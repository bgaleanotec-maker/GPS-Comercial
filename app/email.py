# Ruta: SST/app/email.py
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from flask import current_app, render_template
from datetime import datetime
import pytz
# --- NUEVA IMPORTACIÓN ---
from app.models import Setting 

def send_infraction_alert(infraction, device_name):
    """
    Envía un correo electrónico de alerta de infracción.
    """
    api_key = current_app.config['SENDGRID_API_KEY']
    sender = current_app.config['MAIL_DEFAULT_SENDER']
    
    # --- LÓGICA ACTUALIZADA ---
    # Obtiene los destinatarios desde la base de datos en lugar del archivo de configuración
    sst_setting = Setting.query.filter_by(key='sst_recipients').first()
    recipients_str = sst_setting.value if sst_setting and sst_setting.value else ''
    
    if not recipients_str:
        print("ADVERTENCIA (Alerta Infracción): No hay correos configurados para alertas SST.")
        return

    recipients = [email.strip() for email in recipients_str.split(',') if email.strip()]

    if not api_key or not sender or not recipients:
        print("ADVERTENCIA (Alerta Infracción): Faltan las claves de SendGrid, el remitente o los destinatarios. No se enviará el correo.")
        return

    message = Mail(
        from_email=sender,
        to_emails=recipients,  # <-- Usa la lista de destinatarios
        subject=f'Alerta de Infracción de SST: {device_name}',
        html_content=f"""
            <h2>Alerta de Seguridad Vial</h2>
            <p>Se ha detectado una nueva infracción a las reglas de conducción segura.</p>
            <ul>
                <li><strong>Vehículo/Dispositivo:</strong> {device_name}</li>
                <li><strong>Hora de la Infracción:</strong> {infraction.timestamp.strftime('%Y-%m-%d %H:%M:%S')} (UTC)</li>
                <li><strong>Regla Incumplida:</strong> {infraction.rule.name}</li>
                <li><strong>Valor Registrado:</strong> <strong style="color:red;">{infraction.measured_value}</strong></li>
                <li><strong>Límite Permitido:</strong> {infraction.rule.value} { 'km/h' if infraction.rule.rule_type == 'max_speed' else '' }</li>
            </ul>
            <p>Por favor, revise la plataforma para más detalles.</p>
        """
    )
    try:
        sg = SendGridAPIClient(api_key)
        response = sg.send(message)
        print(f"Correo de alerta enviado. Código de estado: {response.status_code}")
    except Exception as e:
        print(f"Error al enviar correo de alerta con SendGrid: {e}")

def send_report_email(recipients, data):
    """
    Envía el correo electrónico del reporte diario.
    """
    api_key = current_app.config['SENDGRID_API_KEY']
    sender = current_app.config['MAIL_DEFAULT_SENDER']
    
    if not api_key or not sender or not recipients:
        print("ADVERTENCIA (Reporte Diario): Faltan las claves de SendGrid o los destinatarios. No se enviará el correo.")
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
        print(f"Correo de reporte enviado. Código de estado: {response.status_code}")
        return True
    except Exception as e:
        print(f"Error al enviar correo de reporte con SendGrid: {e}")
        return False
