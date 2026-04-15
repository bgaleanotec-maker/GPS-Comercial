# Ruta: GPS_Comercial/app/schedule/routes.py
"""Torre de Control: cronograma, tareas, plantillas recurrentes, gestion de lider."""
import logging
from datetime import datetime, timedelta, date

import pytz
from flask import render_template, request, flash, redirect, url_for, abort, jsonify
from flask_login import login_required, current_user

from app import db
from app.models import (ScheduledTask, TaskTemplate, TaskAssignment,
                        User, Ally, Visit)
from app.schedule import bp

logger = logging.getLogger(__name__)
COLOMBIA_TZ = pytz.timezone('America/Bogota')


# ============================================================
# MI AGENDA - Vista del empleado
# ============================================================
@bp.route('/my-schedule', methods=['GET', 'POST'])
@login_required
def my_schedule():
    """Cronograma del empleado: agendar y ver tareas de la semana."""
    now = datetime.now(COLOMBIA_TZ)

    if request.method == 'POST':
        ally_id = request.form.get('ally_id', type=int)
        scheduled_date_str = request.form.get('scheduled_date')
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        task_type = request.form.get('task_type', 'visita')
        priority = request.form.get('priority', 'media')

        if not title or not scheduled_date_str:
            flash('Titulo y fecha son requeridos.', 'danger')
            return redirect(url_for('schedule.my_schedule'))

        try:
            scheduled_date = datetime.strptime(scheduled_date_str, '%Y-%m-%d').date()
        except ValueError:
            flash('Formato de fecha invalido.', 'danger')
            return redirect(url_for('schedule.my_schedule'))

        validation_type = 'manual' if task_type in ('gestion', 'checklist', 'otro') else 'gps'

        task = ScheduledTask(
            user_id=current_user.id,
            ally_id=ally_id if ally_id else None,
            scheduled_date=scheduled_date,
            title=title,
            description=description,
            task_type=task_type,
            priority=priority,
            validation_type=validation_type,
        )
        db.session.add(task)
        db.session.commit()
        flash(f'Tarea "{title}" agendada para {scheduled_date_str}.', 'success')
        return redirect(url_for('schedule.my_schedule'))

    # GET: mostrar cronograma semanal
    week_start = now.date() - timedelta(days=now.weekday())
    week_end = week_start + timedelta(days=6)

    week_offset = request.args.get('week', 0, type=int)
    week_start += timedelta(weeks=week_offset)
    week_end += timedelta(weeks=week_offset)

    tasks = ScheduledTask.query.filter(
        ScheduledTask.user_id == current_user.id,
        ScheduledTask.scheduled_date >= week_start,
        ScheduledTask.scheduled_date <= week_end,
    ).order_by(ScheduledTask.scheduled_date, ScheduledTask.priority.desc()).all()

    allies = Ally.query.order_by(Ally.name).all()

    # Agrupar por dia
    days = {}
    day_names = ['Lun', 'Mar', 'Mie', 'Jue', 'Vie', 'Sab', 'Dom']
    for i in range(7):
        d = week_start + timedelta(days=i)
        days[d] = {'name': day_names[d.weekday()], 'date': d, 'tasks': []}
    for task in tasks:
        if task.scheduled_date in days:
            days[task.scheduled_date]['tasks'].append(task)

    # Stats de la semana
    total_week = len(tasks)
    completed_week = sum(1 for t in tasks if t.status == 'cumplida')
    pending_week = sum(1 for t in tasks if t.status == 'pendiente')
    overdue_week = sum(1 for t in tasks if t.is_overdue)

    return render_template(
        'schedule/my_schedule.html',
        title='Mi Agenda',
        days=days,
        allies=allies,
        week_start=week_start,
        week_end=week_end,
        week_offset=week_offset,
        today=now.date(),
        stats={'total': total_week, 'completed': completed_week,
               'pending': pending_week, 'overdue': overdue_week},
    )


@bp.route('/task/<int:task_id>/complete', methods=['POST'])
@login_required
def complete_task(task_id):
    """Marcar tarea como completada manualmente."""
    task = ScheduledTask.query.get_or_404(task_id)
    if task.user_id != current_user.id and current_user.role not in ('admin', 'lider'):
        abort(403)

    task.status = 'cumplida'
    task.completed_at = datetime.now(pytz.utc)
    task.notes = request.form.get('notes', '')
    db.session.commit()
    flash('Tarea marcada como cumplida.', 'success')

    next_url = request.form.get('next') or url_for('schedule.my_schedule')
    return redirect(next_url)


