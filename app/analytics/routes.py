# Ruta: SST/app/analytics/routes.py
from flask import render_template, request, flash, redirect, url_for, jsonify, send_file
from app.analytics import bp
from flask_login import login_required, current_user
from app.models import User, Ally, Visit, Infraction
from app import db
from datetime import datetime, time, timedelta
import pytz
from io import BytesIO
from werkzeug.utils import secure_filename
import os
from flask import current_app
from sqlalchemy import func
from collections import defaultdict

# Importar funciones de cálculo de distancias
from app.main.routes import get_devices_view, get_device_positions_view, calculate_distance_from_points

@bp.route('/dashboard')
@login_required
def analytics_dashboard():
    """
    Dashboard principal de analítica con filtros interactivos
    """
    colombia_tz = pytz.timezone('America/Bogota')
    now = datetime.now(colombia_tz)
    
    # Obtener parámetros de filtro
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    employee_id = request.args.get('employee_id', type=int)
    ally_id = request.args.get('ally_id', type=int)
    
    # Fechas por defecto: último mes
    if start_date_str:
        start_date = colombia_tz.localize(datetime.strptime(start_date_str, '%Y-%m-%d'))
    else:
        start_date = colombia_tz.localize(datetime.combine((now - timedelta(days=30)).date(), time.min))
    
    if end_date_str:
        end_date = colombia_tz.localize(datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59))
    else:
        end_date = now
    
    # Convertir a UTC para consultas
    start_date_utc = start_date.astimezone(pytz.utc)
    end_date_utc = end_date.astimezone(pytz.utc)
    
    # Obtener todos los usuarios y aliados para filtros
    all_users = User.query.filter_by(role='empleado').order_by(User.username).all()
    all_allies = Ally.query.order_by(Ally.name).all()
    
    # --- ANÁLISIS POR EMPLEADO ---
    employees_data = []
    devices = get_devices_view()
    
    if devices:
        for user in all_users:
            # Filtrar si se seleccionó un empleado específico
            if employee_id and user.id != employee_id:
                continue
                
            if not user.traccar_device_id:
                continue
            
            device = next((d for d in devices if d['id'] == user.traccar_device_id), None)
            if not device:
                continue
            
            # Calcular distancias
            positions_period = get_device_positions_view(user.traccar_device_id, start_date, end_date)
            distance_period_meters = calculate_distance_from_points(positions_period)
            
            today_start = colombia_tz.localize(datetime.combine(now.date(), time.min))
            positions_today = get_device_positions_view(user.traccar_device_id, today_start, now)
            distance_today_meters = calculate_distance_from_points(positions_today)
            
            month_start = today_start.replace(day=1)
            positions_month = get_device_positions_view(user.traccar_device_id, month_start, now)
            distance_month_meters = calculate_distance_from_points(positions_month)
            
            total_start = colombia_tz.localize(datetime(2000, 1, 1))
            positions_total = get_device_positions_view(user.traccar_device_id, total_start, now)
            distance_total_meters = calculate_distance_from_points(positions_total)
            
            # Contar visitas
            visits_period = Visit.query.filter(
                Visit.user_id == user.id,
                Visit.timestamp >= start_date_utc,
                Visit.timestamp <= end_date_utc
            ).count()
            
            # Contar infracciones
            infractions_period = Infraction.query.filter(
                Infraction.user_id == user.id,
                Infraction.timestamp >= start_date_utc,
                Infraction.timestamp <= end_date_utc
            ).count()
            
            employees_data.append({
                'id': user.id,
                'username': user.username,
                'full_name': user.full_name or user.username,
                'device_name': device.get('name'),
                'distance_today_km': distance_today_meters / 1000,
                'distance_month_km': distance_month_meters / 1000,
                'distance_total_km': distance_total_meters / 1000,
                'distance_period_km': distance_period_meters / 1000,
                'visits_period': visits_period,
                'infractions_period': infractions_period
            })
    
    # --- ANÁLISIS POR ALIADO ---
    allies_data = []
    
    for ally in all_allies:
        # Filtrar si se seleccionó un aliado específico
        if ally_id and ally.id != ally_id:
            continue
        
        # Contar visitas en el período
        visits_period = Visit.query.filter(
            Visit.ally_id == ally.id,
            Visit.timestamp >= start_date_utc,
            Visit.timestamp <= end_date_utc
        ).all()
        
        # Obtener última visita
        last_visit = Visit.query.filter_by(ally_id=ally.id)\
            .order_by(Visit.timestamp.desc()).first()
        
        # Calcular días desde última visita
        days_since_last_visit = None
        if last_visit:
            days_since_last_visit = (now.replace(tzinfo=None) - last_visit.timestamp.replace(tzinfo=None)).days
        
        # Contar visitas únicas (diferentes empleados)
        unique_employees = db.session.query(func.count(func.distinct(Visit.user_id)))\
            .filter(Visit.ally_id == ally.id,
                   Visit.timestamp >= start_date_utc,
                   Visit.timestamp <= end_date_utc).scalar()
        
        allies_data.append({
            'id': ally.id,
            'name': ally.name,
            'category': ally.category,
            'visits_period': len(visits_period),
            'unique_employees': unique_employees,
            'last_visit': last_visit.timestamp.astimezone(colombia_tz) if last_visit else None,
            'days_since_last_visit': days_since_last_visit,
            'status': 'active' if days_since_last_visit and days_since_last_visit < 7 else 'inactive'
        })
    
    # Ordenar por número de visitas (descendente)
    allies_data.sort(key=lambda x: x['visits_period'], reverse=True)
    
    return render_template(
        'analytics/analytics_dashboard.html',
        title='Analítica Avanzada',
        employees_data=employees_data,
        allies_data=allies_data,
        all_users=all_users,
        all_allies=all_allies,
        start_date=start_date.strftime('%Y-%m-%d'),
        end_date=end_date.strftime('%Y-%m-%d'),
        selected_employee=employee_id,
        selected_ally=ally_id
    )

