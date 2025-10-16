# Ruta: SST/app/analytics/routes.py
from flask import render_template, flash, redirect, url_for, request, send_file
from app.analytics import bp
from flask_login import login_required, current_user
from app.models import Visit, Ally, User, Infraction
from app.forms import VisitForm
from app import db
from datetime import datetime, timedelta
import pytz
from werkzeug.utils import secure_filename
import os
from flask import current_app
from app.main.routes import get_devices_view, get_device_positions_view, calculate_distance_from_points
from app.analytics.export_utils import generate_dashboard_excel

@bp.route('/visit-report', methods=['GET', 'POST'])
@login_required
def visit_report():
    form = VisitForm()
    
    # Poblar opciones de aliados
    allies = Ally.query.order_by(Ally.name).all()
    form.ally_id.choices = [(ally.id, ally.name) for ally in allies]
    
    if form.validate_on_submit() and current_user.role == 'empleado':
        # Manejo de evidencia
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
            device_id=current_user.traccar_device_id,
            user_id=current_user.id,
            ally_id=form.ally_id.data,
            is_manual=True,
            category=form.category.data,
            observations=form.observations.data,
            evidence_path=evidence_filename
        )
        db.session.add(new_visit)
        db.session.commit()
        flash('Visita registrada con éxito.', 'success')
        return redirect(url_for('analytics.visit_report'))
    
    # Obtener visitas según rol
    if current_user.role == 'admin':
        visits = Visit.query.order_by(Visit.timestamp.desc()).limit(100).all()
    else:
        visits = Visit.query.filter_by(user_id=current_user.id)\
            .order_by(Visit.timestamp.desc()).limit(100).all()
    
    # Obtener mapa de dispositivos
    devices = get_devices_view()
    device_map = {device['id']: device['name'] for device in devices} if devices else {}
    
    # Agregar nombre de dispositivo a cada visita
    for visit in visits:
        visit.device_name = device_map.get(visit.device_id, 'N/A')
    
    # Calcular resumen
    colombia_tz = pytz.timezone('America/Bogota')
    now = datetime.now(colombia_tz)
    today_start = colombia_tz.localize(datetime.combine(now.date(), datetime.min.time())).astimezone(pytz.utc)
    month_start = today_start.replace(day=1)
    
    if current_user.role == 'admin':
        visits_today = Visit.query.filter(Visit.timestamp >= today_start).count()
        visits_manual_month = Visit.query.filter(
            Visit.timestamp >= month_start,
            Visit.is_manual == True
        ).count()
        visits_auto_month = Visit.query.filter(
            Visit.timestamp >= month_start,
            Visit.is_manual == False
        ).count()
    else:
        visits_today = Visit.query.filter(
            Visit.user_id == current_user.id,
            Visit.timestamp >= today_start
        ).count()
        visits_manual_month = Visit.query.filter(
            Visit.user_id == current_user.id,
            Visit.timestamp >= month_start,
            Visit.is_manual == True
        ).count()
        visits_auto_month = Visit.query.filter(
            Visit.user_id == current_user.id,
            Visit.timestamp >= month_start,
            Visit.is_manual == False
        ).count()
    
    summary = {
        'today': visits_today,
        'manual_month': visits_manual_month,
        'auto_month': visits_auto_month
    }
    
    return render_template(
        'analytics/visit_report.html',
        title='Analítica de Visitas',
        form=form,
        visits=visits,
        summary=summary
    )

@bp.route('/uploads/<filename>')
@login_required
def uploaded_file(filename):
    """Sirve archivos de evidencia subidos."""
    return send_file(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))

