# Ruta: GPS_Comercial/app/scoring/engine.py
"""Motor de evaluacion de infracciones y conduccion segura."""

import logging
from datetime import datetime, time as dt_time, timedelta

import pytz

from app import db
from app.models import Rule, Infraction, User
from app.email import send_infraction_alert
from app.traccar import get_devices, get_device_positions, KNOTS_TO_KMH
from app.utils import is_working_hours

logger = logging.getLogger(__name__)


def evaluate_device(device):
    """
    Evalua infracciones SOLO si estamos en horario laboral.
    Protege la privacidad de los empleados.
    """
    if not is_working_hours():
        return

    device_id = device.get('id')
    device_name = device.get('name')
    logger.info("Evaluando (posiciones): %s (ID: %s)", device_name, device_id)

    active_rules = Rule.query.filter_by(is_active=True).all()
    if not active_rules:
        return

    colombia_tz = pytz.timezone('America/Bogota')
    now = datetime.now(colombia_tz)
    today_start = colombia_tz.localize(datetime.combine(now.date(), dt_time.min))

    positions_data = get_device_positions(device_id, today_start, now)

    if not positions_data:
        logger.debug("No se encontraron posiciones GPS para %s hoy.", device_name)
        return

    user = User.query.filter_by(traccar_device_id=device_id).first()
    new_infractions_found = []

    for point in positions_data:
        try:
            infraction_time = datetime.fromisoformat(point.get('fixTime', '').replace('Z', '+00:00'))
        except (ValueError, TypeError):
            continue

        attributes = point.get('attributes', {})
        for rule in active_rules:
            infraction_details = None

            if rule.rule_type == 'max_speed':
                speed_kmh = point.get('speed', 0) * KNOTS_TO_KMH
                if speed_kmh > rule.value:
                    infraction_details = {
                        'measured_value': f"{speed_kmh:.2f} km/h",
                        'log_message': f"INFRACCION: {device_name} - Exceso de velocidad ({speed_kmh:.2f} km/h)"
                    }
            elif rule.rule_type == 'harsh_acceleration' and attributes.get('alarm') == 'hardAcceleration':
                infraction_details = {
                    'measured_value': "Evento Detectado",
                    'log_message': f"INFRACCION: {device_name} - Aceleracion Brusca"
                }
            elif rule.rule_type == 'harsh_braking' and attributes.get('alarm') == 'hardBraking':
                infraction_details = {
                    'measured_value': "Evento Detectado",
                    'log_message': f"INFRACCION: {device_name} - Frenada Brusca"
                }

            if infraction_details:
                existing = Infraction.query.filter_by(
                    device_id=device_id, rule_id=rule.id, timestamp=infraction_time
                ).first()
                if not existing:
                    new_infraction = Infraction(
                        device_id=device_id,
                        user_id=user.id if user else None,
                        rule_id=rule.id,
                        measured_value=infraction_details['measured_value'],
                        timestamp=infraction_time
                    )
                    db.session.add(new_infraction)
                    new_infractions_found.append(new_infraction)
                    logger.info(infraction_details['log_message'])

    if new_infractions_found:
        try:
            db.session.commit()
            logger.info("Enviando %d alerta(s)...", len(new_infractions_found))
            for infraction in new_infractions_found:
                db.session.refresh(infraction)
                send_infraction_alert(infraction, device_name)
        except Exception as e:
            db.session.rollback()
            logger.error("Error al guardar infracciones: %s", e)


def run_periodic_evaluation():
    """Ejecuta la evaluacion periodica respetando horario laboral."""
    logger.info("--- EJECUTANDO EVALUACION PERIODICA ---")
    if not is_working_hours():
        logger.info("[PRIVACIDAD] Evaluacion saltada - Fuera de horario laboral.")
        return

    devices = get_devices()
    if devices:
        for device in devices:
            evaluate_device(device)
    logger.info("--- EVALUACION FINALIZADA ---")


def calculate_driving_score(device_id, days=30):
    """Calcula el puntaje de conduccion segura (0-100)."""
    now = datetime.now(pytz.timezone('America/Bogota'))
    period_start = now - timedelta(days=days)
    infractions = Infraction.query.filter(
        Infraction.device_id == device_id,
        Infraction.timestamp >= period_start
    ).all()
    total_penalty_points = sum(infraction.rule.points for infraction in infractions)
    score = max(0, 100 - total_penalty_points)
    return score, len(infractions)
