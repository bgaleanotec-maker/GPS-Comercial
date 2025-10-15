# Ruta: SST/app/__init__.py
import os
from flask import Flask
from config import Config
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from sqlalchemy import MetaData
import pytz
from datetime import datetime

# --- INICIO: Corrección para Migraciones con SQLite ---
# Se define una convención de nombres para las restricciones de la base de datos
# para evitar errores con Alembic y SQLite.
naming_convention = {
    "ix": 'ix_%(column_0_label)s',
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}

# Se crea el objeto MetaData con la convención de nombres
metadata = MetaData(naming_convention=naming_convention)
# Se pasa el objeto MetaData al inicializador de SQLAlchemy con el nombre de argumento correcto
db = SQLAlchemy(metadata=metadata)
# --- FIN: Corrección ---

login = LoginManager()
login.login_view = 'auth.login'
migrate = Migrate()

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Asegurarse de que la carpeta de subidas exista
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])

    app.jinja_env.globals['pytz'] = pytz
    app.jinja_env.globals['datetime'] = datetime

    db.init_app(app)
    login.init_app(app)
    migrate.init_app(app, db) # Se pasa el objeto db a migrate

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

    # --- NUEVO BLUEPRINT DE GESTIÓN DE USUARIOS ---
    from app.user_management import bp as user_management_bp
    app.register_blueprint(user_management_bp, url_prefix='/users')
    # --- FIN ---

    return app

from app import models