@bp.route('/dashboard')
@login_required
def analytics_dashboard():
    """
    Dashboard avanzado de analítica comercial con filtros y métricas detalladas.
    """
    colombia_tz = pytz.timezone('America/Bogota')
    now = datetime.now(colombia_tz)
    
    # Obtener parámetros de filtro
    start_date_str = request.args.get('start_date', now.replace(day=1).strftime('%Y-%m-%d'))
    end_date_str = request.args.get('end_date', now.strftime('%Y-%m-%d'))
    selected_employee = request.args.get('employee_id', type=int)
    selected_ally = request.args.get('ally_id', type=int)
    
    # Convertir fechas
    start_date = colombia_tz.localize(datetime.strptime(start_date_str, '%Y-%m-%d'))
    end_date = colombia_tz.localize(datetime.strptime(end_date_str + ' 23:59:59', '%Y-%m-%d %H:%M:%S'))
    
    # Convertir a UTC para queries
    start_date_utc = start_date.astimezone(pytz.utc)
    end_date_utc = end_date.astimezone(pytz.utc)
    
    # Obtener dispositivos de Traccar
    devices = get_devices_view()
    device_map = {device['id']: device['name'] for device in devices} if devices else {}
    
    # === ANÁLISIS POR EMPLEADO ===
    all_users = User.query.filter_by(role='empleado').order_by(User.full_name).all()
    employees_data = []
    
    for user in all_users:
        # Aplicar filtro de empleado si existe
        if selected_employee and user.id != selected_employee:
            continue
            
        device_id = user.traccar_device_id
        device_name = device_map.get(device_id, 'Sin asignar')
        
        # Calcular kilómetros
        distance_today_km = 0
        distance_month_km = 0
        distance_total_km = 0
        
        if device_id:
            today_start = colombia_tz.localize(datetime.combine(now.date(), datetime.min.time()))
            month_start = today_start.replace(day=1)
            total_start = colombia_tz.localize(datetime(2000, 1, 1))
            
            positions_today = get_device_positions_view(device_id, today_start, now)
            positions_month = get_device_positions_view(device_id, month_start, now)
            positions_total = get_device_positions_view(device_id, total_start, now)
            
            distance_today_km = calculate_distance_from_points(positions_today) / 1000
            distance_month_km = calculate_distance_from_points(positions_month) / 1000
            distance_total_km = calculate_distance_from_points(positions_total) / 1000
        
        # Contar visitas en el período
        visits_query = Visit.query.filter(
            Visit.user_id == user.id,
            Visit.timestamp >= start_date_utc,
            Visit.timestamp <= end_date_utc
        )
        
        if selected_ally:
            visits_query = visits_query.filter_by(ally_id=selected_ally)
            
        visits_period = visits_query.count()
        
        # Contar infracciones en el período
        infractions_period = Infraction.query.filter(
            Infraction.user_id == user.id,
            Infraction.timestamp >= start_date_utc,
            Infraction.timestamp <= end_date_utc
        ).count()
        
        employees_data.append({
            'id': user.id,
            'username': user.username,
            'full_name': user.full_name or user.username,
            'device_name': device_name,
            'distance_today_km': distance_today_km,
            'distance_month_km': distance_month_km,
            'distance_total_km': distance_total_km,
            'visits_period': visits_period,
            'infractions_period': infractions_period
        })
    
    # === ANÁLISIS POR ALIADO ===
    all_allies = Ally.query.order_by(Ally.name).all()
    allies_data = []
    
    for ally in all_allies:
        # Aplicar filtro de aliado si existe
        if selected_ally and ally.id != selected_ally:
            continue
            
        # Obtener visitas en el período
        visits_query = Visit.query.filter(
            Visit.ally_id == ally.id,
            Visit.timestamp >= start_date_utc,
            Visit.timestamp <= end_date_utc
        )
        
        if selected_employee:
            visits_query = visits_query.filter_by(user_id=selected_employee)
            
        visits_in_period = visits_query.all()
        visits_period = len(visits_in_period)
        
        # Empleados únicos que visitaron
        unique_employees = len(set(v.user_id for v in visits_in_period if v.user_id))
        
        # Última visita
        last_visit_record = Visit.query.filter_by(ally_id=ally.id)\
            .order_by(Visit.timestamp.desc()).first()
        
        last_visit = None
        days_since_last_visit = 0
        status = 'inactive'
        
        if last_visit_record:
            last_visit = last_visit_record.timestamp.astimezone(colombia_tz)
            days_since_last_visit = (now - last_visit).days
            status = 'active' if days_since_last_visit <= 7 else 'inactive'
        
        allies_data.append({
            'id': ally.id,
            'name': ally.name,
            'category': ally.category,
            'visits_period': visits_period,
            'unique_employees': unique_employees,
            'last_visit': last_visit,
            'days_since_last_visit': days_since_last_visit,
            'status': status
        })
    
    return render_template(
        'analytics/analytics_dashboard.html',
        title='Dashboard de Analítica',
        employees_data=employees_data,
        allies_data=allies_data,
        all_users=all_users,
        all_allies=all_allies,
        start_date=start_date_str,
        end_date=end_date_str,
        selected_employee=selected_employee,
        selected_ally=selected_ally,
        date_from=start_date_str,
        date_to=end_date_str,
        employee_filter=str(selected_employee) if selected_employee else 'all',
        ally_filter=str(selected_ally) if selected_ally else 'all',
        employees_list=[(u.id, u.full_name or u.username) for u in all_users],
        allies_list=[(a.id, a.name) for a in all_allies]
    )

