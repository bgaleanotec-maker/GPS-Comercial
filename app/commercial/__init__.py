# Ruta: SST/app/commercial/__init__.py
from flask import Blueprint

# Creamos un nuevo Blueprint llamado 'commercial'
bp = Blueprint('commercial', __name__)

# Importamos las rutas de este módulo para que se registren
from app.commercial import routes

