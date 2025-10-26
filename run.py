from app import create_app
from threading import Thread
import time
from waitress import serve
import requests
from flask import current_app
from datetime import datetime, time as dt_time, timedelta
import pytz
from math import radians, sin, cos, sqrt, atan2

# Importamos los modelos y la función de email directamente
from app import db
from app.models import Rule, Infraction, User, Ally, Visit, Setting
from app.email import send_infraction_alert, send_report_email
from app.reporting_logic import generate_report_data


# --- Constante de Conversión ---
KNOTS_TO_KMH = 1.852
# Variable global para rastrear el último día que se envió el reporte
last_report_sent_day = None


# --- NUEVA FUNCIÓN: VERIFICACIÓN DE HORARIO LABORAL ---
def is_working_hours(app):
    """
    Verifica si estamos en horario laboral según la configuración.
    Retorna True solo si:
    1. Es un día laboral configurado
    2. Está dentro del rango de horas configurado
    
    Esto respeta la privacidad de los empleados fuera de horario.
    """
    with app.app_context():
        settings = {s.key: s.value for s in Setting.query.all()}
        
        # Obtener configuración de días y horarios
        active_days_str = settings.get('active_days', '1,2,3,4,5')  # Default: Lunes a Viernes
        start_time_str = settings.get('start_time', '06:00')
        end_time_str = settings.get('end_time', '20:00')
        
        # Obtener hora actual en Colombia
        colombia_tz = pytz.timezone('America/Bogota')
        now_colombia = datetime.now(colombia_tz)
        
        # Verificar día de la semana (0=Domingo, 1=Lunes, ..., 6=Sábado)
        current_day = str(now_colombia.weekday() + 1)
        if current_day == '7':  # Si es domingo, convertir a 0
            current_day = '0'
        
        active_days = active_days_str.split(',')
        
        if current_day not in active_days:
            print(f"[PRIVACIDAD] Hoy no es día laboral. No se registrará actividad.")
            return False
        
        # Verificar hora del día
        try:
            start_hour, start_minute = map(int, start_time_str.split(':'))
            end_hour, end_minute = map(int, end_time_str.split(':'))
            
            start_time = dt_time(start_hour, start_minute)
            end_time = dt_time(end_hour, end_minute)
            current_time = now_colombia.time()
            
            if not (start_time <= current_time <= end_time):
                print(f"[PRIVACIDAD] Fuera de horario laboral ({start_time_str} - {end_time_str}). No se registrará actividad.")
                return False
        except ValueError:
            print("[ERROR] Formato de hora inválido en configuración.")
            return False
    
    return True


# --- Lógica de Traccar para el Hilo de Fondo (Integrada) ---

def _get_traccar_session_bg(app):
    """Obtiene una sesión de requests con las credenciales de la app."""
    session = requests.Session()
    session.auth = (app.config['TRACCAR_USER'], app.config['TRACCAR_PASSWORD'])
    return session

def get_devices_bg(app):
    """Obtiene la lista de dispositivos (versión para el hilo de fondo)."""
    session = _get_traccar_session_bg(app)
    base_url = app.config['TRACCAR_URL']
    try:
        response = session.get(f"{base_url}/api/devices")
        response.raise_for_status()
        print("[Diagnóstico Hilo Fondo] Conexión con Traccar exitosa. Dispositivos obtenidos.")
        return response.json()
    except Exception as e:
        print(f"[ERROR Hilo Fondo] No se pudo conectar con Traccar para obtener dispositivos: {e}")
        return None

def get_latest_position_bg(app, device_id):
    """Obtiene la última posición registrada para un dispositivo, sin importar la antigüedad."""
    session = _get_traccar_session_bg(app)
    base_url = app.config['TRACCAR_URL']
    params = {'deviceId': device_id, 'limit': 1}
    try:
        response = session.get(f"{base_url}/api/positions", params=params)
        response.raise_for_status()
        positions = response.json()
        return positions[0] if positions else None
    except Exception as e:
        print(f"[ERROR Hilo Fondo] Error al obtener la última posición para el dispositivo {device_id}: {e}")
        return None

def haversine_distance(lat1, lon1, lat2, lon2):
    """Calcula la distancia en metros entre dos puntos geográficos."""
    R = 6371000  # Radio de la Tierra en metros
    lat1_rad, lon1_rad = radians(lat1), radians(lon1)
    lat2_rad, lon2_rad = radians(lat2), radians(lon2)
    dlon, dlat = lon2_rad - lon1_rad, lat2_rad - lat1_rad
    a = sin(dlat / 2)**2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2)**2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c

