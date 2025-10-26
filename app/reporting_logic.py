# Ruta: SST/app/reporting_logic.py
from datetime import datetime, time, timedelta
import pytz
from app.models import Ally, Visit, Setting
from app.main.routes import get_devices_view, calculate_distance_from_points, get_device_positions_view
from app.email import send_report_email

def generate_report_data():
    """
    Recopila y estructura todos los datos necesarios para el reporte diario.
    🔒 Solo cuenta kilómetros de horario laboral (para bonos/auxilios).
    """
    colombia_tz = pytz.timezone('America/Bogota')
    now = datetime.now(colombia_tz)
    
    # --- 1. Datos de Dispositivos (FILTRADOS POR HORARIO LABORAL) ---
    devices_data = []
    devices = get_devices_view()
    if devices:
        today_start = colombia_tz.localize(datetime.combine(now.date(), time.min))
        month_start = today_start.replace(day=1)
        
        for device in devices:
            # 🔒 get_device_positions_view YA filtra por horario laboral
            positions_today = get_device_positions_view(device['id'], today_start, now)
            positions_month = get_device_positions_view(device['id'], month_start, now)
            
            distance_today_km = calculate_distance_from_points(positions_today) / 1000
            distance_month_km = calculate_distance_from_points(positions_month) / 1000

            devices_data.append({
                'name': device.get('name', 'N/A'),
                'status': device.get('status', 'unknown'),
                'distance_today': distance_today_km,
                'distance_month': distance_month_km,
            })

    # --- 2. Datos de Visitas a Aliados ---
    allies_data = []
    allies = Ally.query.all()
    today_start_utc = colombia_tz.localize(datetime.combine(now.date(), time.min)).astimezone(pytz.utc)
    week_start_utc = (today_start_utc - timedelta(days=now.weekday()))
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
    """
    Función principal que genera los datos y envía el correo del reporte.
    """
    print("[Reporte] Iniciando generación de datos...")
    report_data = generate_report_data()
    
    # Obtener la lista de correos desde la configuración
    report_recipients_str = Setting.query.filter_by(key='report_recipients').first()
    if report_recipients_str and report_recipients_str.value:
        recipients = [email.strip() for email in report_recipients_str.value.split(',')]
        print(f"[Reporte] Enviando reporte a: {recipients}")
        send_report_email(recipients, report_data)
        return True
    else:
        print("[Reporte] ADVERTENCIA: No hay destinatarios configurados para el reporte diario.")
        return False