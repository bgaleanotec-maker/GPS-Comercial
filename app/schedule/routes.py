# Ruta: GPS_Comercial/app/schedule/routes.py
"""Torre de Control: cronograma, tareas, validacion GPS automatica."""
import logging
from datetime import datetime, timedelta, date

import pytz
from flask import render_template, request, flash, redirect, url_for, abort, jsonify
from flask_login import login_required, current_user

from app import db
from app.models import ScheduledTask, User, Ally, Visit
from app.schedule import bp

logger = logging.getLogger(__name__)
COLOMBIA_TZ = pytz.timezone('America/Bogota')


@bp.route('/my-schedule', methods=['GET', 'POST'])
@login_required
def my_schedule():
    """Cronograma del empleado: agendar y ver tareas de la semana."""
    now = datetime.now(COLOMBIA_TZ)

    if request.method == 'POST':
        # Crear nueva tarea
        ally_id = request.form.get('ally_id', type=int)
        scheduled_date_str = request.form.get('scheduled_date')
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        task_type = request.form.get('task_type', 'visita')

        if not title or not scheduled_date_str:
            flash('Titulo y fecha son requeridos.', 'danger')
            return redirect(url_for('schedule.my_schedule'))

        try:
            scheduled_date = datetime.strptime(scheduled_date_str, '%Y-%m-%d').date()
        except ValueError:
            flash('Formato de fecha invalido.', 'danger')
            return redirect(url_for('schedule.my_schedule'))

        # Tareas tipo gestion/checklist/otro son manuales, visita/reunion son GPS
        validation_type = 'manual' if task_type in ('gestion', 'checklist', 'otro') else 'gps'

        task = ScheduledTask(
            user_id=current_user.id,
            ally_id=ally_id if ally_id else None,
            scheduled_date=scheduled_date,
            title=title,
            description=description,
            task_type=task_type,
            validation_type=validation_type,
        )
        db.session.add(task)
        db.session.commit()
        flash(f'Tarea "{title}" agendada para {scheduled_date_str}.', 'success')
        return redirect(url_for('schedule.my_schedule'))

    # GET: mostrar cronograma semanal
    week_start = now.date() - timedelta(days=now.weekday())
    week_end = week_start + timedelta(days=6)

    # Parametro de semana (offset)
    week_offset = request.args.get('week', 0, type=int)
    week_start += timedelta(weeks=week_offset)
    week_end += timedelta(weeks=week_offset)

    tasks = ScheduledTask.query.filter(
        ScheduledTask.user_id == current_user.id,
        ScheduledTask.scheduled_date >= week_start,
        ScheduledTask.scheduled_date <= week_end,
    ).order_by(ScheduledTask.scheduled_date).all()

    allies = Ally.query.order_by(Ally.name).all()

    # Agrupar por dia
    days = {}
    for i in range(7):
        d = week_start + timedelta(days=i)
        day_name = ['Lun', 'Mar', 'Mie', 'Jue', 'Vie', 'Sab', 'Dom'][d.weekday()]
        days[d] = {'name': day_name, 'date': d, 'tasks': []}
    for task in tasks:
        if task.scheduled_date in days:
            days[task.scheduled_date]['tasks'].append(task)

    return render_template(
        'schedule/my_schedule.html',
        title='Mi Cronograma',
        days=days,
        allies=allies,
        week_start=week_start,
        week_end=week_end,
        week_offset=week_offset,
        today=now.date(),
    )


@bp.route('/task/<int:task_id>/complete', methods=['POST'])
@login_required
def complete_task(task_id):
    """Marcar tarea como completada manualmente."""
    task = ScheduledTask.query.get_or_404(task_id)
    if task.user_id != current_user.id and current_user.role != 'admin':
        abort(403)

    task.status = 'cumplida'
    task.completed_at = datetime.now(pytz.utc)
    task.notes = request.form.get('notes', '')
    db.session.commit()
    flash('Tarea marcada como cumplida.', 'success')
    return redirect(url_for('schedule.my_schedule'))


@bp.route('/task/<int:task_id>/cancel', methods=['POST'])
@login_required
def cancel_task(task_id):
    """Cancelar una tarea."""
    task = ScheduledTask.query.get_or_404(task_id)
    if task.user_id != current_user.id and current_user.role != 'admin':
        abort(403)
    task.status = 'cancelada'
    db.session.commit()
    flash('Tarea cancelada.', 'info')
    return redirect(url_for('schedule.my_schedule'))


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

    try:
        date_from = datetime.strptime(date_from_str, '%Y-%m-%d').date()
        date_to = datetime.strptime(date_to_str, '%Y-%m-%d').date()
    except ValueError:
        date_from = today
        date_to = today

    # Query base
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

    tasks = query.order_by(ScheduledTask.scheduled_date, ScheduledTask.user_id).all()

    # Estadisticas
    total = len(tasks)
    cumplidas = sum(1 for t in tasks if t.status == 'cumplida')
    pendientes = sum(1 for t in tasks if t.status == 'pendiente')
    vencidas = sum(1 for t in tasks if t.is_overdue)
    auto_validadas = sum(1 for t in tasks if t.auto_validated)
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
            'cumplimiento': cumplimiento,
        },
        employee_summary=employee_summary,
        employees=employees,
        date_from=date_from_str,
        date_to=date_to_str,
        employee_filter=employee_filter,
        status_filter=status_filter,
        today=today,
    )


@bp.route('/api/validate-tasks', methods=['POST'])
@login_required
def validate_tasks_api():
    """API para validar tareas automaticamente basado en GPS (llamado por el worker)."""
    if current_user.role != 'admin':
        abort(403)
    from app.schedule.validator import validate_pending_tasks
    validated = validate_pending_tasks()
    return jsonify({'validated': validated})
