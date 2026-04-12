# Ruta: GPS_Comercial/app/main/routes.py
import logging

from flask import render_template, abort, flash
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
    if current_user.role == 'admin':
        devices = get_devices()
        if devices:
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
            flash('No se pudo conectar a Traccar para obtener la lista de dispositivos.', 'danger')
        return render_template('admin_dashboard.html', title='Dashboard Admin', devices=devices)

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
    if current_user.role != 'admin' and current_user.traccar_device_id != device_id:
        abort(403)

    device = get_device_by_id(device_id)
    if not device:
        abort(404)

    score, total_infractions = calculate_driving_score_view(device_id)
    colombia_tz = pytz.timezone('America/Bogota')
    now = datetime.now(colombia_tz)
    today_start = colombia_tz.localize(datetime.combine(now.date(), time.min))

    positions_today = get_device_positions_view(device_id, today_start, now)
    distance_today = calculate_distance_from_points(positions_today) / 1000

    max_speed_today = 0
    route_stats = None
    if positions_today:
        max_speed_today = max(p.get('speed', 0) for p in positions_today) * KNOTS_TO_KMH
        if len(positions_today) >= 2:
            route_stats = calculate_route_distances(positions_today)

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
        current_date=formatted_date,
        route_stats=route_stats,
    )
