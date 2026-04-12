# Ruta: GPS_Comercial/app/schedule/validator.py
"""Validador automatico de tareas basado en datos GPS de Traccar."""
import logging
from datetime import datetime, time as dt_time, timedelta

import pytz

from app import db
from app.models import ScheduledTask, User, Ally, Setting
from app.traccar import get_device_positions
from app.utils import haversine_distance

logger = logging.getLogger(__name__)
COLOMBIA_TZ = pytz.timezone('America/Bogota')


def validate_pending_tasks():
    """
    Valida tareas pendientes de hoy comparando posiciones GPS con ubicacion del aliado.
    Si el empleado estuvo dentro del radio del aliado por el tiempo minimo, marca como cumplida.
    Retorna el numero de tareas validadas.
    """
    now = datetime.now(COLOMBIA_TZ)
    today = now.date()
    validated_count = 0

    # Buscar tareas pendientes de hoy que tengan aliado asignado
    pending_tasks = ScheduledTask.query.filter(
        ScheduledTask.scheduled_date == today,
        ScheduledTask.status.in_(['pendiente', 'en_progreso']),
        ScheduledTask.ally_id.isnot(None),
    ).all()

    if not pending_tasks:
        return 0

    # Agrupar tareas por usuario para minimizar consultas a Traccar
    tasks_by_user = {}
    for task in pending_tasks:
        if task.user_id not in tasks_by_user:
            tasks_by_user[task.user_id] = []
        tasks_by_user[task.user_id].append(task)

    today_start = COLOMBIA_TZ.localize(datetime.combine(today, dt_time.min))

    for user_id, user_tasks in tasks_by_user.items():
        user = User.query.get(user_id)
        if not user or not user.traccar_device_id:
            continue

        # Obtener posiciones del dia
        positions = get_device_positions(user.traccar_device_id, today_start, now)
        if not positions:
            continue

        for task in user_tasks:
            ally = Ally.query.get(task.ally_id)
            if not ally:
                continue

            # Calcular tiempo dentro del radio del aliado
            time_in_radius = _calculate_time_in_radius(
                positions, ally.latitude, ally.longitude, ally.radius
            )

            min_required = task.min_time_on_site or 30  # default 30 min

            if time_in_radius >= min_required:
                task.status = 'cumplida'
                task.auto_validated = True
                task.validated_at = datetime.now(pytz.utc)
                task.time_on_site_minutes = time_in_radius
                task.completed_at = datetime.now(pytz.utc)
                validated_count += 1
                logger.info(
                    "Tarea #%d auto-validada: %s estuvo %.0f min en %s (min: %d)",
                    task.id, user.username, time_in_radius, ally.name, min_required
                )
            elif time_in_radius > 0:
                # Estuvo ahi pero no suficiente tiempo
                task.status = 'en_progreso'
                task.time_on_site_minutes = time_in_radius

    if validated_count > 0:
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error("Error al validar tareas: %s", e)
            return 0

    return validated_count


def _calculate_time_in_radius(positions, target_lat, target_lon, radius_meters):
    """
    Calcula el tiempo total (en minutos) que el dispositivo estuvo dentro
    del radio de un punto objetivo, basado en la lista de posiciones GPS.
    """
    if not positions or len(positions) < 2:
        return 0

    total_minutes = 0.0

    for i in range(len(positions) - 1):
        pos = positions[i]
        next_pos = positions[i + 1]

        dist = haversine_distance(
            pos.get('latitude', 0), pos.get('longitude', 0),
            target_lat, target_lon
        )

        if dist <= radius_meters:
            # Calcular duracion entre este punto y el siguiente
            try:
                t1 = datetime.fromisoformat(pos['fixTime'].replace('Z', '+00:00'))
                t2 = datetime.fromisoformat(next_pos['fixTime'].replace('Z', '+00:00'))
                delta = (t2 - t1).total_seconds() / 60.0
                # Maximo 30 min entre puntos (evitar gaps largos)
                if 0 < delta < 30:
                    total_minutes += delta
            except (ValueError, KeyError):
                continue

    return total_minutes


def mark_overdue_tasks():
    """Marca tareas vencidas como no_cumplida al final del dia."""
    today = datetime.now(COLOMBIA_TZ).date()
    overdue = ScheduledTask.query.filter(
        ScheduledTask.scheduled_date < today,
        ScheduledTask.status.in_(['pendiente', 'en_progreso']),
    ).all()

    for task in overdue:
        task.status = 'no_cumplida'

    if overdue:
        try:
            db.session.commit()
            logger.info("Marcadas %d tareas como no_cumplida", len(overdue))
        except Exception as e:
            db.session.rollback()
            logger.error("Error marcando tareas vencidas: %s", e)
