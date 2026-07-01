# Ruta: SST/app/analytics/__init__.py
from flask import Blueprint

bp = Blueprint('analytics', __name__)

from app.analytics import routes
from app.analytics import commercial  # noqa: E402,F401  (registra rutas de analitica comercial)
