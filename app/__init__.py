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

# Convencion de nombres para restricciones de BD (compatibilidad Alembic + SQLite)
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


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Validar configuracion
    Config.validate()

    # Carpeta de subidas
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])

    app.jinja_env.globals['pytz'] = pytz
    app.jinja_env.globals['datetime'] = datetime

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

    # Iniciar worker de fondo (deteccion automatica de visitas + reportes)
    if os.environ.get('ENABLE_BACKGROUND_WORKER', 'true').lower() != 'false':
        try:
            from app.background import start_background_worker
            start_background_worker(app)
        except Exception as e:
            logger.warning("No se pudo iniciar el background worker: %s", e)

    return app

from app import models
