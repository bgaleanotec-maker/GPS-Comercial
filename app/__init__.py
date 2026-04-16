# Ruta: GPS_Comercial/app/__init__.py
import os
import logging
from flask import Flask
from config import Config
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from sqlalchemy import MetaData
import pytz
from datetime import datetime

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

# Convencion de nombres para restricciones de BD
naming_convention = {
    "ix": 'ix_%(column_0_label)s',
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}

metadata = MetaData(naming_convention=naming_convention)
db = SQLAlchemy(metadata=metadata)

login = LoginManager()
login.login_view = 'auth.login'
migrate = Migrate()


def _init_database(app):
    """Crea tablas faltantes y datos iniciales. Seguro para correr multiples veces."""
    try:
        with app.app_context():
            db.create_all()
            # Agregar columnas nuevas a tablas existentes (PostgreSQL no lo hace con create_all)
            from app.db_utils import auto_add_missing_columns
            auto_add_missing_columns(db, app)
            from app.models import User, Setting

            # Admin por defecto
            admin_user = User.query.filter_by(username='admin').first()
            if not admin_user:
                admin_user = User(username='admin', full_name='Administrador',
                             email='admin@gps.com', role='admin')
                admin_user.set_password(os.environ.get('ADMIN_INITIAL_PASSWORD', 'admin123'))
                db.session.add(admin_user)
                logger.info("Admin creado")
            # Asegurar que admin tenga telefono configurado
            if admin_user and not admin_user.phone_number:
                admin_user.phone_number = '573222699322'

            # Settings por defecto
            defaults = {
                'start_time': '06:00', 'end_time': '20:00',
                'active_days': '1,2,3,4,5', 'visit_interval': '60',
                'report_time': '08:00', 'report_recipients': '',
                'sst_recipients': '',
                'whatsapp_enabled': 'true',
                'ultramsg_instance_id': os.environ.get('ULTRAMSG_INSTANCE_ID', 'instance154562'),
                'ultramsg_token': os.environ.get('ULTRAMSG_TOKEN', 'gxcg5k06jjz7fmi0'),
                'whatsapp_report_time': '18:00',
                'emergency_whatsapp_enabled': 'true',
                'admin_whatsapp_number': '573222699322',
            }
            # Keys que siempre deben actualizarse desde env/defaults si estan vacios
            force_update_keys = {
                'ultramsg_instance_id', 'ultramsg_token',
                'whatsapp_enabled', 'emergency_whatsapp_enabled',
                'admin_whatsapp_number',
            }
            for key, value in defaults.items():
                existing = Setting.query.filter_by(key=key).first()
                if not existing:
                    db.session.add(Setting(key=key, value=value))
                elif key in force_update_keys and not existing.value and value:
                    existing.value = value
                    logger.info("Setting '%s' actualizado: %s", key, value[:20] if len(value) > 20 else value)

            db.session.commit()

            # Seed contratistas si no existen
            _seed_contractors(app)
    except Exception as e:
        logger.warning("Error inicializando BD (puede ser normal en build): %s", e)


def _seed_contractors(app):
    """Crea los contratistas/aliados iniciales si no existen."""
    from app.models import Ally
    contractors = [
        # Bogota (filial Vanti)
        {'name': 'Multintegral Bogota', 'address': 'Calle 19a # 69 11, Montevideo, Bogota',
         'latitude': 4.6351, 'longitude': -74.1108, 'category': 'Contratista', 'filial': 'Vanti', 'radius': 100},
        {'name': 'Connect', 'address': 'Cra 14 # 97 63, Bogota',
         'latitude': 4.6912, 'longitude': -74.0484, 'category': 'Contratista', 'filial': 'Vanti', 'radius': 100},
        {'name': 'Aprogas', 'address': 'Cra 68h # 78 64, Bogota',
         'latitude': 4.6984, 'longitude': -74.0937, 'category': 'Contratista', 'filial': 'Vanti', 'radius': 100},
        {'name': 'Romegas', 'address': 'Diagonal 52a Sur # 54b 02, Bogota',
         'latitude': 4.5874, 'longitude': -74.1437, 'category': 'Contratista', 'filial': 'Vanti', 'radius': 100},
        # Cundinamarca / Boyaca (filial Cundi)
        {'name': 'Romegas Chia', 'address': 'Calle 29 # 6 126, Chia',
         'latitude': 4.8636, 'longitude': -74.0540, 'category': 'Contratista', 'filial': 'Cundi', 'radius': 100},
        {'name': 'Connect Funza', 'address': 'Cra 23 # 12c 39, Funza',
         'latitude': 4.7174, 'longitude': -74.2112, 'category': 'Contratista', 'filial': 'Cundi', 'radius': 100},
        {'name': 'Multintegral Boyaca', 'address': 'Cra 9 # 24 64, Tunja',
         'latitude': 5.5353, 'longitude': -73.3622, 'category': 'Contratista', 'filial': 'Cundi', 'radius': 150},
        {'name': 'Aprogas Boyaca', 'address': 'Cra 16 # 12 10, Duitama',
         'latitude': 5.8264, 'longitude': -73.0331, 'category': 'Contratista', 'filial': 'Cundi', 'radius': 150},
    ]
    added = 0
    for c in contractors:
        existing = Ally.query.filter_by(name=c['name']).first()
        if not existing:
            ally = Ally(**c)
            db.session.add(ally)
            added += 1
    if added:
        db.session.commit()
        logger.info("Contratistas seed: %d nuevos creados.", added)


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    Config.validate()

    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])

    app.jinja_env.globals['pytz'] = pytz
    app.jinja_env.globals['datetime'] = datetime

    from flask_wtf.csrf import generate_csrf
    app.jinja_env.globals['csrf_token'] = generate_csrf

    db.init_app(app)
    login.init_app(app)
    migrate.init_app(app, db)

    # Registro de Blueprints
    from app.main import bp as main_bp
    app.register_blueprint(main_bp)

    from app.auth import bp as auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')

    from app.scoring import bp as scoring_bp
    app.register_blueprint(scoring_bp, url_prefix='/scoring')

    from app.commercial import bp as commercial_bp
    app.register_blueprint(commercial_bp, url_prefix='/commercial')

    from app.analytics import bp as analytics_bp
    app.register_blueprint(analytics_bp, url_prefix='/analytics')

    from app.user_management import bp as user_management_bp
    app.register_blueprint(user_management_bp, url_prefix='/users')

    from app.api_keys import bp as api_keys_bp
    app.register_blueprint(api_keys_bp, url_prefix='/api-keys')

    from app.schedule import bp as schedule_bp
    app.register_blueprint(schedule_bp, url_prefix='/schedule')

    # Forzar cambio de contrasena en cualquier ruta protegida
    @app.before_request
    def check_password_change():
        from flask_login import current_user
        from flask import request, redirect, url_for
        if current_user.is_authenticated and getattr(current_user, 'must_change_password', False):
            allowed = ('auth.change_password', 'auth.logout', 'static')
            if request.endpoint and request.endpoint not in allowed:
                return redirect(url_for('auth.change_password'))

    # Crear/actualizar tablas e inicializar datos
    _init_database(app)

    # Iniciar worker de fondo
    if os.environ.get('ENABLE_BACKGROUND_WORKER', 'true').lower() != 'false':
        try:
            from app.background import start_background_worker
            start_background_worker(app)
        except Exception as e:
            logger.warning("No se pudo iniciar el background worker: %s", e)

    return app

from app import models
