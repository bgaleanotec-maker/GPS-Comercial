# Ruta: SST/app/main/routes.py
from flask import render_template, abort, current_app, flash
from app.main import bp
from flask_login import login_required, current_user
from datetime import datetime, time, timedelta
import pytz
import locale
import requests
from math import radians, sin, cos, sqrt, atan2

# Importamos los modelos directamente
from app.models import Infraction, User, Rule, Setting

# --- Lógica de Traccar y Cálculos para las Vistas (Integrada) ---
KNOTS_TO_KMH = 1.852


# --- 🔒 NUEVA FUNCIÓN: FILTRAR POSICIONES POR HORARIO LABORAL ---
def filter_positions_by_working_hours(positions):
    """
    Filtra posiciones GPS para quedarse SOLO con las que ocurrieron
    durante días y horarios laborales configurados.
    
    Esto elimina el "ruido" de kilómetros personales para:
    - Cálculo de bonos
    - Auxilios de transporte
    - Kilometraje productivo
    """
    if not positions:
        return []
    
    # Obtener configuración de días y horarios laborales
    settings = {s.key: s.value for s in Setting.query.all()}
    active_days_str = settings.get('active_days', '1,2,3,4,5')  # Default: Lun-Vie
    start_time_str = settings.get('start_time', '06:00')
    end_time_str = settings.get('end_time', '20:00')
    
    active_days = active_days_str.split(',')
    
    try:
        start_hour, start_minute = map(int, start_time_str.split(':'))
        end_hour, end_minute = map(int, end_time_str.split(':'))
        start_time = time(start_hour, start_minute)
        end_time = time(end_hour, end_minute)
    except ValueError:
        # Si hay error en configuración, devolver todas las posiciones
        return positions
    
    # Filtrar posiciones
    filtered = []
    colombia_tz = pytz.timezone('America/Bogota')
    
    for pos in positions:
        try:
            # Obtener timestamp de la posición
            fix_time = datetime.fromisoformat(pos.get('fixTime', '').replace('Z', '+00:00'))
            fix_time_col = fix_time.astimezone(colombia_tz)
            
            # Verificar día de la semana (0=Domingo, 1=Lunes, ..., 6=Sábado)
            day_of_week = str(fix_time_col.weekday() + 1)
            if day_of_week == '7':  # Domingo
                day_of_week = '0'
            
            # Si no es día laboral, saltar
            if day_of_week not in active_days:
                continue
            
            # Verificar hora del día
            pos_time = fix_time_col.time()
            if not (start_time <= pos_time <= end_time):
                continue
            
            # Esta posición SÍ es laboral
            filtered.append(pos)
            
        except Exception:
            # Si hay error procesando esta posición, la omitimos
            continue
    
    return filtered


def _get_traccar_session():
    """Obtiene una sesión de requests con las credenciales de la app."""
    session = requests.Session()
    session.auth = (current_app.config['TRACCAR_USER'], current_app.config['TRACCAR_PASSWORD'])
    return session

def get_devices_view():
    """Obtiene la lista de dispositivos (versión para las vistas)."""
    base_url = current_app.config['TRACCAR_URL']
    session = _get_traccar_session()
    try:
        response = session.get(f"{base_url}/api/devices")
        response.raise_for_status()
        return response.json()
    except Exception:
        return None

def get_device_by_id_view(device_id):
    """Obtiene un dispositivo por su ID (versión para las vistas)."""
    all_devices = get_devices_view()
    if all_devices:
        return next((d for d in all_devices if d['id'] == device_id), None)
    return None

def get_device_positions_view(device_id, from_time, to_time):
    """
    Obtiene las posiciones GPS FILTRADAS por horario laboral.
    🔒 Solo devuelve posiciones de días/horas laborales.
    """
    base_url = current_app.config['TRACCAR_URL']
    session = _get_traccar_session()
    params = {
        'deviceId': device_id,
        'from': from_time.astimezone(pytz.utc).isoformat(),
        'to': to_time.astimezone(pytz.utc).isoformat()
    }
    try:
        response = session.get(f"{base_url}/api/positions", params=params)
        response.raise_for_status()
        all_positions = response.json()
        
        # 🔒 FILTRAR POR HORARIO LABORAL
        filtered_positions = filter_positions_by_working_hours(all_positions)
        
        return filtered_positions
    except Exception:
        return []

def calculate_distance_from_points(positions):
    """Calcula la distancia total en metros a partir de una lista de puntos GPS."""
    total_distance = 0
    R = 6371000  # Radio de la Tierra en metros
    if not positions or len(positions) < 2:
        return 0
    for i in range(len(positions) - 1):
        pos1, pos2 = positions[i], positions[i+1]
        lat1_rad, lon1_rad = radians(pos1['latitude']), radians(pos1['longitude'])
        lat2_rad, lon2_rad = radians(pos2['latitude']), radians(pos2['longitude'])
        dlon, dlat = lon2_rad - lon1_rad, lat2_rad - lat1_rad
        a = sin(dlat / 2)**2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2)**2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))
        total_distance += R * c
    return total_distance

