# Ruta: GPS_Comercial/app/whatsapp.py
"""Modulo de notificaciones WhatsApp via Ultramsg API."""

import logging
import os
from datetime import datetime

import requests
import pytz

from app.models import Setting

logger = logging.getLogger(__name__)

ULTRAMSG_TIMEOUT = 15


def _get_ultramsg_config():
    """Obtiene configuracion de Ultramsg desde la tabla Setting, con fallback a env vars."""
    try:
        settings = {s.key: s.value for s in Setting.query.all()}
        instance_id = settings.get('ultramsg_instance_id', '')
        token = settings.get('ultramsg_token', '')
    except Exception:
        instance_id = ''
        token = ''

    # Fallback a variables de entorno si la BD no tiene valores
    if not instance_id:
        instance_id = os.environ.get('ULTRAMSG_INSTANCE_ID', '')
    if not token:
        token = os.environ.get('ULTRAMSG_TOKEN', '')

    return instance_id, token


def _normalize_phone(phone_number):
    """Normaliza numero de telefono al formato requerido por Ultramsg (+573...)."""
    phone = phone_number.strip().replace(' ', '').replace('-', '')
    # Quitar + si existe
    if phone.startswith('+'):
        phone = phone[1:]
    # Si empieza con 3 y tiene 10 digitos, agregar 57 (Colombia)
    if phone.startswith('3') and len(phone) == 10:
        phone = '57' + phone
    # Ultramsg espera formato +57...
    return '+' + phone


def send_whatsapp_message(phone_number, message):
    """
    Envia un mensaje de WhatsApp via Ultramsg API.
    phone_number: cualquier formato colombiano (3222699322, 573222699322, +573222699322)
    """
    instance_id, token = _get_ultramsg_config()
    if not instance_id or not token:
        logger.warning("Ultramsg no configurado. instance_id=%s, token=%s",
                       'SET' if instance_id else 'EMPTY', 'SET' if token else 'EMPTY')
        return False

    normalized = _normalize_phone(phone_number)
    url = f"https://api.ultramsg.com/{instance_id}/messages/chat"
    payload = {
        'token': token,
        'to': normalized,
        'body': message,
    }

    try:
        logger.info("Enviando WhatsApp a %s via Ultramsg instance %s...", normalized, instance_id)
        response = requests.post(url, data=payload, timeout=ULTRAMSG_TIMEOUT)
        data = response.json()
        logger.info("Respuesta Ultramsg: %s", data)
        if data.get('sent') == 'true' or data.get('id'):
            logger.info("WhatsApp enviado exitosamente a %s", normalized)
            return True
        else:
            logger.error("Error Ultramsg: %s", data)
            return False
    except Exception as e:
        logger.error("Error enviando WhatsApp a %s: %s", normalized, e)
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


def format_task_overdue_message(user_name, task_title, scheduled_date, task_type):
    """Formato de mensaje WhatsApp para tarea vencida."""
    return (
        f"⏰ *Tarea Vencida*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👤 *{user_name}*\n"
        f"📋 {task_title}\n"
        f"📅 Fecha: {scheduled_date}\n"
        f"🏷️ Tipo: {task_type}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"_Esta tarea no fue completada a tiempo._\n"
        f"_GPS Comercial - Sistema Automatico_"
    )


def format_leader_daily_task_summary(leader_name, date_str, employee_tasks):
    """
    Formato de resumen diario de tareas para el lider.
    employee_tasks: lista de dicts {name, total, cumplidas, vencidas, pendientes}
    """
    lines = [
        f"📊 *Resumen Diario de Tareas*",
        f"━━━━━━━━━━━━━━━━━━━",
        f"👔 *Gerente:* {leader_name}",
        f"📅 *Fecha:* {date_str}",
        f"━━━━━━━━━━━━━━━━━━━",
        "",
    ]

    total_all = 0
    cumplidas_all = 0
    vencidas_all = 0

    for emp in employee_tasks:
        total_all += emp['total']
        cumplidas_all += emp['cumplidas']
        vencidas_all += emp['vencidas']

        if emp['total'] == 0:
            continue

        pct = (emp['cumplidas'] / emp['total'] * 100) if emp['total'] > 0 else 0
        status_icon = '✅' if pct >= 80 else ('⚠️' if pct >= 50 else '🔴')

        lines.append(f"{status_icon} *{emp['name']}*")
        lines.append(f"   ✅ {emp['cumplidas']}/{emp['total']} tareas ({pct:.0f}%)")
        if emp['vencidas'] > 0:
            lines.append(f"   🔴 {emp['vencidas']} vencida(s)")
        if emp.get('pending_titles'):
            for t in emp['pending_titles'][:3]:
                lines.append(f"   ⏳ _{t}_")
        lines.append("")

    # Resumen global
    pct_global = (cumplidas_all / total_all * 100) if total_all > 0 else 0
    lines.extend([
        f"━━━━━━━━━━━━━━━━━━━",
        f"📈 *Cumplimiento Global:* {pct_global:.0f}%",
        f"✅ Cumplidas: {cumplidas_all} | 🔴 Vencidas: {vencidas_all}",
        f"📋 Total: {total_all}",
        f"━━━━━━━━━━━━━━━━━━━",
        f"_GPS Comercial - Reporte Automatico_",
    ])

    return "\n".join(lines)