@bp.route('/task/<int:task_id>/cancel', methods=['POST'])
@login_required
def cancel_task(task_id):
    """Cancelar una tarea."""
    task = ScheduledTask.query.get_or_404(task_id)
    if task.user_id != current_user.id and current_user.role not in ('admin', 'lider'):
        abort(403)
    task.status = 'cancelada'
    db.session.commit()
    flash('Tarea cancelada.', 'info')

    next_url = request.form.get('next') or url_for('schedule.my_schedule')
    return redirect(next_url)


@bp.route('/task/<int:task_id>/edit', methods=['POST'])
@login_required
def edit_task(task_id):
    """Editar una tarea existente."""
    task = ScheduledTask.query.get_or_404(task_id)
    if task.user_id != current_user.id and current_user.role not in ('admin', 'lider'):
        abort(403)
    if task.status in ('cumplida', 'cancelada'):
        flash('No se puede editar una tarea cumplida o cancelada.', 'warning')
        return redirect(url_for('schedule.my_schedule'))

    task.title = request.form.get('title', task.title).strip()
    task.description = request.form.get('description', '').strip()
    task.task_type = request.form.get('task_type', task.task_type)
    task.priority = request.form.get('priority', task.priority)

    new_date = request.form.get('scheduled_date')
    if new_date:
        try:
            task.scheduled_date = datetime.strptime(new_date, '%Y-%m-%d').date()
        except ValueError:
            pass

    ally_id = request.form.get('ally_id', type=int)
    task.ally_id = ally_id if ally_id else None
    task.validation_type = 'manual' if task.task_type in ('gestion', 'checklist', 'otro') else 'gps'

    db.session.commit()
    flash('Tarea actualizada.', 'success')
    next_url = request.form.get('next') or url_for('schedule.my_schedule')
    return redirect(next_url)


@bp.route('/task/<int:task_id>/reopen', methods=['POST'])
@login_required
def reopen_task(task_id):
    """Reabrir una tarea cancelada o vencida."""
    task = ScheduledTask.query.get_or_404(task_id)
    if current_user.role not in ('admin', 'lider'):
        abort(403)
    task.status = 'pendiente'
    task.completed_at = None
    task.auto_validated = False
    db.session.commit()
    flash('Tarea reabierta.', 'success')
    next_url = request.form.get('next') or url_for('schedule.control_tower')
    return redirect(next_url)


