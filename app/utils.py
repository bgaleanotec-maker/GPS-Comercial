# Ruta: GPS_Comercial/app/utils.py
"""Utilidades compartidas: horario laboral, distancias, filtros de posiciones."""

import logging
from datetime import datetime, time as dt_time
from math import radians, sin, cos, sqrt, atan2

import pytz

from app import db
from app.models import Setting

logger = logging.getLogger(__name__)

# Zona horaria de Colombia
COLOMBIA_TZ = pytz.timezone('America/Bogota')


def is_working_hours(app=None):
    """
    Verifica si estamos en horario laboral segun la configuracion.
    Retorna True solo si es un dia laboral configurado y dentro del rango de horas.
    Respeta la privacidad de los empleados fuera de horario.

    Si se pasa `app`, usa su contexto. Si no, asume que ya hay un app context activo.
    """
    def _check():
        settings = {s.key: s.value for s in Setting.query.all()}

        active_days_str = settings.get('active_days', '1,2,3,4,5')
        start_time_str = settings.get('start_time', '06:00')
        end_time_str = settings.get('end_time', '20:00')

        now_colombia = datetime.now(COLOMBIA_TZ)

        # weekday(): 0=Lunes ... 6=Domingo. Nuestra convención: 1=Lunes ... 0=Domingo
        current_day = str(now_colombia.weekday() + 1)
        if current_day == '7':
            current_day = '0'

        active_days = active_days_str.split(',')

        if current_day not in active_days:
            logger.info("[PRIVACIDAD] Hoy no es dia laboral. No se registrara actividad.")
            return False

        try:
            start_hour, start_minute = map(int, start_time_str.split(':'))
            end_hour, end_minute = map(int, end_time_str.split(':'))

            start_time = dt_time(start_hour, start_minute)
            end_time = dt_time(end_hour, end_minute)
            current_time = now_colombia.time()

            if not (start_time <= current_time <= end_time):
                logger.info(
                    "[PRIVACIDAD] Fuera de horario laboral (%s - %s).",
                    start_time_str, end_time_str
                )
                return False
        except ValueError:
            logger.error("Formato de hora invalido en configuracion.")
            return False

        return True

    if app is not None:
        with app.app_context():
            return _check()
    return _check()


def haversine_distance(lat1, lon1, lat2, lon2):
    """Calcula la distancia en metros entre dos puntos geograficos."""
    R = 6371000  # Radio de la Tierra en metros
    lat1_rad, lon1_rad = radians(lat1), radians(lon1)
    lat2_rad, lon2_rad = radians(lat2), radians(lon2)
    dlon, dlat = lon2_rad - lon1_rad, lat2_rad - lat1_rad
    a = sin(dlat / 2) ** 2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c


def filter_positions_by_working_hours(positions):
    """
    Filtra una lista de posiciones GPS para incluir solo las que estan
    dentro del horario laboral configurado.
    """
    if not positions:
        return []

    settings = {s.key: s.value for s in Setting.query.all()}
    active_days_str = settings.get('active_days', '1,2,3,4,5')
    start_time_str = settings.get('start_time', '06:00')
    end_time_str = settings.get('end_time', '20:00')

    try:
        start_hour, start_minute = map(int, start_time_str.split(':'))
        end_hour, end_minute = map(int, end_time_str.split(':'))
        start_time = dt_time(start_hour, start_minute)
        end_time = dt_time(end_hour, end_minute)
    except ValueError:
        logger.error("Formato de hora invalido, retornando todas las posiciones.")
        return positions

    active_days = set(active_days_str.split(','))
    filtered = []

    for pos in positions:
        fix_time_str = pos.get('fixTime', '')
        if not fix_time_str:
            continue
        try:
            fix_time_utc = datetime.fromisoformat(fix_time_str.replace('Z', '+00:00'))
            fix_time_col = fix_time_utc.astimezone(COLOMBIA_TZ)

            day_str = str(fix_time_col.weekday() + 1)
            if day_str == '7':
                day_str = '0'

            if day_str in active_days and start_time <= fix_time_col.time() <= end_time:
                filtered.append(pos)
        except (ValueError, TypeError):
            continue

    return filtered
