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

# --- IMPORTACIÓN CLAVE: Traemos la lógica de evaluación de infracciones ---
from app.scoring.engine import evaluate_device

# --- Constante de Conversión ---
KNOTS_TO_KMH = 1.852
# Variable global para rastrear el último día que se envió el reporte
last_report_sent_day = None


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

    # --- TIMEZONE DE COLOMBIA ---
    colombia_tz = pytz.timezone('America/Bogota')
    now_colombia = datetime.now(colombia_tz)
    now_utc = now_colombia.astimezone(pytz.utc)
    
    # Parsear la fecha del GPS
    fix_time_str = last_pos['fixTime'].replace('Z', '+00:00')
    fix_time_utc = datetime.fromisoformat(fix_time_str)
    
    if fix_time_utc.tzinfo is None:
        fix_time_utc = pytz.utc.localize(fix_time_utc)
    
    fix_time_colombia = fix_time_utc.astimezone(colombia_tz)
    
    # --- CLASIFICACIÓN DE TIPO DE MOVIMIENTO ---
    speed_knots = last_pos.get('speed', 0)
    speed_kmh = speed_knots * KNOTS_TO_KMH
    
    # Lógica de clasificación inteligente:
    # - Velocidad < 8 km/h = Caminando
    # - Velocidad >= 8 km/h = Vehículo
    if speed_kmh < 8:
        movement_type = 'walking'
        movement_emoji = '🚶'
        movement_label = 'CAMINANDO'
    else:
        movement_type = 'vehicle'
        movement_emoji = '🚗'
        movement_label = 'VEHÍCULO'
    
    age_seconds = (now_utc - fix_time_utc).total_seconds()
    print(f"[Diagnóstico Hilo Fondo] Última posición encontrada.")
    print(f"[Diagnóstico Hilo Fondo] Hora GPS (Colombia): {fix_time_colombia.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[Diagnóstico Hilo Fondo] Velocidad: {speed_kmh:.2f} km/h ({movement_emoji} {movement_label})")
    print(f"[Diagnóstico Hilo Fondo] Antigüedad: {age_seconds:.0f} segundos ({age_seconds/60:.1f} minutos)")

    # Solo consideramos posiciones recientes (últimas 24 horas)
    if age_seconds > 86400:
        print("[Diagnóstico Hilo Fondo] Posición demasiado antigua (>24h). Ignorando.")
        return

    for ally in all_allies:
        distance = haversine_distance(last_pos['latitude'], last_pos['longitude'], ally.latitude, ally.longitude)
        print(f"[Diagnóstico Hilo Fondo] Distancia a '{ally.name}': {distance:.2f}m (Radio requerido: {ally.radius}m)")

        if distance <= ally.radius:
            settings = {s.key: s.value for s in Setting.query.all()}
            visit_interval_minutes = int(settings.get('visit_interval', 60))
            
            last_visit = Visit.query.filter_by(device_id=device_id, ally_id=ally.id)\
                .order_by(Visit.timestamp.desc()).first()

            if last_visit:
                if last_visit.timestamp.tzinfo is None:
                    last_visit_utc = pytz.utc.localize(last_visit.timestamp)
                else:
                    last_visit_utc = last_visit.timestamp.astimezone(pytz.utc)
                
                time_since_last = (fix_time_utc - last_visit_utc).total_seconds() / 60
                
                if time_since_last < visit_interval_minutes:
                    print(f"[Diagnóstico Hilo Fondo] Visita a '{ally.name}' ya registrada hace {time_since_last:.1f} min.")
                    print(f"[Diagnóstico Hilo Fondo] Esperando intervalo de {visit_interval_minutes} min.")
                    continue

            print(f"\n{'='*80}")
            print(f"🎯 ¡NUEVA VISITA AUTOMÁTICA DETECTADA!")
            print(f"{'='*80}")
            print(f"   Dispositivo: {device_name} (ID: {device_id})")
            print(f"   Aliado: {ally.name}")
            print(f"   Tipo de Movimiento: {movement_emoji} {movement_label}")
            print(f"   Velocidad Registrada: {speed_kmh:.2f} km/h")
            print(f"   Fecha/Hora (Colombia): {fix_time_colombia.strftime('%d/%m/%Y %H:%M:%S')}")
            print(f"   Distancia al Punto: {distance:.2f} metros")
            print(f"   Precisión GPS: {last_pos.get('accuracy', 'N/A')} metros")
            print(f"{'='*80}\n")
            
            user = User.query.filter_by(traccar_device_id=device_id).first()
            
            # Guardar visita con clasificación
            new_visit = Visit(
                timestamp=fix_time_utc.replace(tzinfo=None),
                device_id=device_id,
                user_id=user.id if user else None,
                ally_id=ally.id,
                is_manual=False,
                movement_type=movement_type,  # ← NUEVO: Clasificación
                avg_speed=round(speed_kmh, 2)  # ← NUEVO: Velocidad
            )
            db.session.add(new_visit)
            db.session.commit()
            print(f"✅ Visita guardada exitosamente")
            print(f"   - Tipo: {movement_label}")
            print(f"   - Velocidad: {speed_kmh:.2f} km/h\n")
            break  # Solo una visita por evaluación

