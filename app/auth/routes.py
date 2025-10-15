# Ruta: SST/app/auth/routes.py
from flask import render_template, flash, redirect, url_for, request
from app import db
from app.auth import bp
from app.forms import LoginForm
from flask_login import current_user, login_user, logout_user
from app.models import User
from sqlalchemy import or_

@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard')) # Redirige al dashboard si ya está logueado
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user is None or not user.check_password(form.password.data):
            flash('Usuario o contraseña inválidos', 'danger')
            return redirect(url_for('auth.login'))
        login_user(user, remember=form.remember_me.data)
        
        # --- ¡CAMBIO CLAVE AQUÍ! ---
        # Ahora redirige al dashboard después de un login exitoso
        return redirect(url_for('main.dashboard'))
        # --- FIN DEL CAMBIO ---
        
    return render_template('auth/login.html', title='Iniciar Sesión', form=form)

@bp.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('main.index'))

# La ruta '/register' ha sido eliminada.

