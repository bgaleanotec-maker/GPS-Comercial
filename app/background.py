# Ruta: GPS_Comercial/app/background.py
"""Worker de fondo para deteccion automatica de visitas y envio de reportes."""

import logging
from threading import Thread
from datetime import datetime, timedelta
import time

import pytz

from app import db
from app.models import User, Ally, Visit, Setting
from app.email import send_infraction_alert, send_report_email
from app.reporting_logic import generate_report_data
from app.utils import is_working_hours, haversine_distance, is_user_trackable
from app.traccar import get_devices_for_app, get_latest_position_for_app

logger = logging.getLogger(__name__)

# Variable para rastrear el ultimo dia que se envio el reporte
_last_report_sent_day = None


def check_for_visits(app, device, all_allies):
    """Comprueba si la ultima posicion de un dispositivo esta dentro del radio de algun aliado."""
    device_id = device.get('id')
    device_name = device.get('name')

    last_pos = get_latest_position_for_app(app, device_id)
    if not last_pos:
        return

    now_utc = datetime.now(pytz.utc)
    try:
        fix_time_utc = datetime.fromisoformat(last_pos['fixTime'].replace('Z', '+00:00'))
    except (ValueError, KeyError):
        logger.warning("No se pudo parsear fixTime para dispositivo %s", device_name)
        return

    age_seconds = (now_utc - fix_time_utc).total_seconds()

    # Solo posiciones de las ultimas 24 horas
    if age_seconds > 86400:
        return

    for ally in all_allies:
        distance = haversine_distance(
            last_pos['latitude'], last_pos['longitude'],
            ally.latitude, ally.longitude
        )

        if distance <= ally.radius:
            settings = {s.key: s.value for s in Setting.query.all()}
            visit_interval_minutes = int(settings.get('visit_interval', 60))

            last_visit = Visit.query.filter_by(
                device_id=device_id, ally_id=ally.id
            ).order_by(Visit.timestamp.desc()).first()

            if last_visit:
                last_ts = last_visit.timestamp.replace(tzinfo=pytz.utc) if last_visit.timestamp.tzinfo is None else last_visit.timestamp
                if (fix_time_utc - last_ts) < timedelta(minutes=visit_interval_minutes):
                    continue

            user = User.query.filter_by(traccar_device_id=device_id).first()
            # Verificar estado del usuario (vacaciones, incapacidad, etc.)
            if not is_user_trackable(user):
                logger.info("Usuario %s no trackeable (estado: %s). Saltando.",
                           user.username if user else 'N/A',
                           user.employee_status if user else 'N/A')
                return

            logger.info(
                "NUEVA VISITA AUTOMATICA: Dispositivo %s -> Aliado %s (%.0fm)",
                device_name, ally.name, distance
            )
            new_visit = Visit(
                timestamp=fix_time_utc,
                device_id=device_id,
                user_id=user.id if user else None,
                ally_id=ally.id,
                is_manual=False
            )
            try:
                db.session.add(new_visit)
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                logger.error("Error al registrar visita automatica: %s", e)
            break  # Solo una visita por evaluacion


def run_periodic_evaluation(app):
    """Evalua visitas automaticas. Solo en horario laboral."""
    if not is_working_hours(app):
        return

    logger.info("--- EJECUTANDO EVALUACION: %s ---", datetime.now())
    devices = get_devices_for_app(app)
    if devices:
        with app.app_context():
            all_allies = Ally.query.all()
            if not all_allies:
                logger.debug("No hay aliados configurados.")
                return
            for device in devices:
                check_for_visits(app, device, all_allies)
    logger.info("--- EVALUACION FINALIZADA ---")


def check_and_send_report(app):
    """Verifica si es hora de enviar el reporte diario."""
    global _last_report_sent_day
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
            logger.error("Formato de hora de reporte invalido.")
            return

        if (now_colombia.hour == report_hour and
                now_colombia.minute == report_minute and
                now_colombia.date() != _last_report_sent_day):

            logger.info("--- ENVIANDO REPORTE DIARIO AUTOMATICO ---")
            recipients = [e.strip() for e in report_recipients_str.split(',') if e.strip()]
            report_data = generate_report_data()
            send_report_email(recipients, report_data)
            _last_report_sent_day = now_colombia.date()
            logger.info("--- REPORTE DIARIO ENVIADO ---")


def check_and_send_whatsapp(app):
    """Verifica si es hora de enviar notificaciones WhatsApp a lideres."""
    global _last_whatsapp_sent_day
    with app.app_context():
        settings = {s.key: s.value for s in Setting.query.all()}
        if settings.get('whatsapp_enabled', 'false') != 'true':
            return

        whatsapp_time_str = settings.get('whatsapp_report_time', '')
        if not whatsapp_time_str:
            return

        colombia_tz = pytz.timezone('America/Bogota')
        now_colombia = datetime.now(colombia_tz)

        try:
            wh_hour, wh_minute = map(int, whatsapp_time_str.split(':'))
        except ValueError:
            return

        if (now_colombia.hour == wh_hour and
                now_colombia.minute == wh_minute and
                now_colombia.date() != _last_whatsapp_sent_day):
            logger.info("--- ENVIANDO NOTIFICACIONES WHATSAPP ---")
            try:
                from app.whatsapp import send_leader_notifications
                send_leader_notifications(app)
                _last_whatsapp_sent_day = now_colombia.date()
                logger.info("--- NOTIFICACIONES WHATSAPP ENVIADAS ---")
            except Exception as e:
                logger.error("Error enviando WhatsApp: %s", e)


# Variables de tracking de envios
_last_whatsapp_sent_day = None


def _background_loop(app):
    """Funcion principal del hilo de fondo."""
    logger.info("Hilo de fondo iniciado. Evaluacion cada 60 segundos.")
    logger.info("MODO PRIVACIDAD ACTIVADO: Solo monitorea en horario laboral.")
    while True:
        try:
            with app.app_context():
                run_periodic_evaluation(app)
                check_and_send_report(app)
                check_and_send_whatsapp(app)
                # Validar tareas del cronograma con GPS
                try:
                    from app.schedule.validator import validate_pending_tasks, mark_overdue_tasks
                    validate_pending_tasks()
                    mark_overdue_tasks()
                except Exception as ve:
                    logger.debug("Validacion de tareas: %s", ve)
        except Exception as e:
            logger.error("Error en el hilo de fondo: %s", e)
        time.sleep(60)


def start_background_worker(app):
    """Inicia el hilo de fondo como daemon thread."""
    thread = Thread(target=_background_loop, args=(app,), daemon=True)
    thread.start()
    logger.info("Background worker iniciado correctamente.")
