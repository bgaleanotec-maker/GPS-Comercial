# Ruta: GPS_Comercial/config.py
import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))


class Config(object):
    SECRET_KEY = os.environ.get('SECRET_KEY')

    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'app.db')

    if SQLALCHEMY_DATABASE_URI and SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace("postgres://", "postgresql://", 1)

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    TEMPLATES_AUTO_RELOAD = True
    UPLOAD_FOLDER = os.path.join(basedir, 'app/static/uploads')

    # Traccar - URL no es secreto, puede tener fallback
    TRACCAR_URL = os.environ.get('TRACCAR_URL') or 'http://64.227.85.213:8082'
    TRACCAR_USER = os.environ.get('TRACCAR_USER')
    TRACCAR_PASSWORD = os.environ.get('TRACCAR_PASSWORD')

    # Email
    SENDGRID_API_KEY = os.environ.get('SENDGRID_API_KEY')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER') or 'bgaleanotec@gmail.com'
    SST_EMAIL_RECIPIENT = os.environ.get('SST_EMAIL_RECIPIENT') or 'bgaleanotec@gmail.com'

    @staticmethod
    def validate():
        """Verifica que las variables de entorno requeridas esten configuradas."""
        required = ['SECRET_KEY', 'TRACCAR_USER', 'TRACCAR_PASSWORD']
        missing = [k for k in required if not os.environ.get(k)]
        if missing:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                f"Variables de entorno faltantes: {', '.join(missing)}. "
                f"Usando valores por defecto para desarrollo local."
            )
            # En desarrollo local, usar defaults seguros
            if not os.environ.get('SECRET_KEY'):
                Config.SECRET_KEY = 'dev-secret-key-change-in-production'
            if not os.environ.get('TRACCAR_USER'):
                Config.TRACCAR_USER = 'admin'
            if not os.environ.get('TRACCAR_PASSWORD'):
                Config.TRACCAR_PASSWORD = 'admin'