def calculate_driving_score_view(device_id, days=30):
    """Calcula el Score de Conducción (versión para las vistas)."""
    now = datetime.now(pytz.timezone('America/Bogota'))
    period_start = now - timedelta(days=days)
    infractions = Infraction.query.filter(
        Infraction.device_id == device_id,
        Infraction.timestamp >= period_start
    ).all()
    total_penalty_points = sum(infraction.rule.points for infraction in infractions)
    score = max(0, 100 - total_penalty_points)
    return score, len(infractions)

# --- FIN Lógica Integrada ---


@bp.route('/')
@bp.route('/index')
def index():
    return render_template('index.html', title='Inicio')

@bp.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'admin':
        devices = get_devices_view()
        if devices:
            colombia_tz = pytz.timezone('America/Bogota')
            now = datetime.now(colombia_tz)
            today_start = colombia_tz.localize(datetime.combine(now.date(), time.min))
            month_start = today_start.replace(day=1)
            total_start = colombia_tz.localize(datetime(2000, 1, 1))
            
            for device in devices:
                # 🔒 SOLO POSICIONES DE HORARIO LABORAL
                positions_today = get_device_positions_view(device['id'], today_start, now)
                positions_month = get_device_positions_view(device['id'], month_start, now)
                positions_total = get_device_positions_view(device['id'], total_start, now)
                
                device['distance_today_meters'] = calculate_distance_from_points(positions_today)
                device['distance_month_meters'] = calculate_distance_from_points(positions_month)
                device['distance_total_meters'] = calculate_distance_from_points(positions_total)
                
                device['distance_today'] = device['distance_today_meters'] / 1000
                device['distance_month'] = device['distance_month_meters'] / 1000
                device['distance_total'] = device['distance_total_meters'] / 1000
        else:
            flash('No se pudo conectar a Traccar para obtener la lista de dispositivos.', 'danger')
        return render_template('admin_dashboard.html', title='Dashboard Admin', devices=devices)
    
    elif current_user.role == 'empleado':
        if not current_user.traccar_device_id:
            flash('Tu usuario no está asociado a ningún dispositivo.', 'danger')
            return render_template('employee_dashboard.html', title='Mi Dashboard')

        device = get_device_by_id_view(current_user.traccar_device_id)
        
        if not device:
            flash('El dispositivo asociado a tu cuenta no fue encontrado en Traccar.', 'danger')
            return render_template('admin_dashboard.html', title='Mi Dashboard', devices=[])

        # Calculamos los datos del resumen para el único dispositivo del empleado
        colombia_tz = pytz.timezone('America/Bogota')
        now = datetime.now(colombia_tz)
        today_start = colombia_tz.localize(datetime.combine(now.date(), time.min))
        month_start = today_start.replace(day=1)
        total_start = colombia_tz.localize(datetime(2000, 1, 1))
        
        # 🔒 SOLO POSICIONES DE HORARIO LABORAL
        positions_today = get_device_positions_view(device['id'], today_start, now)
        positions_month = get_device_positions_view(device['id'], month_start, now)
        positions_total = get_device_positions_view(device['id'], total_start, now)
        
        device['distance_today_meters'] = calculate_distance_from_points(positions_today)
        device['distance_month_meters'] = calculate_distance_from_points(positions_month)
        device['distance_total_meters'] = calculate_distance_from_points(positions_total)
        
        device['distance_today'] = device['distance_today_meters'] / 1000
        device['distance_month'] = device['distance_month_meters'] / 1000
        device['distance_total'] = device['distance_total_meters'] / 1000

        # Usamos la misma plantilla del admin, pero le pasamos una lista con un solo dispositivo
        return render_template('admin_dashboard.html', title='Mi Dashboard', devices=[device])
    else:
        abort(403)

@bp.route('/device/<int:device_id>', methods=['GET', 'POST'])
@login_required
def device_details(device_id):
    # Verificación de permisos: O es admin, o es un empleado viendo su PROPIO dispositivo
    if current_user.role != 'admin' and current_user.traccar_device_id != device_id:
        abort(403)
    
    device = get_device_by_id_view(device_id)
    if not device:
        abort(404)

    # El resto de la función sigue igual...
    score, total_infractions = calculate_driving_score_view(device_id)
    colombia_tz = pytz.timezone('America/Bogota')
    now = datetime.now(colombia_tz)
    today_start = colombia_tz.localize(datetime.combine(now.date(), time.min))
    
    # 🔒 SOLO POSICIONES DE HORARIO LABORAL
    positions_today = get_device_positions_view(device_id, today_start, now)
    distance_today = calculate_distance_from_points(positions_today) / 1000
    
    max_speed_today = 0
    if positions_today:
        max_speed_today = max(p.get('speed', 0) for p in positions_today) * KNOTS_TO_KMH

    infractions_today = Infraction.query.filter(
        Infraction.device_id == device_id,
        Infraction.timestamp >= today_start
    ).order_by(Infraction.timestamp.desc()).all()
    
    try:
        locale.setlocale(locale.LC_TIME, 'es_CO.UTF-8')
    except locale.Error:
        pass
    formatted_date = now.strftime('%d de %B de %Y')
    
    return render_template(
        'device_details.html',
        title=f"Score de {device.get('name', 'Dispositivo')}", 
        device=device,
        score=score,
        total_infractions=total_infractions,
        distance_today=distance_today,
        max_speed_today=max_speed_today,
        route=positions_today, 
        infractions_today=infractions_today,
        current_date=formatted_date
    )