# ============================================================
# TORRE DE CONTROL - Admin/Lider
# ============================================================
@bp.route('/control-tower')
@login_required
def control_tower():
    """Torre de Control: dashboard para admin/lider con todas las tareas del equipo."""
    if current_user.role not in ('admin', 'lider'):
        abort(403)

    now = datetime.now(COLOMBIA_TZ)
    today = now.date()

    # Filtros
    date_from_str = request.args.get('date_from', today.strftime('%Y-%m-%d'))
    date_to_str = request.args.get('date_to', today.strftime('%Y-%m-%d'))
    employee_filter = request.args.get('employee_id', type=int)
    status_filter = request.args.get('status', 'all')
    priority_filter = request.args.get('priority', 'all')

    try:
        date_from = datetime.strptime(date_from_str, '%Y-%m-%d').date()
        date_to = datetime.strptime(date_to_str, '%Y-%m-%d').date()
    except ValueError:
        date_from = today
        date_to = today

    query = ScheduledTask.query.filter(
        ScheduledTask.scheduled_date >= date_from,
        ScheduledTask.scheduled_date <= date_to,
    )

    # Filtro por lider: solo su equipo (misma categoria)
    if current_user.role == 'lider':
        team_ids = [u.id for u in User.query.filter_by(categoria=current_user.categoria).all()]
        query = query.filter(ScheduledTask.user_id.in_(team_ids))

    if employee_filter:
        query = query.filter_by(user_id=employee_filter)

    if status_filter and status_filter != 'all':
        if status_filter == 'vencida':
            query = query.filter(
                ScheduledTask.status.in_(['pendiente', 'en_progreso']),
                ScheduledTask.scheduled_date < today
            )
        else:
            query = query.filter_by(status=status_filter)

    if priority_filter and priority_filter != 'all':
        query = query.filter_by(priority=priority_filter)

    tasks = query.order_by(ScheduledTask.scheduled_date, ScheduledTask.user_id).all()

    # Estadisticas
    total = len(tasks)
    cumplidas = sum(1 for t in tasks if t.status == 'cumplida')
    pendientes = sum(1 for t in tasks if t.status == 'pendiente')
    vencidas = sum(1 for t in tasks if t.is_overdue)
    auto_validadas = sum(1 for t in tasks if t.auto_validated)
    alta_prioridad = sum(1 for t in tasks if t.priority == 'alta')
    cumplimiento = (cumplidas / total * 100) if total > 0 else 0

    # Empleados para filtro
    if current_user.role == 'admin':
        employees = User.query.filter(User.role.in_(['empleado', 'lider'])).order_by(User.full_name).all()
    else:
        employees = User.query.filter_by(categoria=current_user.categoria).order_by(User.full_name).all()

    # Resumen por empleado
    employee_summary = {}
    for task in tasks:
        uid = task.user_id
        if uid not in employee_summary:
            employee_summary[uid] = {
                'user': task.user,
                'total': 0, 'cumplidas': 0, 'pendientes': 0, 'vencidas': 0
            }
        employee_summary[uid]['total'] += 1
        if task.status == 'cumplida':
            employee_summary[uid]['cumplidas'] += 1
        elif task.is_overdue:
            employee_summary[uid]['vencidas'] += 1
        else:
            employee_summary[uid]['pendientes'] += 1

    return render_template(
        'schedule/control_tower.html',
        title='Torre de Control',
        tasks=tasks,
        stats={
            'total': total, 'cumplidas': cumplidas, 'pendientes': pendientes,
            'vencidas': vencidas, 'auto_validadas': auto_validadas,
            'cumplimiento': cumplimiento, 'alta_prioridad': alta_prioridad,
        },
        employee_summary=employee_summary,
        employees=employees,
        date_from=date_from_str,
        date_to=date_to_str,
        employee_filter=employee_filter,
        status_filter=status_filter,
        priority_filter=priority_filter,
        today=today,
    )


# ============================================================
# GESTION DE TAREAS POR LIDER - Asignar tareas al equipo
# ============================================================
@bp.route('/assign-task', methods=['GET', 'POST'])
@login_required
def assign_task():
    """Lider o admin asigna tarea puntual a un empleado."""
    if current_user.role not in ('admin', 'lider'):
        abort(403)

    if request.method == 'POST':
        user_ids = request.form.getlist('user_ids')
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        scheduled_date_str = request.form.get('scheduled_date')
        task_type = request.form.get('task_type', 'visita')
        priority = request.form.get('priority', 'media')
        ally_id = request.form.get('ally_id', type=int)

        if not title or not scheduled_date_str or not user_ids:
            flash('Titulo, fecha y al menos un empleado son requeridos.', 'danger')
            return redirect(url_for('schedule.assign_task'))

        try:
            scheduled_date = datetime.strptime(scheduled_date_str, '%Y-%m-%d').date()
        except ValueError:
            flash('Formato de fecha invalido.', 'danger')
            return redirect(url_for('schedule.assign_task'))

        validation_type = 'manual' if task_type in ('gestion', 'checklist', 'otro') else 'gps'
        count = 0

        for uid in user_ids:
            task = ScheduledTask(
                user_id=int(uid),
                ally_id=ally_id if ally_id else None,
                scheduled_date=scheduled_date,
                title=title,
                description=description,
                task_type=task_type,
                priority=priority,
                validation_type=validation_type,
                assigned_by=current_user.id,
            )
            db.session.add(task)
            count += 1

        db.session.commit()
        flash(f'Tarea asignada a {count} empleado(s).', 'success')
        return redirect(url_for('schedule.control_tower'))

    # GET: form de asignacion
    if current_user.role == 'admin':
        employees = User.query.filter(
            User.role.in_(['empleado', 'lider']),
            User.employee_status == 'activo'
        ).order_by(User.full_name).all()
    else:
        employees = User.query.filter_by(
            categoria=current_user.categoria,
            employee_status='activo'
        ).order_by(User.full_name).all()

    allies = Ally.query.order_by(Ally.name).all()

    return render_template(
        'schedule/assign_task.html',
        title='Asignar Tarea',
        employees=employees,
        allies=allies,
    )


