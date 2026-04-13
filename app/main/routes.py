# Ruta: GPS_Comercial/app/main/routes.py
import logging

from flask import render_template, abort, flash, request
from app.main import bp
from flask_login import login_required, current_user
from datetime import datetime, time, timedelta
import pytz
import locale

from app.models import Infraction, Setting
from app.traccar import (
    get_devices, get_device_by_id, get_device_positions,
    KNOTS_TO_KMH, calculate_route_distances
)
from app.utils import haversine_distance, filter_positions_by_working_hours

logger = logging.getLogger(__name__)


def get_device_positions_view(device_id, from_time, to_time):
    """Obtiene posiciones GPS FILTRADAS por horario laboral."""
    all_positions = get_device_positions(device_id, from_time, to_time)
    if all_positions is None:
        return []
    return filter_positions_by_working_hours(all_positions)


def calculate_distance_from_points(positions):
    """Calcula la distancia total en metros a partir de una lista de puntos GPS."""
    if not positions or len(positions) < 2:
        return 0
    total_distance = 0
    for i in range(len(positions) - 1):
        pos1, pos2 = positions[i], positions[i + 1]
        total_distance += haversine_distance(
            pos1['latitude'], pos1['longitude'],
            pos2['latitude'], pos2['longitude']
        )
    return total_distance


def calculate_driving_score_view(device_id, days=30):
    """Calcula el Score de Conduccion."""
    now = datetime.now(pytz.timezone('America/Bogota'))
    period_start = now - timedelta(days=days)
    infractions = Infraction.query.filter(
        Infraction.device_id == device_id,
        Infraction.timestamp >= period_start
    ).all()
    total_penalty_points = sum(infraction.rule.points for infraction in infractions)
    score = max(0, 100 - total_penalty_points)
    return score, len(infractions)


# ============================================================
# RUTAS
# ============================================================

@bp.route('/health')
def health_check():
    return {'status': 'ok'}, 200


@bp.route('/test-wa-send')
def test_wa_send():
    """Ruta temporal para probar WhatsApp desde Render. ELIMINAR despues de verificar."""
    import requests as req_lib
    secret = request.args.get('key', '')
    if secret != 'gps2026test':
        abort(404)
    phone = request.args.get('phone', '573222699322')
    from app.whatsapp import _get_ultramsg_config, _normalize_phone
    instance_id, token = _get_ultramsg_config()
    normalized = _normalize_phone(phone)
    msg = (
        "*GPS Comercial - Test Automatico*\n\n"
        "La integracion con WhatsApp esta funcionando.\n"
        "Credenciales OK."
    )
    url = f"https://api.ultramsg.com/{instance_id}/messages/chat"
    payload = {'token': token, 'to': normalized, 'body': msg}
    try:
        resp = req_lib.post(url, data=payload, timeout=15)
        api_response = resp.json()
    except Exception as e:
        api_response = {'error': str(e)}
    return {
        'instance_id': instance_id,
        'token_preview': token[:8] + '...' if token else 'EMPTY',
        'phone_input': phone,
        'phone_normalized': normalized,
        'api_url': url,
        'api_response': api_response,
    }, 200


@bp.route('/offline')
def offline():
    return render_template('offline.html', title='Sin Conexion')


@bp.route('/')
@bp.route('/index')
def index():
    return render_template('index.html', title='Inicio')


