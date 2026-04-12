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
            if not User.query.filter_by(username='admin').first():
                admin = User(username='admin', full_name='Administrador',
                             email='admin@gps.com', role='admin')
                admin.set_password(os.environ.get('ADMIN_INITIAL_PASSWORD', 'admin123'))
                db.session.add(admin)
                logger.info("Admin creado")

            # Settings por defecto
            defaults = {
                'start_time': '06:00', 'end_time': '20:00',
                'active_days': '1,2,3,4,5', 'visit_interval': '60',
                'report_time': '08:00', 'report_recipients': '',
                'sst_recipients': '', 'whatsapp_enabled': 'false',
                'ultramsg_instance_id': '', 'ultramsg_token': '',
                'whatsapp_report_time': '08:00',
            }
            for key, value in defaults.items():
                if not Setting.query.filter_by(key=key).first():
                    db.session.add(Setting(key=key, value=value))

            db.session.commit()
    except Exception as e:
        logger.warning("Error inicializando BD (puede ser normal en build): %s", e)


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
