# Ruta: app/api_keys/routes.py
"""
Gestión completa de API Keys para GPS Comercial.
Permite a los administradores crear, listar, revocar y auditar claves de API.
"""
from flask import render_template, flash, redirect, url_for, abort, request, jsonify, current_app
from app.api_keys import bp
from flask_login import login_required, current_user
from app.models import ApiKey, User
from app import db
from datetime import datetime, timedelta, timezone
from functools import wraps


# ─── DECORADOR: Solo admin ───────────────────────────────────────────────────
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            abort(403)
        return f(*args, **kwargs)
    return decorated_function


# ─── DECORADOR: Autenticación por API Key (para endpoints externos) ──────────
def api_key_required(f):
    """
    Decorador para rutas que aceptan autenticación por API Key.
    Busca el header: Authorization: Bearer gps_XXXXX
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'API Key requerida. Usa: Authorization: Bearer gps_XXXXX'}), 401

        raw_key = auth_header.split('Bearer ', 1)[1].strip()
        api_key = ApiKey.query.filter_by(key=raw_key, is_active=True).first()

        if not api_key:
            return jsonify({'error': 'API Key inválida o revocada.'}), 401

        if api_key.is_expired:
            return jsonify({'error': 'API Key expirada.'}), 401

        # Registrar uso
        api_key.record_usage()
        db.session.commit()

        return f(*args, **kwargs)
    return decorated_function


# ─── VISTAS DE ADMINISTRACIÓN ─────────────────────────────────────────────────

@bp.route('/manage', methods=['GET'])
@login_required
@admin_required
def manage_keys():
    """Panel de gestión de API Keys."""
    keys = ApiKey.query.order_by(ApiKey.created_at.desc()).all()
    users = User.query.order_by(User.username).all()

    # Stats
    total = ApiKey.query.count()
    active = ApiKey.query.filter_by(is_active=True).count()
    revoked = ApiKey.query.filter_by(is_active=False).count()
    expired = sum(1 for k in keys if k.is_expired and k.is_active)

    stats = {
        'total': total,
        'active': active,
        'revoked': revoked,
        'expired': expired,
    }

    return render_template(
        'api_keys/manage_keys.html',
        title='Gestión de API Keys',
        keys=keys,
        users=users,
        stats=stats,
    )


@bp.route('/create', methods=['POST'])
@login_required
@admin_required
def create_key():
    """Crea una nueva API Key."""
    name = request.form.get('name', '').strip()
    user_id = request.form.get('user_id')
    permissions = request.form.get('permissions', 'read')
    scopes_raw = request.form.getlist('scopes')
    expires_days = request.form.get('expires_days', '0')
    notes = request.form.get('notes', '').strip()

    # Validaciones
    if not name:
        flash('El nombre de la API Key es requerido.', 'danger')
        return redirect(url_for('api_keys.manage_keys'))

    if not user_id:
        flash('Debes seleccionar un usuario propietario.', 'danger')
        return redirect(url_for('api_keys.manage_keys'))

    owner = db.session.get(User,user_id)
    if not owner:
        flash('Usuario no encontrado.', 'danger')
        return redirect(url_for('api_keys.manage_keys'))

    if not scopes_raw:
        scopes_raw = ['devices']

    # Calcular expiración
    expires_at = None
    try:
        days = int(expires_days)
        if days > 0:
            expires_at = datetime.now(timezone.utc) + timedelta(days=days)
    except ValueError:
        pass

    # Generar clave segura
    prefix, full_key = ApiKey.generate_key()

    api_key = ApiKey(
        name=name,
        key=full_key,
        prefix=prefix,
        user_id=int(user_id),
        permissions=permissions,
        scopes=','.join(scopes_raw),
        expires_at=expires_at,
        notes=notes or None,
    )

    db.session.add(api_key)
    db.session.commit()

    # Mostrar la clave COMPLETA una sola vez al admin
    flash(
        f'✅ API Key creada exitosamente. '
        f'Copia esta clave ahora — no se volverá a mostrar: <strong class="font-mono">{full_key}</strong>',
        'success_key'
    )
    return redirect(url_for('api_keys.manage_keys'))


@bp.route('/revoke/<int:key_id>', methods=['POST'])
@login_required
@admin_required
def revoke_key(key_id):
    """Revoca (desactiva) una API Key."""
    api_key = ApiKey.query.get_or_404(key_id)
    api_key.is_active = False
    db.session.commit()
    flash(f'API Key "{api_key.name}" revocada correctamente.', 'warning')
    return redirect(url_for('api_keys.manage_keys'))


@bp.route('/activate/<int:key_id>', methods=['POST'])
@login_required
@admin_required
def activate_key(key_id):
    """Reactiva una API Key revocada."""
    api_key = ApiKey.query.get_or_404(key_id)
    if api_key.is_expired:
        flash('No se puede reactivar una clave expirada. Crea una nueva.', 'danger')
    else:
        api_key.is_active = True
        db.session.commit()
        flash(f'API Key "{api_key.name}" reactivada.', 'success')
    return redirect(url_for('api_keys.manage_keys'))


@bp.route('/delete/<int:key_id>', methods=['POST'])
@login_required
@admin_required
def delete_key(key_id):
    """Elimina permanentemente una API Key."""
    api_key = ApiKey.query.get_or_404(key_id)
    name = api_key.name
    db.session.delete(api_key)
    db.session.commit()
    flash(f'API Key "{name}" eliminada permanentemente.', 'info')
    return redirect(url_for('api_keys.manage_keys'))


# ─── ENDPOINT DE EJEMPLO: API REST protegida por API Key ────────────────────

@bp.route('/api/v1/status', methods=['GET'])
@api_key_required
def api_status():
    """
    Endpoint de ejemplo protegido por API Key.
    GET /api-keys/api/v1/status
    Header: Authorization: Bearer gps_XXXXX
    """
    return jsonify({
        'status': 'ok',
        'service': 'GPS Comercial API',
        'version': '1.0',
        'timestamp': datetime.now(timezone.utc).isoformat() + 'Z',
    })


@bp.route('/api/v1/devices', methods=['GET'])
@api_key_required
def api_devices():
    """
    Lista dispositivos Traccar vía API Key.
    GET /api-keys/api/v1/devices
    Header: Authorization: Bearer gps_XXXXX
    """
    from app.traccar import get_devices
    try:
        devices = get_devices()
        if devices is None:
            return jsonify({'status': 'error', 'message': 'No se pudo conectar a Traccar'}), 500
        return jsonify({
            'status': 'ok',
            'count': len(devices),
            'devices': [{'id': d['id'], 'name': d['name'], 'status': d.get('status')} for d in devices],
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
