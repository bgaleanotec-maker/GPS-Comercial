# Ruta: GPS_Comercial/app/auth/routes.py
import secrets
from flask import render_template, flash, redirect, url_for, request
from app import db
from app.auth import bp
from app.forms import LoginForm
from flask_login import current_user, login_user, logout_user, login_required
from app.models import User


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if getattr(current_user, 'must_change_password', False):
            return redirect(url_for('auth.change_password'))
        return redirect(url_for('main.dashboard'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user is None or not user.check_password(form.password.data):
            flash('Usuario o contrasena invalidos', 'danger')
            return redirect(url_for('auth.login'))
        login_user(user, remember=form.remember_me.data)

        # Si debe cambiar clave, redirigir
        if getattr(user, 'must_change_password', False):
            flash('Debes cambiar tu contrasena antes de continuar.', 'warning')
            return redirect(url_for('auth.change_password'))

        return redirect(url_for('main.dashboard'))

    return render_template('auth/login.html', title='Iniciar Sesion', form=form)


@bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """Cambio de contrasena obligatorio o voluntario."""
    forced = getattr(current_user, 'must_change_password', False)

    if request.method == 'POST':
        current_pw = request.form.get('current_password', '').strip()
        new_pw = request.form.get('new_password', '').strip()
        confirm_pw = request.form.get('confirm_password', '').strip()

        # Validaciones
        if not forced and not current_user.check_password(current_pw):
            flash('La contrasena actual es incorrecta.', 'danger')
            return redirect(url_for('auth.change_password'))

        if len(new_pw) < 6:
            flash('La nueva contrasena debe tener al menos 6 caracteres.', 'danger')
            return redirect(url_for('auth.change_password'))

        if new_pw != confirm_pw:
            flash('Las contrasenas no coinciden.', 'danger')
            return redirect(url_for('auth.change_password'))

        current_user.set_password(new_pw)
        current_user.must_change_password = False
        db.session.commit()
        flash('Contrasena actualizada exitosamente.', 'success')
        return redirect(url_for('main.dashboard'))

    return render_template('auth/change_password.html',
                           title='Cambiar Contrasena', forced=forced)


@bp.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('main.index'))
