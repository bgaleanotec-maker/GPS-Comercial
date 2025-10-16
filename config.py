# Ruta: SST/config.py
import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))

class Config(object):
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'una-clave-secreta-muy-dificil'
    
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'app.db')
    
    if SQLALCHEMY_DATABASE_URI and SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace("postgres://", "postgresql://", 1)
    
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(basedir, 'app/static/uploads')

    TRACCAR_URL = os.environ.get('TRACCAR_URL') or 'http://68.183.171.26:8082'
    TRACCAR_USER = os.environ.get('TRACCAR_USER') or 'admin'
    TRACCAR_PASSWORD = os.environ.get('TRACCAR_PASSWORD') or 'admin'

    SENDGRID_API_KEY = os.environ.get('SENDGRID_API_KEY') or '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'
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER') or 'bgaleanotec@gmail.com'
    SST_EMAIL_RECIPIENT = os.environ.get('SST_EMAIL_RECIPIENT') or 'bgaleanotec@gmail.com'