# ============================================================
# PLANTILLAS DE TAREAS RECURRENTES
# ============================================================
@bp.route('/templates')
@login_required
def manage_templates():
    """Gestionar plantillas de tareas recurrentes."""
    if current_user.role not in ('admin', 'lider'):
        abort(403)

    if current_user.role == 'admin':
        templates = TaskTemplate.query.order_by(TaskTemplate.created_at.desc()).all()
    else:
        templates = TaskTemplate.query.filter_by(
            categoria=current_user.categoria
        ).order_by(TaskTemplate.created_at.desc()).all()

    return render_template(
        'schedule/templates.html',
        title='Plantillas Recurrentes',
        templates=templates,
    )


@bp.route('/templates/create', methods=['GET', 'POST'])
@login_required
def create_template():
    """Crear nueva plantilla de tarea recurrente."""
    if current_user.role not in ('admin', 'lider'):
        abort(403)

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        task_type = request.form.get('task_type', 'visita')
        priority = request.form.get('priority', 'media')
        recurrence_type = request.form.get('recurrence_type', 'weekly')
        recurrence_days = ','.join(request.form.getlist('recurrence_days'))
        ally_id = request.form.get('ally_id', type=int)
        min_time = request.form.get('min_time_on_site', 30, type=int)
        assign_to_all = request.form.get('assign_to_all') == 'on'
        user_ids = request.form.getlist('user_ids')

        end_date_str = request.form.get('recurrence_end_date', '')
        end_date = None
        if end_date_str:
            try:
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass

        if not title:
            flash('El titulo es requerido.', 'danger')
            return redirect(url_for('schedule.create_template'))

        categoria = current_user.categoria if current_user.role == 'lider' else request.form.get('categoria', '')
        validation_type = 'manual' if task_type in ('gestion', 'checklist', 'otro') else 'gps'

        template = TaskTemplate(
            created_by=current_user.id,
            categoria=categoria,
            title=title,
            description=description,
            task_type=task_type,
            priority=priority,
            validation_type=validation_type,
            recurrence_type=recurrence_type,
            recurrence_days=recurrence_days,
            recurrence_end_date=end_date,
            ally_id=ally_id if ally_id else None,
            min_time_on_site=min_time,
            assign_to_all=assign_to_all,
        )
        db.session.add(template)
        db.session.flush()  # Get template.id

        # Crear asignaciones
        if not assign_to_all and user_ids:
            for uid in user_ids:
                assignment = TaskAssignment(
                    template_id=template.id,
                    user_id=int(uid),
                )
                db.session.add(assignment)

        db.session.commit()
        flash(f'Plantilla "{title}" creada exitosamente.', 'success')
        return redirect(url_for('schedule.manage_templates'))

    # GET
    if current_user.role == 'admin':
        employees = User.query.filter(
            User.role.in_(['empleado', 'lider']),
            User.employee_status == 'activo'
        ).order_by(User.full_name).all()
        categorias = sorted(set(u.categoria for u in User.query.all() if u.categoria))
    else:
        employees = User.query.filter_by(
            categoria=current_user.categoria,
            employee_status='activo'
        ).order_by(User.full_name).all()
        categorias = [current_user.categoria]

    allies = Ally.query.order_by(Ally.name).all()

    return render_template(
        'schedule/create_template.html',
        title='Nueva Plantilla',
        employees=employees,
        allies=allies,
        categorias=categorias,
    )


@bp.route('/templates/<int:template_id>/toggle', methods=['POST'])
@login_required
def toggle_template(template_id):
    """Activar/desactivar plantilla."""
    if current_user.role not in ('admin', 'lider'):
        abort(403)
    template = TaskTemplate.query.get_or_404(template_id)
    template.is_active = not template.is_active
    db.session.commit()
    estado = 'activada' if template.is_active else 'desactivada'
    flash(f'Plantilla "{template.title}" {estado}.', 'success')
    return redirect(url_for('schedule.manage_templates'))


@bp.route('/templates/<int:template_id>/delete', methods=['POST'])
@login_required
def delete_template(template_id):
    """Eliminar plantilla."""
    if current_user.role not in ('admin', 'lider'):
        abort(403)
    template = TaskTemplate.query.get_or_404(template_id)
    TaskAssignment.query.filter_by(template_id=template_id).delete()
    db.session.delete(template)
    db.session.commit()
    flash(f'Plantilla eliminada.', 'info')
    return redirect(url_for('schedule.manage_templates'))