@bp.route('/export-report')
@login_required
def export_report():
    """
    Exporta el reporte en formato PDF o Excel
    """
    format_type = request.args.get('format', 'pdf')
    
    # Aquí implementarías la lógica de exportación
    # Por ahora retornamos un mensaje
    flash(f'Funcionalidad de exportación a {format_type.upper()} en desarrollo', 'info')
    return redirect(url_for('analytics.analytics_dashboard'))

@bp.route('/visit-report', methods=['GET', 'POST'])
@login_required
def visit_report():
    """
    Reporte de visitas con clasificación de tipo de movimiento
    """
    from app.forms import VisitForm
    from werkzeug.utils import secure_filename
    
    form = VisitForm()
    
    # Poblar opciones del formulario
    form.ally_id.choices = [(a.id, a.name) for a in Ally.query.order_by(Ally.name).all()]
    
    if form.validate_on_submit() and current_user.role == 'empleado':
        # Obtener el dispositivo del usuario
        device_id = current_user.traccar_device_id
        
        # Guardar evidencia si existe
        evidence_filename = None
        if form.evidence.data:
            file = form.evidence.data
            filename = secure_filename(file.filename)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            evidence_filename = f"{current_user.username}_{timestamp}_{filename}"
            filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], evidence_filename)
            file.save(filepath)
        
        # Crear visita manual
        new_visit = Visit(
            timestamp=datetime.now(pytz.utc),
            device_id=device_id,
            user_id=current_user.id,
            ally_id=form.ally_id.data,
            is_manual=True,
            category=form.category.data,
            observations=form.observations.data,
            evidence_path=evidence_filename,
            movement_type='manual',  # ← NUEVO: Las visitas manuales son tipo 'manual'
            avg_speed=0.0  # ← NUEVO: Sin velocidad en visitas manuales
        )
        db.session.add(new_visit)
        db.session.commit()
        
        flash('Visita registrada exitosamente.', 'success')
        return redirect(url_for('analytics.visit_report'))
    
    # Obtener visitas recientes
    colombia_tz = pytz.timezone('America/Bogota')
    now = datetime.now(colombia_tz)
    today_start = colombia_tz.localize(datetime.combine(now.date(), time.min))
    month_start = today_start.replace(day=1)
    
    # Query base
    visits_query = Visit.query.order_by(Visit.timestamp.desc()).limit(50)
    
    # Si es empleado, solo ver sus visitas
    if current_user.role == 'empleado':
        visits_query = visits_query.filter_by(user_id=current_user.id)
    
    visits = visits_query.all()
    
    # Agregar nombre del dispositivo a cada visita
    devices = get_devices_view()
    device_map = {device['id']: device['name'] for device in devices} if devices else {}
    
    for visit in visits:
        visit.device_name = device_map.get(visit.device_id, 'N/A')
    
    # Calcular resumen con filtros de tipo de movimiento
    if current_user.role == 'admin':
        summary = {
            'today': Visit.query.filter(Visit.timestamp >= today_start.astimezone(pytz.utc)).count(),
            'manual_month': Visit.query.filter(
                Visit.timestamp >= month_start.astimezone(pytz.utc),
                Visit.is_manual == True
            ).count(),
            'auto_month': Visit.query.filter(
                Visit.timestamp >= month_start.astimezone(pytz.utc),
                Visit.is_manual == False
            ).count(),
            # Nuevas estadísticas
            'walking_month': Visit.query.filter(
                Visit.timestamp >= month_start.astimezone(pytz.utc),
                Visit.movement_type == 'walking'
            ).count(),
            'vehicle_month': Visit.query.filter(
                Visit.timestamp >= month_start.astimezone(pytz.utc),
                Visit.movement_type == 'vehicle'
            ).count()
        }
    else:
        summary = {
            'today': Visit.query.filter(
                Visit.user_id == current_user.id,
                Visit.timestamp >= today_start.astimezone(pytz.utc)
            ).count(),
            'manual_month': Visit.query.filter(
                Visit.user_id == current_user.id,
                Visit.timestamp >= month_start.astimezone(pytz.utc),
                Visit.is_manual == True
            ).count(),
            'auto_month': Visit.query.filter(
                Visit.user_id == current_user.id,
                Visit.timestamp >= month_start.astimezone(pytz.utc),
                Visit.is_manual == False
            ).count(),
            # Nuevas estadísticas
            'walking_month': Visit.query.filter(
                Visit.user_id == current_user.id,
                Visit.timestamp >= month_start.astimezone(pytz.utc),
                Visit.movement_type == 'walking'
            ).count(),
            'vehicle_month': Visit.query.filter(
                Visit.user_id == current_user.id,
                Visit.timestamp >= month_start.astimezone(pytz.utc),
                Visit.movement_type == 'vehicle'
            ).count()
        }
    
    return render_template(
        'analytics/visit_report.html',
        title='Registro de Visitas',
        form=form,
        visits=visits,
        summary=summary
    )

@bp.route('/uploads/<filename>')
@login_required
def uploaded_file(filename):
    """
    Sirve archivos de evidencia subidos
    """
    upload_folder = current_app.config['UPLOAD_FOLDER']
    filepath = os.path.join(upload_folder, filename)
    
    if not os.path.exists(filepath):
        flash('Archivo no encontrado.', 'danger')
        return redirect(url_for('analytics.visit_report'))
    
    return send_file(filepath, as_attachment=False)