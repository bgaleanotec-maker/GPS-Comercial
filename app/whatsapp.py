# Ruta: GPS_Comercial/app/whatsapp.py
"""Modulo de notificaciones WhatsApp via Ultramsg API."""

import logging
from datetime import datetime

import requests
import pytz

from app.models import Setting

logger = logging.getLogger(__name__)

ULTRAMSG_TIMEOUT = 15


def _get_ultramsg_config():
    """Obtiene configuracion de Ultramsg desde la tabla Setting."""
    settings = {s.key: s.value for s in Setting.query.all()}
    instance_id = settings.get('ultramsg_instance_id', '')
    token = settings.get('ultramsg_token', '')
    return instance_id, token


def send_whatsapp_message(phone_number, message):
    """
    Envia un mensaje de WhatsApp via Ultramsg API.
    phone_number: formato internacional sin '+' (ej: '573001234567')
    """
    instance_id, token = _get_ultramsg_config()
    if not instance_id or not token:
        logger.warning("Ultramsg no configurado. Configure instance_id y token en Configuracion.")
        return False

    url = f"https://api.ultramsg.com/{instance_id}/messages/chat"
    payload = {
        'token': token,
        'to': phone_number,
        'body': message,
    }

    try:
        response = requests.post(url, data=payload, timeout=ULTRAMSG_TIMEOUT)
        data = response.json()
        if data.get('sent') == 'true' or data.get('id'):
            logger.info("WhatsApp enviado a %s", phone_number)
            return True
        else:
            logger.error("Error Ultramsg: %s", data)
            return False
    except Exception as e:
        logger.error("Error enviando WhatsApp a %s: %s", phone_number, e)
        return False


def format_daily_summary(devices_data, visits_data):
    """Formatea un resumen diario para WhatsApp."""
    colombia_tz = pytz.timezone('America/Bogota')
    now = datetime.now(colombia_tz)

    lines = [
        f"*GPS Comercial - Resumen {now.strftime('%d/%m/%Y')}*",
        "",
    ]

    if devices_data:
        lines.append("*Flota:*")
        for d in devices_data[:10]:
            status_icon = '🟢' if d.get('status') == 'online' else '🔴'
            lines.append(
                f"{status_icon} {d.get('name', 'N/A')}: "
                f"{d.get('distance_today', 0):.1f} km"
            )
        lines.append("")

    if visits_data:
        total_visits = sum(v.get('visits_today', 0) for v in visits_data)
        lines.append(f"*Visitas hoy:* {total_visits}")
        for v in visits_data[:5]:
            if v.get('visits_today', 0) > 0:
                lines.append(f"  - {v.get('name')}: {v['visits_today']} visitas")

    return "\n".join(lines)


def format_leader_summary(leader_name, team_devices, team_visits):
    """Formatea resumen para un lider de negocio con su equipo."""
    colombia_tz = pytz.timezone('America/Bogota')
    now = datetime.now(colombia_tz)

    lines = [
        f"*Reporte Equipo - {leader_name}*",
        f"_{now.strftime('%d/%m/%Y %H:%M')}_",
        "",
    ]

    online_count = sum(1 for d in team_devices if d.get('status') == 'online')
    total = len(team_devices)
    lines.append(f"*Conectados:* {online_count}/{total}")
    lines.append("")

    for d in team_devices:
        status_icon = '🟢' if d.get('status') == 'online' else '🔴'
        walking = d.get('walking_km', 0)
        vehicle = d.get('vehicle_km', 0)
        lines.append(f"{status_icon} *{d.get('employee_name', d.get('name', 'N/A'))}*")
        lines.append(f"   🚗 {vehicle:.1f} km | 🚶 {walking:.1f} km")
        if d.get('visits_today', 0) > 0:
            lines.append(f"   📍 {d['visits_today']} visitas")
        lines.append("")

    return "\n".join(lines)


def send_leader_notifications(app):
    """
    Envia notificaciones WhatsApp a los lideres de negocio configurados.
    Cada lider recibe info solo de su mercado/equipo.
    """
    from app.models import User
    from app.traccar import get_devices_for_app
    from app import db

    with app.app_context():
        settings = {s.key: s.value for s in Setting.query.all()}
        if not settings.get('whatsapp_enabled', 'false') == 'true':
            return

        # Obtener dispositivos de Traccar
        devices = get_devices_for_app(app)
        if not devices:
            return

        device_map = {d['id']: d for d in devices}

        # Buscar lideres (role='lider')
        leaders = User.query.filter_by(role='lider').all()

        for leader in leaders:
            if not leader.phone_number:
                continue

            # Obtener empleados del mismo mercado/categoria
            team_members = User.query.filter(
                User.categoria == leader.categoria,
                User.role == 'empleado'
            ).all()

            team_devices = []
            for member in team_members:
                if member.traccar_device_id and member.traccar_device_id in device_map:
                    device_info = device_map[member.traccar_device_id].copy()
                    device_info['employee_name'] = member.full_name or member.username
                    team_devices.append(device_info)

            if team_devices:
                message = format_leader_summary(
                    leader.full_name or leader.username,
                    team_devices,
                    []
                )
                send_whatsapp_message(leader.phone_number, message)