@bp.route('/templates/<int:template_id>/generate', methods=['POST'])
@login_required
def generate_from_template(template_id):
    """Generar tareas manualmente desde una plantilla para una fecha."""
    if current_user.role not in ('admin', 'lider'):
        abort(403)

    template = TaskTemplate.query.get_or_404(template_id)
    target_date_str = request.form.get('target_date')

    if not target_date_str:
        flash('Fecha requerida.', 'danger')
        return redirect(url_for('schedule.manage_templates'))

    try:
        target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
    except ValueError:
        flash('Fecha invalida.', 'danger')
        return redirect(url_for('schedule.manage_templates'))

    count = _generate_tasks_for_template(template, target_date)
    flash(f'{count} tarea(s) generada(s) para {target_date_str}.', 'success')
    return redirect(url_for('schedule.manage_templates'))


# ============================================================
# DASHBOARD LIDER - Vista de negocio
# ============================================================
@bp.route('/leader-dashboard')
@login_required
def leader_dashboard():
    """Dashboard del lider: resumen de su negocio/mercado."""
    if current_user.role not in ('admin', 'lider'):
        abort(403)

    now = datetime.now(COLOMBIA_TZ)
    today = now.date()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    # Equipo del lider
    if current_user.role == 'lider':
        team = User.query.filter_by(categoria=current_user.categoria).all()
    else:
        cat_filter = request.args.get('categoria', '')
        if cat_filter:
            team = User.query.filter_by(categoria=cat_filter).all()
        else:
            team = User.query.filter(User.role.in_(['empleado', 'lider'])).all()

    team_ids = [u.id for u in team]
    active_team = [u for u in team if u.employee_status == 'activo']

    # Tareas de hoy
    tasks_today = ScheduledTask.query.filter(
        ScheduledTask.user_id.in_(team_ids),
        ScheduledTask.scheduled_date == today,
    ).all()

    # Tareas de la semana
    tasks_week = ScheduledTask.query.filter(
        ScheduledTask.user_id.in_(team_ids),
        ScheduledTask.scheduled_date >= week_start,
        ScheduledTask.scheduled_date <= today,
    ).all()

    # Tareas del mes
    tasks_month = ScheduledTask.query.filter(
        ScheduledTask.user_id.in_(team_ids),
        ScheduledTask.scheduled_date >= month_start,
        ScheduledTask.scheduled_date <= today,
    ).all()

    def calc_stats(tasks_list):
        total = len(tasks_list)
        cumplidas = sum(1 for t in tasks_list if t.status == 'cumplida')
        return {
            'total': total,
            'cumplidas': cumplidas,
            'pendientes': sum(1 for t in tasks_list if t.status == 'pendiente'),
            'vencidas': sum(1 for t in tasks_list if t.is_overdue),
            'cumplimiento': (cumplidas / total * 100) if total > 0 else 0,
        }

    # Resumen por empleado (semana actual)
    employee_data = []
    for user in active_team:
        user_tasks = [t for t in tasks_week if t.user_id == user.id]
        total = len(user_tasks)
        cumplidas = sum(1 for t in user_tasks if t.status == 'cumplida')
        employee_data.append({
            'user': user,
            'total': total,
            'cumplidas': cumplidas,
            'pendientes': sum(1 for t in user_tasks if t.status == 'pendiente'),
            'vencidas': sum(1 for t in user_tasks if t.is_overdue),
            'cumplimiento': (cumplidas / total * 100) if total > 0 else 0,
        })
    employee_data.sort(key=lambda x: x['cumplimiento'], reverse=True)

    # Templates activas
    if current_user.role == 'lider':
        active_templates = TaskTemplate.query.filter_by(
            categoria=current_user.categoria, is_active=True
        ).count()
    else:
        active_templates = TaskTemplate.query.filter_by(is_active=True).count()

    categorias = sorted(set(u.categoria for u in User.query.all() if u.categoria))

    return render_template(
        'schedule/leader_dashboard.html',
        title='Mi Negocio' if current_user.role == 'lider' else 'Dashboard General',
        stats_today=calc_stats(tasks_today),
        stats_week=calc_stats(tasks_week),
        stats_month=calc_stats(tasks_month),
        employee_data=employee_data,
        active_team=len(active_team),
        total_team=len(team),
        active_templates=active_templates,
        today=today,
        categorias=categorias,
        cat_filter=request.args.get('categoria', ''),
    )