@bp.route('/dashboard/export')
@login_required
def export_dashboard():
    """
    Exporta el dashboard completo a Excel con todas las hojas de análisis.
    """
    if current_user.role != 'admin':
        flash('Solo los administradores pueden exportar el dashboard completo.', 'danger')
        return redirect(url_for('analytics.analytics_dashboard'))
    
    colombia_tz = pytz.timezone('America/Bogota')
    now = datetime.now(colombia_tz)
    
    # Obtener los mismos parámetros del dashboard
    start_date_str = request.args.get('date_from', now.replace(day=1).strftime('%Y-%m-%d'))
    end_date_str = request.args.get('date_to', now.strftime('%Y-%m-%d'))
    employee_filter = request.args.get('employee', 'all')
    ally_filter = request.args.get('ally', 'all')
    
    # Convertir fechas
    start_date = colombia_tz.localize(datetime.strptime(start_date_str, '%Y-%m-%d'))
    end_date = colombia_tz.localize(datetime.strptime(end_date_str + ' 23:59:59', '%Y-%m-%d %H:%M:%S'))
    
    start_date_utc = start_date.astimezone(pytz.utc)
    end_date_utc = end_date.astimezone(pytz.utc)
    
    # Obtener dispositivos
    devices = get_devices_view()
    device_map = {device['id']: device['name'] for device in devices} if devices else {}
    
    # Query de visitas
    visits_query = Visit.query.filter(
        Visit.timestamp >= start_date_utc,
        Visit.timestamp <= end_date_utc
    )
    
    if employee_filter != 'all':
        visits_query = visits_query.filter_by(user_id=int(employee_filter))
    
    if ally_filter != 'all':
        visits_query = visits_query.filter_by(ally_id=int(ally_filter))
    
    visits = visits_query.order_by(Visit.timestamp.desc()).all()
    
    # Agregar nombres
    for visit in visits:
        visit.device_name = device_map.get(visit.device_id, 'N/A')
        if visit.user:
            visit.employee_name = visit.user.full_name or visit.user.username
        else:
            visit.employee_name = 'N/A'
    
    # Calcular datos de empleados
    employees = User.query.filter_by(role='empleado').all()
    employees_data = []
    
    for emp in employees:
        emp_visits = [v for v in visits if v.user_id == emp.id]
        employees_data.append({
            'name': emp.full_name or emp.username,
            'vehicle': device_map.get(emp.traccar_device_id, 'Sin asignar'),
            'km_today': 0,
            'km_month': 0,
            'km_total': 0,
            'visits': len(emp_visits),
            'infractions': 0
        })
    
    # Datos de aliados
    allies = Ally.query.all()
    allies_data = []
    
    for ally in allies:
        ally_visits = [v for v in visits if v.ally_id == ally.id]
        unique_employees = len(set(v.user_id for v in ally_visits if v.user_id))
        
        last_visit = max([v.timestamp for v in ally_visits], default=None)
        if last_visit:
            last_visit_str = last_visit.astimezone(colombia_tz).strftime('%d/%m/%Y')
            days_since = (now - last_visit.astimezone(colombia_tz)).days
            status = 'Activo' if days_since <= 7 else 'Inactivo'
        else:
            last_visit_str = '-'
            status = 'Inactivo'
        
        allies_data.append({
            'name': ally.name,
            'category': ally.category or '-',
            'visits_period': len(ally_visits),
            'unique_employees': unique_employees,
            'last_visit': last_visit_str,
            'status': status
        })
    
    # Preparar datos para el Excel
    data = {
        'date_from': start_date.strftime('%d/%m/%Y'),
        'date_to': end_date.strftime('%d/%m/%Y'),
        'total_employees': len(employees),
        'total_allies': len(allies),
        'total_visits': len(visits),
        'active_allies': len([a for a in allies_data if a['status'] == 'Activo']),
        'avg_visits': len(visits) / len(allies) if len(allies) > 0 else 0,
        'employees_data': employees_data,
        'allies_data': allies_data,
        'visits_detail': visits
    }
    
    # Generar Excel
    excel_file = generate_dashboard_excel(data)
    
    # Nombre del archivo
    filename = f"Dashboard_Analitica_{datetime.now(colombia_tz).strftime('%Y%m%d_%H%M%S')}.xlsx"
    
    return send_file(
        excel_file,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )