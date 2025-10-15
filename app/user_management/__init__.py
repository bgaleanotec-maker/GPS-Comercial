# Ruta: SST/app/user_management/__init__.py
from flask import Blueprint

# Se crea un nuevo Blueprint para la gestión de usuarios
bp = Blueprint('user_management', __name__)

# Se importan las rutas de este módulo para que se registren con el Blueprint
from app.user_management import routes

