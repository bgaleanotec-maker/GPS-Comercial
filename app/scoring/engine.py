
Engine · PY
Copiar

# Ruta: SST/app/scoring/engine.py

# --- LÍNEA DE VERIFICACIÓN ---
print("\n>>> CARGANDO VERSIÓN CON PRIVACIDAD HABILITADA de engine.py <<<\n")

from app import db
from app.models import Rule, Infraction, User, Setting
from datetime import datetime, time as dt_time, timedelta
import pytz
from app.email import send_infraction_alert
import requests
from flask import current_app

KNOTS_TO_KMH = 1.852


# --- NUEVA FUNCIÓN: VERIFICACIÓN DE HORARIO LABORAL ---
def is_working_hours():
    """
    Verifica si estamos en horario laboral según la configuración.
    🔒 Protege la privacidad de los empleados fuera de horario.
    """
    settings = {s.key: s.value for s in Setting.query.all()}
    
    # Obtener configuración de días y horarios
    active_days_str = settings.get('active_days', '1,2,3,4,5')
    start_time_str = settings.get('start_time', '06:00')
    end_time_str = settings.get('end_time', '20:00')
    
    # Obtener hora actual en Colombia
    colombia_tz = pytz.timezone('America/Bogota')
    now_colombia = datetime.now(colombia_tz)
    
    # Verificar día de la semana
    current_day = str(now_colombia.weekday() + 1)
    if current_day == '7':
        current_day = '0'
    
    active_days = active_days_str.split(',')
    
    if current_day not in active_days:
        return False
    
    # Verificar hora del día
    try:
        start_hour, start_minute = map(int, start_time_str.split(':'))
        end_hour, end_minute = map(int, end_time_str.split(':'))
        
        start_time = dt_time(start_hour, start_minute)
        end_time = dt_time(end_hour, end_minute)
        current_time = now_colombia.time()
        
        if not (start_time <= current_time <= end_time):
            return False
    except ValueError:
        return False
    
    return True


# --- LÓGICA DE TRACCAR ACTUALIZADA ---

def _get_traccar_session():
    session = requests.Session()
    session.auth = (current_app.config['TRACCAR_USER'], current_app.config['TRACCAR_PASSWORD'])
    return session

def get_devices_local():
    base_url = current_app.config['TRACCAR_URL']
    session = _get_traccar_session()
    try:
        response = session.get(f"{base_url}/api/devices")
        response.raise_for_status()
        return response.json()
    except (requests.exceptions.RequestException, requests.exceptions.JSONDecodeError) as e:
        print(f"Error de conexión (get_devices_local): {e}")
        return None

# --- ¡FUNCIÓN CLAVE PARA OBTENER DATOS CRUDOS! ---
def get_device_positions_local(device_id, from_time, to_time):
    """
    Obtiene la lista de posiciones GPS crudas, bypassando el motor de reportes de Traccar.
    """
    base_url = current_app.config['TRACCAR_URL']
    session = _get_traccar_session()
    params = {
        'deviceId': device_id,
        'from': from_time.astimezone(pytz.utc).isoformat(),
        'to': to_time.astimezone(pytz.utc).isoformat(),
    }
    try:
        response = session.get(f"{base_url}/api/positions", params=params)
        response.raise_for_status()
        try:
            return response.json()
        except requests.exceptions.JSONDecodeError:
            print(f"Advertencia: Traccar devolvió una respuesta no-JSON para las posiciones del dispositivo {device_id}.")
            return []
    except requests.exceptions.RequestException as e:
        print(f"Error de conexión (get_device_positions_local): {e}")
        return None