def send_task_overdue_alerts(app):
    """
    Envia alertas WhatsApp cuando tareas pasan de la hora programada sin completarse.
    Se ejecuta desde el background worker.
    """
    from app.models import User, ScheduledTask, TaskTemplate
    from app import db

    with app.app_context():
        settings = {s.key: s.value for s in Setting.query.all()}
        if settings.get('whatsapp_enabled', 'false') != 'true':
            return 0

        colombia_tz = pytz.timezone('America/Bogota')
        now = datetime.now(colombia_tz)
        today = now.date()

        # Buscar tareas pendientes de hoy que tengan template con hora programada
        overdue_tasks = ScheduledTask.query.filter(
            ScheduledTask.scheduled_date == today,
            ScheduledTask.status == 'pendiente',
        ).all()

        sent_count = 0
        for task in overdue_tasks:
            # Si la tarea tiene template con hora programada, verificar si paso la hora
            if task.template_id and task.template:
                sched_time = getattr(task.template, 'scheduled_time', None)
                if sched_time:
                    try:
                        hour, minute = map(int, sched_time.split(':'))
                        if now.hour > hour or (now.hour == hour and now.minute > minute + 30):
                            # La tarea lleva 30+ min de retraso
                            user = task.user
                            if user and user.phone_number:
                                msg = format_task_overdue_message(
                                    user.full_name or user.username,
                                    task.title,
                                    task.scheduled_date.strftime('%d/%m/%Y'),
                                    task.task_type
                                )
                                if send_whatsapp_message(user.phone_number, msg):
                                    sent_count += 1
                    except (ValueError, AttributeError):
                        pass

        return sent_count


def send_leader_daily_task_summary(app):
    """
    Envia resumen diario de tareas al lider/gerente de cada negocio.
    Se ejecuta al final del dia desde el background worker.
    """
    from app.models import User, ScheduledTask
    from app import db

    with app.app_context():
        settings = {s.key: s.value for s in Setting.query.all()}
        if settings.get('whatsapp_enabled', 'false') != 'true':
            return 0

        colombia_tz = pytz.timezone('America/Bogota')
        now = datetime.now(colombia_tz)
        today = now.date()
        date_str = today.strftime('%d/%m/%Y')

        leaders = User.query.filter_by(role='lider').all()
        sent_count = 0

        for leader in leaders:
            if not leader.phone_number:
                continue

            # Obtener equipo del lider
            team = User.query.filter_by(
                categoria=leader.categoria,
                employee_status='activo'
            ).all()

            employee_tasks = []
            for member in team:
                tasks = ScheduledTask.query.filter_by(
                    user_id=member.id,
                    scheduled_date=today,
                ).all()

                total = len(tasks)
                cumplidas = sum(1 for t in tasks if t.status == 'cumplida')
                vencidas = sum(1 for t in tasks if t.is_overdue)
                pending_titles = [t.title for t in tasks if t.status == 'pendiente']

                employee_tasks.append({
                    'name': member.full_name or member.username,
                    'total': total,
                    'cumplidas': cumplidas,
                    'vencidas': vencidas,
                    'pendientes': total - cumplidas,
                    'pending_titles': pending_titles,
                })

            # Solo enviar si hay tareas
            if any(e['total'] > 0 for e in employee_tasks):
                msg = format_leader_daily_task_summary(
                    leader.full_name or leader.username,
                    date_str,
                    employee_tasks
                )
                if send_whatsapp_message(leader.phone_number, msg):
                    sent_count += 1

        return sent_count


def send_manual_whatsapp_test(phone_number, message_type='summary'):
    """
    Envia un mensaje WhatsApp manual de prueba. Usado por el admin.
    message_type: 'summary' | 'overdue' | 'custom'
    """
    from app.models import User, ScheduledTask

    colombia_tz = pytz.timezone('America/Bogota')
    now = datetime.now(colombia_tz)
    today = now.date()

    if message_type == 'summary':
        # Generar un resumen de ejemplo con datos reales
        leaders = User.query.filter_by(role='lider').all()
        if leaders:
            leader = leaders[0]
            team = User.query.filter_by(
                categoria=leader.categoria,
                employee_status='activo'
            ).all()
            employee_tasks = []
            for member in team:
                tasks = ScheduledTask.query.filter_by(
                    user_id=member.id,
                    scheduled_date=today,
                ).all()
                employee_tasks.append({
                    'name': member.full_name or member.username,
                    'total': len(tasks),
                    'cumplidas': sum(1 for t in tasks if t.status == 'cumplida'),
                    'vencidas': sum(1 for t in tasks if t.is_overdue),
                    'pending_titles': [t.title for t in tasks if t.status == 'pendiente'][:3],
                })
            msg = format_leader_daily_task_summary(
                leader.full_name or leader.username,
                today.strftime('%d/%m/%Y'),
                employee_tasks
            )
        else:
            msg = (
                f"📊 *Resumen Diario de Prueba*\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"📅 {today.strftime('%d/%m/%Y')}\n"
                f"✅ 5/8 tareas cumplidas (62%)\n"
                f"🔴 2 vencidas\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"_GPS Comercial - Mensaje de Prueba_"
            )
    elif message_type == 'overdue':
        msg = format_task_overdue_message(
            'Empleado de Prueba',
            'Visita comercial aliado principal',
            today.strftime('%d/%m/%Y'),
            'visita'
        )
    else:
        msg = (
            f"🔔 *GPS Comercial*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"Mensaje de prueba enviado.\n"
            f"WhatsApp configurado correctamente.\n"
            f"_{now.strftime('%d/%m/%Y %H:%M')}_"
        )

    return send_whatsapp_message(phone_number, msg)


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
