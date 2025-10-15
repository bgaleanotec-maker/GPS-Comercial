# Ruta: SST/app/user_management/routes.py
from flask import render_template, flash, redirect, url_for, abort, request
from app.user_management import bp
from flask_login import login_required, current_user
from app.models import User
from app.forms import UserCreationForm
from app import db
from app.main.routes import get_devices_view # Reutilizamos la función para obtener dispositivos

@bp.route('/manage', methods=['GET', 'POST'])
@login_required
def manage_users():
    if current_user.role != 'admin':
        abort(403)

    form = UserCreationForm()
    if form.validate_on_submit():
        user = User(
            username=form.username.data,
            full_name=form.full_name.data, # <-- GUARDAMOS EL NOMBRE COMPLETO
            email=form.email.data
        )
        user.set_password('Vanti2025') # Contraseña genérica
        db.session.add(user)
        db.session.commit()
        flash(f'Usuario "{form.full_name.data}" creado con éxito.', 'success')
        return redirect(url_for('user_management.manage_users'))

    # Lógica para asociar un dispositivo
    if 'associate_device' in request.form:
        user_id = request.form.get('user_id')
        device_id = request.form.get('device_id')
        user_to_associate = User.query.get(user_id)
        if user_to_associate:
            # Si se selecciona "Sin Dispositivo", se guarda None (o 0/null)
            user_to_associate.traccar_device_id = int(device_id) if device_id and device_id != "0" else None
            db.session.commit()
            flash(f'Dispositivo asociado para el usuario {user_to_associate.username}.', 'success')
            return redirect(url_for('user_management.manage_users'))

    # Lógica para eliminar un usuario
    if 'delete_user' in request.form:
        user_id_to_delete = request.form.get('user_id_to_delete')
        user_to_delete = User.query.get(user_id_to_delete)
        if user_to_delete:
            # Prevención para no eliminar al propio usuario admin logueado
            if user_to_delete.id == current_user.id:
                flash('No puedes eliminar tu propia cuenta.', 'danger')
            else:
                db.session.delete(user_to_delete)
                db.session.commit()
                flash(f'Usuario {user_to_delete.username} eliminado.', 'info')
            return redirect(url_for('user_management.manage_users'))

    users = User.query.order_by(User.username).all()
    devices = get_devices_view()

    # Mapear nombres de dispositivos a los usuarios para fácil visualización
    device_map = {device['id']: device['name'] for device in devices} if devices else {}
    for user in users:
        user.device_name = device_map.get(user.traccar_device_id, '--- Sin Dispositivo ---')

    return render_template('user_management/manage_users.html', title='Gestionar Usuarios', form=form, users=users, devices=devices)