def check_for_visits_bg(app, device, all_allies):
    """Comprueba si la última posición de un dispositivo está dentro del radio de algún aliado."""
    device_id = device.get('id')
    device_name = device.get('name')
    print(f"[Diagnóstico Hilo Fondo] Buscando última posición para dispositivo {device_name} (ID: {device_id})...")
    
    last_pos = get_latest_position_bg(app, device_id)
    if not last_pos:
        print(f"[Diagnóstico Hilo Fondo] No se encontró posición GPS para el dispositivo {device_name}.")
        return

    now_utc = datetime.now(pytz.utc)
    fix_time_utc = datetime.fromisoformat(last_pos['fixTime'].replace('Z', '+00:00'))
    age_seconds = (now_utc - fix_time_utc).total_seconds()
    print(f"[Diagnóstico Hilo Fondo] Última posición encontrada. Antigüedad: {age_seconds:.0f} segundos.")

    # Solo consideramos posiciones de las últimas 24 horas para la prueba
    if age_seconds > 86400:
        print("[Diagnóstico Hilo Fondo] La última posición es demasiado antigua para ser considerada para una visita.")
        return

    for ally in all_allies:
        distance = haversine_distance(last_pos['latitude'], last_pos['longitude'], ally.latitude, ally.longitude)
        print(f"[Diagnóstico Hilo Fondo] Distancia a '{ally.name}': {distance:.2f} metros. (Radio requerido: {ally.radius}m)")

        if distance <= ally.radius:
            settings = {s.key: s.value for s in Setting.query.all()}
            visit_interval_minutes = int(settings.get('visit_interval', 60))
            
            last_visit = Visit.query.filter_by(device_id=device_id, ally_id=ally.id)\
                .order_by(Visit.timestamp.desc()).first()

            if last_visit and (fix_time_utc - last_visit.timestamp.replace(tzinfo=pytz.utc)) < timedelta(minutes=visit_interval_minutes):
                print(f"[Diagnóstico Hilo Fondo] Visita a '{ally.name}' ya registrada recientemente. Esperando intervalo.")
                continue

            print(f"--- ¡NUEVA VISITA AUTOMÁTICA DETECTADA! Dispositivo: {device_name}, Aliado: {ally.name} ---")
            user = User.query.filter_by(traccar_device_id=device_id).first()
            new_visit = Visit(
                timestamp=fix_time_utc,
                device_id=device_id,
                user_id=user.id if user else None,
                ally_id=ally.id,
                is_manual=False
            )
            db.session.add(new_visit)
            db.session.commit()
            break # Solo registramos una visita por evaluación para evitar duplicados

def run_periodic_evaluation_bg(app):
    """
    Función principal que se ejecuta en el hilo para evaluar infracciones y visitas.
    🔒 RESPETA HORARIO LABORAL - Solo monitorea en días/horas configurados.
    """
    # ✅ VERIFICACIÓN DE PRIVACIDAD
    if not is_working_hours(app):
        print(f"[PRIVACIDAD] Evaluación saltada - Fuera de horario laboral.")
        return
    
    print(f"--- EJECUTANDO EVALUACIÓN: {datetime.now()} ---")
    devices = get_devices_bg(app)
    if devices:
        with app.app_context():
            all_allies = Ally.query.all()
            if not all_allies:
                print("[Diagnóstico Hilo Fondo] No hay aliados configurados para verificar visitas.")
            for device in devices:
                # Lógica de visitas automáticas
                if all_allies:
                    check_for_visits_bg(app, device, all_allies)
    print("--- EVALUACIÓN FINALIZADA ---\n")

def check_and_send_report_bg(app):
    """Verifica si es hora de enviar el reporte diario y lo hace si corresponde."""
    global last_report_sent_day
    with app.app_context():
        settings = {s.key: s.value for s in Setting.query.all()}
        report_time_str = settings.get('report_time')
        report_recipients_str = settings.get('report_recipients')

        if not report_time_str or not report_recipients_str:
            return # No hacer nada si no está configurado

        colombia_tz = pytz.timezone('America/Bogota')
        now_colombia = datetime.now(colombia_tz)
        
        try:
            report_hour, report_minute = map(int, report_time_str.split(':'))
        except ValueError:
            print("[ERROR Hilo Fondo] El formato de la hora del reporte es inválido.")
            return

        # Comprobamos si es la hora y si no hemos enviado el reporte hoy
        if (now_colombia.hour == report_hour and now_colombia.minute == report_minute and
                now_colombia.date() != last_report_sent_day):
            
            print("--- INICIANDO ENVÍO DE REPORTE DIARIO AUTOMÁTICO ---")
            recipients = [email.strip() for email in report_recipients_str.split(',') if email.strip()]
            
            # Generamos los datos para el reporte
            report_data = generate_report_data()
            
            # Enviamos el correo
            send_report_email(recipients, report_data)
            
            # Actualizamos la fecha del último envío para no repetir
            last_report_sent_day = now_colombia.date()
            print("--- ENVÍO DE REPORTE DIARIO FINALIZADO ---")

# Creamos la aplicación
app = create_app()

def background_task(app_context):
    """Esta es la función que se ejecuta en el hilo de fondo."""
    print("\n--- Hilo de fondo iniciado. La evaluación se ejecutará cada 60 segundos. ---")
    print("🔒 MODO PRIVACIDAD ACTIVADO: Solo se monitoreará en días/horas laborales configurados.")
    while True:
        with app_context():
            # Pasamos la instancia de la app a las funciones
            current_app_obj = current_app._get_current_object()
            run_periodic_evaluation_bg(current_app_obj)
            check_and_send_report_bg(current_app_obj)
        time.sleep(60)

if __name__ == '__main__':
    # Creamos e iniciamos el hilo de fondo
    eval_thread = Thread(target=background_task, args=(app.app_context,), daemon=True)
    eval_thread.start()

    # Iniciamos el servidor web
    print("\n--- INICIANDO SERVIDOR WEB CON WAITRESS ---")
    print(f"Servidor corriendo en http://127.0.0.1:5000")
    print("-----------------------------------------\n")
    serve(app, host='127.0.0.1', port=5000)