# ============================================================
# API ENDPOINTS
# ============================================================
@bp.route('/api/validate-tasks', methods=['POST'])
@login_required
def validate_tasks_api():
    """API para validar tareas automaticamente basado en GPS."""
    if current_user.role != 'admin':
        abort(403)
    from app.schedule.validator import validate_pending_tasks
    validated = validate_pending_tasks()
    return jsonify({'validated': validated})


@bp.route('/api/task/<int:task_id>', methods=['GET'])
@login_required
def get_task_detail(task_id):
    """API: obtener detalle de una tarea como JSON."""
    task = ScheduledTask.query.get_or_404(task_id)
    if task.user_id != current_user.id and current_user.role not in ('admin', 'lider'):
        abort(403)

    return jsonify({
        'id': task.id,
        'title': task.title,
        'description': task.description or '',
        'task_type': task.task_type,
        'priority': task.priority or 'media',
        'scheduled_date': task.scheduled_date.strftime('%Y-%m-%d'),
        'status': task.status,
        'status_display': task.status_display,
        'ally_id': task.ally_id,
        'ally_name': task.ally.name if task.ally else None,
        'user_name': task.user.full_name if task.user else None,
        'assigned_by': task.assigner.full_name if task.assigner else None,
        'validation_type': task.validation_type,
        'auto_validated': task.auto_validated,
        'time_on_site_minutes': task.time_on_site_minutes,
        'notes': task.notes or '',
        'is_overdue': task.is_overdue,
        'created_at': task.created_at.strftime('%d/%m/%Y %H:%M') if task.created_at else None,
        'completed_at': task.completed_at.strftime('%d/%m/%Y %H:%M') if task.completed_at else None,
    })


# ============================================================
# FUNCIONES AUXILIARES
# ============================================================
def _generate_tasks_for_template(template, target_date):
    """Genera tareas para una plantilla en una fecha especifica."""
    count = 0

    # Obtener usuarios asignados
    if template.assign_to_all:
        users = User.query.filter_by(
            categoria=template.categoria,
            employee_status='activo'
        ).all()
    else:
        assignments = TaskAssignment.query.filter_by(
            template_id=template.id, is_active=True
        ).all()
        users = [a.user for a in assignments if a.user and a.user.employee_status == 'activo']

    for user in users:
        # Verificar que no exista ya una tarea de esta plantilla para este usuario y fecha
        existing = ScheduledTask.query.filter_by(
            user_id=user.id,
            template_id=template.id,
            scheduled_date=target_date,
        ).first()
        if existing:
            continue

        task = ScheduledTask(
            user_id=user.id,
            ally_id=template.ally_id,
            scheduled_date=target_date,
            title=template.title,
            description=template.description,
            task_type=template.task_type,
            priority=template.priority,
            validation_type=template.validation_type,
            min_time_on_site=template.min_time_on_site,
            assigned_by=template.created_by,
            template_id=template.id,
        )
        db.session.add(task)
        count += 1

    if count > 0:
        db.session.commit()
        template.last_generated = target_date

    return count


def generate_recurring_tasks():
    """Genera tareas recurrentes para hoy. Llamado por el background worker."""
    today = datetime.now(COLOMBIA_TZ).date()
    day_of_week = str(today.weekday())  # 0=Lun, 6=Dom
    day_of_month = today.day
    generated = 0

    templates = TaskTemplate.query.filter_by(is_active=True).all()

    for template in templates:
        # Verificar si ya se genero hoy
        if template.last_generated == today:
            continue

        # Verificar fecha fin
        if template.recurrence_end_date and today > template.recurrence_end_date:
            continue

        should_generate = False

        if template.recurrence_type == 'daily':
            should_generate = True
        elif template.recurrence_type == 'weekly':
            if template.recurrence_days:
                should_generate = day_of_week in template.recurrence_days.split(',')
        elif template.recurrence_type == 'monthly':
            if template.recurrence_days:
                should_generate = str(day_of_month) in template.recurrence_days.split(',')

        if should_generate:
            count = _generate_tasks_for_template(template, today)
            generated += count
            logger.info("Template #%d: %d tareas generadas para %s", template.id, count, today)

    return generated
