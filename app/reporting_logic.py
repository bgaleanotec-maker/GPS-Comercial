# Ruta: GPS_Comercial/app/reporting_logic.py
"""Logica de generacion de reportes diarios."""

import logging
from datetime import datetime, time, timedelta

import pytz

from app.models import Ally, Visit, Setting
from app.traccar import get_devices, get_device_positions, calculate_route_distances
from app.utils import filter_positions_by_working_hours, haversine_distance
from app.email import send_report_email

logger = logging.getLogger(__name__)


def _get_filtered_positions(device_id, from_time, to_time):
    """Obtiene posiciones filtradas por horario laboral."""
    positions = get_device_positions(device_id, from_time, to_time)
    if positions is None:
        return []
    return filter_positions_by_working_hours(positions)


def _calculate_distance(positions):
    """Calcula distancia total en metros desde una lista de posiciones."""
    if not positions or len(positions) < 2:
        return 0
    total = 0
    for i in range(len(positions) - 1):
        p1, p2 = positions[i], positions[i + 1]
        total += haversine_distance(
            p1['latitude'], p1['longitude'],
            p2['latitude'], p2['longitude']
        )
    return total


def generate_report_data():
    """
    Recopila y estructura todos los datos para el reporte diario.
    Solo cuenta kilometros de horario laboral.
    """
    colombia_tz = pytz.timezone('America/Bogota')
    now = datetime.now(colombia_tz)

    # --- 1. Datos de Dispositivos ---
    devices_data = []
    devices = get_devices()
    if devices:
        today_start = colombia_tz.localize(datetime.combine(now.date(), time.min))
        month_start = today_start.replace(day=1)

        for device in devices:
            positions_today = _get_filtered_positions(device['id'], today_start, now)
            positions_month = _get_filtered_positions(device['id'], month_start, now)

            distance_today_km = _calculate_distance(positions_today) / 1000
            distance_month_km = _calculate_distance(positions_month) / 1000

            # Desglose por modo de transporte
            route_stats = None
            if positions_today and len(positions_today) >= 2:
                route_stats = calculate_route_distances(positions_today)

            devices_data.append({
                'name': device.get('name', 'N/A'),
                'status': device.get('status', 'unknown'),
                'distance_today': distance_today_km,
                'distance_month': distance_month_km,
                'walking_km': route_stats['walking_km'] if route_stats else 0,
                'vehicle_km': route_stats['vehicle_km'] if route_stats else 0,
            })

    # --- 2. Datos de Visitas a Aliados ---
    allies_data = []
    allies = Ally.query.all()
    today_start_utc = colombia_tz.localize(
        datetime.combine(now.date(), time.min)
    ).astimezone(pytz.utc)
    week_start_utc = today_start_utc - timedelta(days=now.weekday())
    year_start_utc = today_start_utc.replace(month=1, day=1)

    for ally in allies:
        visits_today = Visit.query.filter(
            Visit.ally_id == ally.id,
            Visit.timestamp >= today_start_utc
        ).count()
        visits_week = Visit.query.filter(
            Visit.ally_id == ally.id,
            Visit.timestamp >= week_start_utc
        ).count()
        visits_year = Visit.query.filter(
            Visit.ally_id == ally.id,
            Visit.timestamp >= year_start_utc
        ).count()

        allies_data.append({
            'name': ally.name,
            'visits_today': visits_today,
            'visits_week': visits_week,
            'visits_year': visits_year,
        })

    return {
        'date': now.strftime('%d de %B de %Y'),
        'devices': devices_data,
        'allies': allies_data,
    }


def generate_and_send_daily_report():
    """Genera los datos y envia el correo del reporte."""
    logger.info("Iniciando generacion de datos del reporte...")
    report_data = generate_report_data()

    report_recipients_str = Setting.query.filter_by(key='report_recipients').first()
    if report_recipients_str and report_recipients_str.value:
        recipients = [e.strip() for e in report_recipients_str.value.split(',') if e.strip()]
        logger.info("Enviando reporte a: %s", recipients)
        send_report_email(recipients, report_data)
        return True
    else:
        logger.warning("No hay destinatarios configurados para el reporte diario.")
        return False
