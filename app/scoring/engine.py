# Ruta: SST/app/scoring/engine.py

# --- LÍNEA DE VERIFICACIÓN ---
print("\n>>> CARGANDO VERSIÓN FINAL Y CORRECTA DE engine.py <<<\n")

from app import db
from app.models import Rule, Infraction, User
from datetime import datetime, time, timedelta
import pytz
from app.email import send_infraction_alert
import requests
from flask import current_app

KNOTS_TO_KMH = 1.852

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

# --- "CEREBRO" ACTUALIZADO PARA USAR POSICIONES CRUDAS ---
def evaluate_device(device):
    device_id = device.get('id'); device_name = device.get('name')
    print(f"--- Evaluando (usando posiciones): {device_name} (ID: {device_id}) ---")
    active_rules = Rule.query.filter_by(is_active=True).all()
    if not active_rules: return

    colombia_tz = pytz.timezone('America/Bogota'); now = datetime.now(colombia_tz)
    today_start = colombia_tz.localize(datetime.combine(now.date(), time.min))
    
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
                infraction_details = { 'measured_value': f"{speed_kmh:.2f} km/h", 'log_message': f"NUEVA INFRACCIÓN: {device_name} - Exceso de velocidad ({speed_kmh:.2f} km/h)" }
            elif rule.rule_type == 'harsh_acceleration' and attributes.get('alarm') == 'hardAcceleration':
                infraction_details = { 'measured_value': "Evento Detectado", 'log_message': f"NUEVA INFRACCIÓN: {device_name} - Aceleración Brusca" }
            elif rule.rule_type == 'harsh_braking' and attributes.get('alarm') == 'hardBraking':
                infraction_details = { 'measured_value': "Evento Detectado", 'log_message': f"NUEVA INFRACCIÓN: {device_name} - Frenada Brusca" }

            if infraction_details:
                if not Infraction.query.filter_by(device_id=device_id, rule_id=rule.id, timestamp=infraction_time).first():
                    new_infraction = Infraction(device_id=device_id, user_id=user.id if user else None, rule_id=rule.id, measured_value=infraction_details['measured_value'], timestamp=infraction_time)
                    db.session.add(new_infraction)
                    new_infractions_found.append(new_infraction)
                    print(infraction_details['log_message'])
    
    if new_infractions_found:
        db.session.commit()
        print(f"Enviando {len(new_infractions_found)} alerta(s)...")
        for infraction in new_infractions_found:
            db.session.refresh(infraction); send_infraction_alert(infraction, device_name)

def run_periodic_evaluation():
    print(f"\n--- EJECUTANDO EVALUACIÓN PERIÓDICA (usando posiciones) ---")
    from app import create_app
    app = create_app()
    with app.app_context():
        devices = get_devices_local()
        if devices:
            for device in devices: evaluate_device(device)
    print(f"--- EVALUACIÓN FINALIZADA ---\n")

def calculate_driving_score(device_id, days=30):
    now = datetime.now(pytz.timezone('America/Bogota'))
    period_start = now - timedelta(days=days)
    infractions = Infraction.query.filter(Infraction.device_id == device_id, Infraction.timestamp >= period_start).all()
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

