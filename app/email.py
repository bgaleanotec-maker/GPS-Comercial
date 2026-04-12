# Ruta: GPS_Comercial/app/email.py
"""Servicio de envio de correos via SendGrid."""

import logging

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from flask import current_app, render_template
from datetime import datetime
import pytz

from app.models import Setting

logger = logging.getLogger(__name__)


def send_infraction_alert(infraction, device_name):
    """Envia un correo electronico de alerta de infraccion."""
    api_key = current_app.config.get('SENDGRID_API_KEY')
    sender = current_app.config.get('MAIL_DEFAULT_SENDER')

    sst_setting = Setting.query.filter_by(key='sst_recipients').first()
    recipients_str = sst_setting.value if sst_setting and sst_setting.value else ''

    if not recipients_str:
        logger.warning("No hay correos configurados para alertas SST.")
        return

    recipients = [email.strip() for email in recipients_str.split(',') if email.strip()]

    if not api_key or not sender or not recipients:
        logger.warning("Faltan claves de SendGrid, remitente o destinatarios. No se enviara alerta.")
        return

    message = Mail(
        from_email=sender,
        to_emails=recipients,
        subject=f'Alerta de Infraccion de SST: {device_name}',
        html_content=f"""
            <h2>Alerta de Seguridad Vial</h2>
            <p>Se ha detectado una nueva infraccion a las reglas de conduccion segura.</p>
            <ul>
                <li><strong>Vehiculo/Dispositivo:</strong> {device_name}</li>
                <li><strong>Hora:</strong> {infraction.timestamp.strftime('%Y-%m-%d %H:%M:%S')} (UTC)</li>
                <li><strong>Regla Incumplida:</strong> {infraction.rule.name}</li>
                <li><strong>Valor Registrado:</strong> <strong style="color:red;">{infraction.measured_value}</strong></li>
                <li><strong>Limite Permitido:</strong> {infraction.rule.value} {'km/h' if infraction.rule.rule_type == 'max_speed' else ''}</li>
            </ul>
            <p>Por favor, revise la plataforma para mas detalles.</p>
        """
    )
    try:
        sg = SendGridAPIClient(api_key)
        response = sg.send(message)
        logger.info("Correo de alerta enviado. Codigo: %s", response.status_code)
    except Exception as e:
        logger.error("Error al enviar correo de alerta: %s", e)


def send_report_email(recipients, data):
    """Envia el correo electronico del reporte diario."""
    api_key = current_app.config.get('SENDGRID_API_KEY')
    sender = current_app.config.get('MAIL_DEFAULT_SENDER')

    if not api_key or not sender or not recipients:
        logger.warning("Faltan claves de SendGrid o destinatarios. No se enviara reporte.")
        return False

    html_content = render_template('email/report_template.html', report_data=data)

    colombia_tz = pytz.timezone('America/Bogota')
    report_date = datetime.now(colombia_tz).strftime('%d de %B de %Y')

    message = Mail(
        from_email=sender,
        to_emails=recipients,
        subject=f'Reporte Diario de Movilidad - {report_date}',
        html_content=html_content
    )
    try:
        sg = SendGridAPIClient(api_key)
        response = sg.send(message)
        logger.info("Correo de reporte enviado. Codigo: %s", response.status_code)
        return True
    except Exception as e:
        logger.error("Error al enviar correo de reporte: %s", e)
        return False