# --- "CEREBRO" ACTUALIZADO CON RESPETO A PRIVACIDAD ---
def evaluate_device(device):
    """
    Evalúa infracciones SOLO si estamos en horario laboral.
    🔒 Protege la privacidad de los empleados.
    """
    # ✅ VERIFICACIÓN DE PRIVACIDAD
    if not is_working_hours():
        return  # No evaluar fuera de horario laboral
    
    device_id = device.get('id')
    device_name = device.get('name')
    print(f"--- Evaluando (usando posiciones): {device_name} (ID: {device_id}) ---")
    active_rules = Rule.query.filter_by(is_active=True).all()
    if not active_rules:
        return

    colombia_tz = pytz.timezone('America/Bogota')
    now = datetime.now(colombia_tz)
    today_start = colombia_tz.localize(datetime.combine(now.date(), dt_time.min))
    
    positions_data = get_device_positions_local(device_id, today_start, now)
    
    if not positions_data:
        print(f"No se encontraron posiciones GPS para {device_name} hoy.")
        return
        
    user = User.query.filter_by(traccar_device_id=device_id).first()
    new_infractions_found = []

    for point in positions_data:
        infraction_time = datetime.fromisoformat(point.get('fixTime').replace('Z', '+00:00'))
        attributes = point.get('attributes', {})
        for rule in active_rules:
            infraction_details = None
            if rule.rule_type == 'max_speed' and (speed_kmh := point.get('speed', 0) * KNOTS_TO_KMH) > rule.value:
                infraction_details = {
                    'measured_value': f"{speed_kmh:.2f} km/h",
                    'log_message': f"NUEVA INFRACCIÓN: {device_name} - Exceso de velocidad ({speed_kmh:.2f} km/h)"
                }
            elif rule.rule_type == 'harsh_acceleration' and attributes.get('alarm') == 'hardAcceleration':
                infraction_details = {
                    'measured_value': "Evento Detectado",
                    'log_message': f"NUEVA INFRACCIÓN: {device_name} - Aceleración Brusca"
                }
            elif rule.rule_type == 'harsh_braking' and attributes.get('alarm') == 'hardBraking':
                infraction_details = {
                    'measured_value': "Evento Detectado",
                    'log_message': f"NUEVA INFRACCIÓN: {device_name} - Frenada Brusca"
                }

            if infraction_details:
                if not Infraction.query.filter_by(device_id=device_id, rule_id=rule.id, timestamp=infraction_time).first():
                    new_infraction = Infraction(
                        device_id=device_id,
                        user_id=user.id if user else None,
                        rule_id=rule.id,
                        measured_value=infraction_details['measured_value'],
                        timestamp=infraction_time
                    )
                    db.session.add(new_infraction)
                    new_infractions_found.append(new_infraction)
                    print(infraction_details['log_message'])
    
    if new_infractions_found:
        db.session.commit()
        print(f"Enviando {len(new_infractions_found)} alerta(s)...")
        for infraction in new_infractions_found:
            db.session.refresh(infraction)
            send_infraction_alert(infraction, device_name)

def run_periodic_evaluation():
    """
    Ejecuta la evaluación periódica respetando horario laboral.
    """
    print(f"\n--- EJECUTANDO EVALUACIÓN PERIÓDICA (usando posiciones) ---")
    from app import create_app
    app = create_app()
    with app.app_context():
        if not is_working_hours():
            print("[PRIVACIDAD] Evaluación saltada - Fuera de horario laboral.")
            return
            
        devices = get_devices_local()
        if devices:
            for device in devices:
                evaluate_device(device)
    print(f"--- EVALUACIÓN FINALIZADA ---\n")

def calculate_driving_score(device_id, days=30):
    now = datetime.now(pytz.timezone('America/Bogota'))
    period_start = now - timedelta(days=days)
    infractions = Infraction.query.filter(
        Infraction.device_id == device_id,
        Infraction.timestamp >= period_start
    ).all()
    total_penalty_points = sum(infraction.rule.points for infraction in infractions)
    score = max(0, 100 - total_penalty_points)
    return score, len(infractions)

# Funciones de compatibilidad
def get_device_by_id_local(device_id):
    all_devices = get_devices_local()
    if all_devices:
        return next((d for d in all_devices if d['id'] == device_id), None)
    return None

def get_device_summary_local(device_id, from_time, to_time):
    return None