@bp.route('/dashboard')
@login_required
def dashboard():
    from app.models import User
    # Filtro por mercado/categoria
    mercado_filter = request.args.get('mercado', 'all')

    # Lider solo ve su mercado
    if current_user.role == 'lider':
        mercado_filter = current_user.categoria

    if current_user.role in ('admin', 'lider'):
        devices = get_devices()
        if devices:
            # Filtrar por mercado si aplica
            if mercado_filter and mercado_filter != 'all':
                user_device_ids = [u.traccar_device_id for u in User.query.filter_by(categoria=mercado_filter).all() if u.traccar_device_id]
                devices = [d for d in devices if d['id'] in user_device_ids]

            # Agregar info de usuario a cada device
            user_map = {u.traccar_device_id: u for u in User.query.filter(User.traccar_device_id.isnot(None)).all()}
            for d in devices:
                u = user_map.get(d['id'])
                d['employee_name'] = u.full_name if u else None
                d['employee_categoria'] = u.categoria if u else None
                d['employee_status'] = u.employee_status if u else None

            # Obtener categorias unicas para el filtro
            categorias = sorted(set(u.categoria for u in User.query.filter(User.categoria.isnot(None)).all() if u.categoria))

            colombia_tz = pytz.timezone('America/Bogota')
            now = datetime.now(colombia_tz)
            today_start = colombia_tz.localize(datetime.combine(now.date(), time.min))
            month_start = today_start.replace(day=1)
            total_start = colombia_tz.localize(datetime(2000, 1, 1))

            for device in devices:
                positions_today = get_device_positions_view(device['id'], today_start, now)
                positions_month = get_device_positions_view(device['id'], month_start, now)
                positions_total = get_device_positions_view(device['id'], total_start, now)

                device['distance_today_meters'] = calculate_distance_from_points(positions_today)
                device['distance_month_meters'] = calculate_distance_from_points(positions_month)
                device['distance_total_meters'] = calculate_distance_from_points(positions_total)

                device['distance_today'] = device['distance_today_meters'] / 1000
                device['distance_month'] = device['distance_month_meters'] / 1000
                device['distance_total'] = device['distance_total_meters'] / 1000

                # Clasificacion de distancias por modo de transporte
                if positions_today and len(positions_today) >= 2:
                    route_stats = calculate_route_distances(positions_today)
                    device['walking_km_today'] = route_stats['walking_km']
                    device['vehicle_km_today'] = route_stats['vehicle_km']
                    device['max_speed_today'] = route_stats['max_speed_kmh']
                else:
                    device['walking_km_today'] = 0
                    device['vehicle_km_today'] = 0
                    device['max_speed_today'] = 0
        else:
            categorias = []
            flash('No se pudo conectar a Traccar para obtener la lista de dispositivos.', 'danger')
        return render_template('admin_dashboard.html', title='Dashboard Admin', devices=devices,
                               categorias=categorias if devices else [],
                               mercado_filter=mercado_filter)

    elif current_user.role == 'empleado':
        if not current_user.traccar_device_id:
            flash('Tu usuario no esta asociado a ningun dispositivo.', 'danger')
            return render_template('employee_dashboard.html', title='Mi Dashboard')

        device = get_device_by_id(current_user.traccar_device_id)

        if not device:
            flash('El dispositivo asociado a tu cuenta no fue encontrado en Traccar.', 'danger')
            return render_template('admin_dashboard.html', title='Mi Dashboard', devices=[])

        colombia_tz = pytz.timezone('America/Bogota')
        now = datetime.now(colombia_tz)
        today_start = colombia_tz.localize(datetime.combine(now.date(), time.min))
        month_start = today_start.replace(day=1)
        total_start = colombia_tz.localize(datetime(2000, 1, 1))

        positions_today = get_device_positions_view(device['id'], today_start, now)
        positions_month = get_device_positions_view(device['id'], month_start, now)
        positions_total = get_device_positions_view(device['id'], total_start, now)

        device['distance_today_meters'] = calculate_distance_from_points(positions_today)
        device['distance_month_meters'] = calculate_distance_from_points(positions_month)
        device['distance_total_meters'] = calculate_distance_from_points(positions_total)

        device['distance_today'] = device['distance_today_meters'] / 1000
        device['distance_month'] = device['distance_month_meters'] / 1000
        device['distance_total'] = device['distance_total_meters'] / 1000

        # Clasificacion de distancias
        if positions_today and len(positions_today) >= 2:
            route_stats = calculate_route_distances(positions_today)
            device['walking_km_today'] = route_stats['walking_km']
            device['vehicle_km_today'] = route_stats['vehicle_km']
            device['max_speed_today'] = route_stats['max_speed_kmh']
        else:
            device['walking_km_today'] = 0
            device['vehicle_km_today'] = 0
            device['max_speed_today'] = 0

        return render_template('admin_dashboard.html', title='Mi Dashboard', devices=[device])
    else:
        abort(403)


@bp.route('/device/<int:device_id>', methods=['GET', 'POST'])
@login_required
def device_details(device_id):
    if current_user.role not in ('admin', 'lider') and current_user.traccar_device_id != device_id:
        abort(403)

    device = get_device_by_id(device_id)
    if not device:
        abort(404)

    from app.models import User, Visit

    score, total_infractions = calculate_driving_score_view(device_id)
    colombia_tz = pytz.timezone('America/Bogota')
    now = datetime.now(colombia_tz)
    today_start = colombia_tz.localize(datetime.combine(now.date(), time.min))
    week_start = today_start - timedelta(days=now.weekday())
    month_start = today_start.replace(day=1)

    # Posiciones por periodo
    positions_today = get_device_positions_view(device_id, today_start, now)
    positions_week = get_device_positions_view(device_id, week_start, now)
    positions_month = get_device_positions_view(device_id, month_start, now)

    # Distancias
    distance_today = calculate_distance_from_points(positions_today) / 1000
    distance_week = calculate_distance_from_points(positions_week) / 1000
    distance_month = calculate_distance_from_points(positions_month) / 1000

    # Route stats por periodo
    stats_today = calculate_route_distances(positions_today) if positions_today and len(positions_today) >= 2 else None
    stats_week = calculate_route_distances(positions_week) if positions_week and len(positions_week) >= 2 else None
    stats_month = calculate_route_distances(positions_month) if positions_month and len(positions_month) >= 2 else None

    max_speed_today = stats_today['max_speed_kmh'] if stats_today else 0

    # Empleado asignado
    assigned_user = User.query.filter_by(traccar_device_id=device_id).first()

    # Visitas recientes
    visits_today = Visit.query.filter(Visit.device_id == device_id, Visit.timestamp >= today_start).count()
    visits_week = Visit.query.filter(Visit.device_id == device_id, Visit.timestamp >= week_start).count()
    visits_month = Visit.query.filter(Visit.device_id == device_id, Visit.timestamp >= month_start).count()

    # Infracciones
    infractions_today = Infraction.query.filter(
        Infraction.device_id == device_id,
        Infraction.timestamp >= today_start
    ).order_by(Infraction.timestamp.desc()).all()

    infractions_week = Infraction.query.filter(
        Infraction.device_id == device_id,
        Infraction.timestamp >= week_start
    ).count()

    infractions_month = Infraction.query.filter(
        Infraction.device_id == device_id,
        Infraction.timestamp >= month_start
    ).count()

    formatted_date = now.strftime('%d/%m/%Y')

    return render_template(
        'device_details.html',
        title=f"{device.get('name', 'Dispositivo')}",
        device=device,
        assigned_user=assigned_user,
        score=score,
        total_infractions=total_infractions,
        distance_today=distance_today,
        distance_week=distance_week,
        distance_month=distance_month,
        max_speed_today=max_speed_today,
        route=positions_today,
        infractions_today=infractions_today,
        infractions_week=infractions_week,
        infractions_month=infractions_month,
        visits_today=visits_today,
        visits_week=visits_week,
        visits_month=visits_month,
        current_date=formatted_date,
        stats_today=stats_today,
        stats_week=stats_week,
        stats_month=stats_month,
    )
