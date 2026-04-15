# Ruta: GPS_Comercial/app/user_management/routes.py
"""Gestion completa de usuarios: CRUD, rol, direcciones, estado, dispositivo."""
import logging
from flask import render_template, flash, redirect, url_for, abort, request
from app.user_management import bp
from flask_login import login_required, current_user
from app.models import User, Ally, UserAllyAssignment
from app.forms import UserCreationForm
from app import db
from app.traccar import get_devices

logger = logging.getLogger(__name__)


@bp.route('/manage', methods=['GET', 'POST'])
@login_required
def manage_users():
    if current_user.role not in ('admin', 'lider'):
        abort(403)

    form = UserCreationForm()

    if form.validate_on_submit() and current_user.role == 'admin':
        role = request.form.get('role', 'empleado')
        user = User(
            username=form.username.data,
            full_name=form.full_name.data,
            email=form.email.data,
            categoria=form.categoria.data,
            filial=form.filial.data,
            role=role,
            phone_number=request.form.get('phone_number', ''),
            home_address=request.form.get('home_address', ''),
            work_address=request.form.get('work_address', ''),
            employee_status='activo',
        )
        user.set_password('Vanti2025')
        db.session.add(user)
        db.session.commit()
        flash(f'Usuario "{form.full_name.data}" creado como {role}. Clave: Vanti2025', 'success')
        return redirect(url_for('user_management.manage_users'))

    # Asociar dispositivo (solo admin)
    if 'associate_device' in request.form and current_user.role == 'admin':
        user_id = request.form.get('user_id')
        device_id = request.form.get('device_id')
        u = db.session.get(User, user_id)
        if u:
            u.traccar_device_id = int(device_id) if device_id and device_id != "0" else None
            db.session.commit()
            flash(f'Dispositivo asociado para {u.username}.', 'success')
        return redirect(url_for('user_management.manage_users'))

    # Eliminar usuario (solo admin)
    if 'delete_user' in request.form and current_user.role == 'admin':
        uid = request.form.get('user_id_to_delete')
        u = db.session.get(User, uid)
        if u:
            if u.id == current_user.id:
                flash('No puedes eliminar tu propia cuenta.', 'danger')
            else:
                db.session.delete(u)
                db.session.commit()
                flash(f'Usuario {u.username} eliminado.', 'info')
        return redirect(url_for('user_management.manage_users'))

    # Cambiar estado (admin o lider de su equipo)
    if 'change_status' in request.form:
        uid = request.form.get('user_id')
        new_status = request.form.get('new_status', 'activo')
        u = db.session.get(User, uid)
        if u:
            if current_user.role == 'lider' and u.categoria != current_user.categoria:
                abort(403)
            u.employee_status = new_status
            u.status_notes = request.form.get('status_notes', '')
            db.session.commit()
            flash(f'Estado de {u.full_name} cambiado a {new_status}.', 'success')
        return redirect(url_for('user_management.manage_users'))

    # Listar usuarios segun rol
    if current_user.role == 'admin':
        users = User.query.order_by(User.full_name).all()
    else:
        # Lider solo ve su categoria
        users = User.query.filter_by(
            categoria=current_user.categoria
        ).order_by(User.full_name).all()

    devices = get_devices() if current_user.role == 'admin' else None
    device_map = {d['id']: d['name'] for d in devices} if devices else {}
    for user in users:
        user.device_name = device_map.get(user.traccar_device_id, 'Sin Dispositivo')

    # Stats
    total_users = len(users)
    active_users = sum(1 for u in users if u.employee_status == 'activo')
    by_role = {}
    for u in users:
        by_role[u.role] = by_role.get(u.role, 0) + 1

    return render_template('user_management/manage_users.html',
                           title='Gestionar Usuarios' if current_user.role == 'admin' else 'Mi Equipo',
                           form=form,
                           users=users, devices=devices,
                           stats={'total': total_users, 'active': active_users, 'by_role': by_role})


@bp.route('/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required
def edit_user(user_id):
    """Editar usuario completo."""
    if current_user.role not in ('admin', 'lider'):
        abort(403)

    user = db.session.get(User, user_id)
    if not user:
        abort(404)

    # Lider solo puede editar usuarios de su categoria
    if current_user.role == 'lider' and user.categoria != current_user.categoria:
        abort(403)

    if request.method == 'POST':
        user.full_name = request.form.get('full_name', user.full_name)
        user.email = request.form.get('email', user.email)
        user.phone_number = request.form.get('phone_number', '')
        user.home_address = request.form.get('home_address', '')
        user.work_address = request.form.get('work_address', '')
        user.employee_status = request.form.get('employee_status', 'activo')
        user.status_notes = request.form.get('status_notes', '')

        # Solo admin puede cambiar rol, categoria, filial
        if current_user.role == 'admin':
            user.role = request.form.get('role', user.role)
            user.categoria = request.form.get('categoria', user.categoria)
            user.filial = request.form.get('filial', user.filial)

        # Reset password si se solicita
        new_password = request.form.get('new_password', '').strip()
        if new_password:
            user.set_password(new_password)
            flash('Contrasena actualizada.', 'info')

        db.session.commit()
        flash(f'Usuario {user.username} actualizado.', 'success')
        return redirect(url_for('user_management.manage_users'))

    devices = get_devices() if current_user.role == 'admin' else None
    allies = Ally.query.order_by(Ally.name).all()
    assigned_ally_ids = [a.ally_id for a in UserAllyAssignment.query.filter_by(user_id=user.id, is_active=True).all()]

    return render_template('user_management/edit_user.html',
                           title=f'Editar {user.username}',
                           user=user, devices=devices, allies=allies,
                           assigned_ally_ids=assigned_ally_ids)