def run_periodic_evaluation_bg(app):
    """Función principal que se ejecuta en el hilo para evaluar infracciones y visitas."""
    colombia_tz = pytz.timezone('America/Bogota')
    now_colombia = datetime.now(colombia_tz)
    print(f"\n{'='*80}")
    print(f"🔄 EJECUTANDO EVALUACIÓN COMPLETA")
    print(f"{'='*80}")
    print(f"Hora (Colombia): {now_colombia.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*80}\n")
    
    devices = get_devices_bg(app)
    if devices:
        with app.app_context():
            # --- 1. EVALUAR INFRACCIONES ---
            print("[Evaluación Infracciones] Iniciando análisis de reglas...")
            for device in devices:
                try:
                    evaluate_device(device)
                except Exception as e:
                    print(f"[ERROR] Error al evaluar infracciones del dispositivo {device.get('name')}: {e}")
            
            # --- 2. EVALUAR VISITAS AUTOMÁTICAS ---
            print("\n[Evaluación Visitas] Iniciando detección de visitas...")
            all_allies = Ally.query.all()
            if not all_allies:
                print("[Diagnóstico Hilo Fondo] No hay aliados configurados para verificar visitas.")
            else:
                for device in devices:
                    try:
                        check_for_visits_bg(app, device, all_allies)
                    except Exception as e:
                        print(f"[ERROR] Error al evaluar visitas del dispositivo {device.get('name')}: {e}")
    
    print(f"\n{'='*80}")
    print(f"✅ EVALUACIÓN FINALIZADA")
    print(f"{'='*80}\n")

def check_and_send_report_bg(app):
    """Verifica si es hora de enviar el reporte diario y lo hace si corresponde."""
    global last_report_sent_day
    with app.app_context():
        settings = {s.key: s.value for s in Setting.query.all()}
        report_time_str = settings.get('report_time')
        report_recipients_str = settings.get('report_recipients')

        if not report_time_str or not report_recipients_str:
            return

        colombia_tz = pytz.timezone('America/Bogota')
        now_colombia = datetime.now(colombia_tz)
        
        try:
            report_hour, report_minute = map(int, report_time_str.split(':'))
        except ValueError:
            print("[ERROR Hilo Fondo] El formato de la hora del reporte es inválido.")
            return

        if (now_colombia.hour == report_hour and 
            now_colombia.minute == report_minute and
            now_colombia.date() != last_report_sent_day):
            
            print("\n" + "="*80)
            print("📧 INICIANDO ENVÍO DE REPORTE DIARIO AUTOMÁTICO")
            print("="*80)
            
            recipients = [email.strip() for email in report_recipients_str.split(',') if email.strip()]
            report_data = generate_report_data()
            
            if send_report_email(recipients, report_data):
                last_report_sent_day = now_colombia.date()
                print("✅ REPORTE DIARIO ENVIADO EXITOSAMENTE")
            else:
                print("❌ ERROR AL ENVIAR EL REPORTE DIARIO")
            
            print("="*80 + "\n")

# Creamos la aplicación
app = create_app()

def background_task(app_context):
    """Esta es la función que se ejecuta en el hilo de fondo."""
    print("\n" + "="*80)
    print("🚀 HILO DE FONDO INICIADO")
    print("="*80)
    print("⏱️  Evaluación cada 60 segundos")
    print("📍 Detección automática de visitas: ACTIVA")
    print("⚠️  Monitoreo de infracciones: ACTIVO")
    print("🚗 Clasificación vehículo/caminando: ACTIVA")
    print("="*80 + "\n")
    
    while True:
        with app_context():
            current_app_obj = current_app._get_current_object()
            run_periodic_evaluation_bg(current_app_obj)
            check_and_send_report_bg(current_app_obj)
        time.sleep(60)

if __name__ == '__main__':
    eval_thread = Thread(target=background_task, args=(app.app_context,), daemon=True)
    eval_thread.start()

    print("\n" + "="*80)
    print("🌐 INICIANDO SERVIDOR WEB CON WAITRESS")
    print("="*80)
    print(f"📍 Servidor: http://127.0.0.1:5000")
    print(f"🕐 Zona horaria: America/Bogota (COT)")
    print(f"⏰ Hora actual: {datetime.now(pytz.timezone('America/Bogota')).strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80 + "\n")
    
    serve(app, host='127.0.0.1', port=5000)