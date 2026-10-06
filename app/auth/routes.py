# Ruta: GPS_Comercial/app/auth/routes.py
import secrets
from flask import render_template, flash, redirect, url_for, request
from app import db
from app.auth import bp
from app.forms import LoginForm
from flask_login import current_user, login_user, logout_user, login_required
from app.models import User
import threading
import time as _clock

# Freno de fuerza bruta en el login: tras LOGIN_MAX_FAILS intentos fallidos por
# (IP, usuario) en LOGIN_WINDOW_S, se bloquea LOGIN_BLOCK_S (en memoria; 1 worker).
LOGIN_MAX_FAILS, LOGIN_WINDOW_S, LOGIN_BLOCK_S = 6, 600, 900
_login_fails = {}
_login_lock = threading.Lock()


def _client_ip():
    fwd = request.headers.get('X-Forwarded-For', '')
    return (fwd.split(',')[0].strip() if fwd else request.remote_addr) or '?'


def _login_blocked(key):
    rec = _login_fails.get(key)
    if not rec:
        return False
    if rec.get('until', 0) > _clock.time():
        return True
    return False


def _login_failed(key):
    now = _clock.time()
    with _login_lock:
        rec = _login_fails.setdefault(key, {'times': [], 'until': 0})
        rec['times'] = [t for t in rec['times'] if now - t < LOGIN_WINDOW_S] + [now]
        if len(rec['times']) >= LOGIN_MAX_FAILS:
            rec['until'] = now + LOGIN_BLOCK_S
            rec['times'] = []
        if len(_login_fails) > 5000:
            _login_fails.clear()


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if getattr(current_user, 'must_change_password', False):
            return redirect(url_for('auth.change_password'))
        return redirect(url_for('main.dashboard'))
    form = LoginForm()
    if form.validate_on_submit():
        key = f"{_client_ip()}|{(form.username.data or '').strip().lower()}"
        if _login_blocked(key):
            flash('Demasiados intentos fallidos. Espera 15 minutos e intenta de nuevo.', 'danger')
            return redirect(url_for('auth.login'))
        user = User.query.filter_by(username=form.username.data).first()
        if user is None or not user.check_password(form.password.data):
            _login_failed(key)
            flash('Usuario o contrasena invalidos', 'danger')
            return redirect(url_for('auth.login'))
        _login_fails.pop(key, None)
        # Vendedores usan la app instalada en el celular: la sesion se recuerda
        # siempre para que funcione sin volver a ingresar (incluso sin internet).
        login_user(user, remember=(form.remember_me.data or user.role == 'venta'))

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

        if len(new_pw) < 8 or not any(c.isdigit() for c in new_pw) or not any(c.isalpha() for c in new_pw):
            flash('La nueva contrasena debe tener al menos 8 caracteres e incluir letras y numeros.', 'danger')
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
    from flask import make_response
    resp = make_response(redirect(url_for('auth.login')))
    # Borra lo cacheado por el service worker (paginas/JSON con datos del usuario)
    resp.headers['Clear-Site-Data'] = '"cache"'
    return resp
    return redirect(url_for('main.index'))
