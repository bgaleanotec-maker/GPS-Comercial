# Ruta: SST/app/user_management/routes.py
from flask import render_template, flash, redirect, url_for, abort, request
from app.user_management import bp
from flask_login import login_required, current_user
from app.models import User
from app.forms import UserCreationForm
from app import db
from app.traccar import get_devices

@bp.route('/manage', methods=['GET', 'POST'])
@login_required
def manage_users():
    if current_user.role != 'admin':
        abort(403)

    form = UserCreationForm()
    if form.validate_on_submit():
        user = User(
            username=form.username.data,
            full_name=form.full_name.data,
            email=form.email.data,
            categoria=form.categoria.data,  # ← NUEVO
            filial=form.filial.data  # ← NUEVO
        )
        user.set_password('Vanti2025')
        db.session.add(user)
        db.session.commit()
        flash(f'Usuario "{form.full_name.data}" creado con éxito.', 'success')
        return redirect(url_for('user_management.manage_users'))

    # Lógica para asociar un dispositivo
    if 'associate_device' in request.form:
        user_id = request.form.get('user_id')
        device_id = request.form.get('device_id')
        user_to_associate = db.session.get(User,user_id)
        if user_to_associate:
            user_to_associate.traccar_device_id = int(device_id) if device_id and device_id != "0" else None
            db.session.commit()
            flash(f'Dispositivo asociado para el usuario {user_to_associate.username}.', 'success')
            return redirect(url_for('user_management.manage_users'))

    # Lógica para actualizar categoría y filial
    if 'update_classification' in request.form:
        user_id = request.form.get('user_id')
        categoria = request.form.get('categoria')
        filial = request.form.get('filial')
        user_to_update = db.session.get(User,user_id)
        if user_to_update:
            user_to_update.categoria = categoria
            user_to_update.filial = filial
            db.session.commit()
            flash(f'Clasificación actualizada para {user_to_update.username}.', 'success')
            return redirect(url_for('user_management.manage_users'))

    # Lógica para eliminar un usuario
    if 'delete_user' in request.form:
        user_id_to_delete = request.form.get('user_id_to_delete')
        user_to_delete = db.session.get(User,user_id_to_delete)
        if user_to_delete:
            if user_to_delete.id == current_user.id:
                flash('No puedes eliminar tu propia cuenta.', 'danger')
            else:
                db.session.delete(user_to_delete)
                db.session.commit()
                flash(f'Usuario {user_to_delete.username} eliminado.', 'info')
            return redirect(url_for('user_management.manage_users'))

    users = User.query.order_by(User.username).all()
    devices = get_devices()

    device_map = {device['id']: device['name'] for device in devices} if devices else {}
    for user in users:
        user.device_name = device_map.get(user.traccar_device_id, '--- Sin Dispositivo ---')

    return render_template('user_management/manage_users.html', 
                         title='Gestionar Usuarios', 
                         form=form, 
                         users=users, 
                         devices=devices)