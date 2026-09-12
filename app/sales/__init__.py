# Ruta: GPS_Comercial/app/sales/__init__.py
from flask import Blueprint

bp = Blueprint('sales', __name__)

from app.sales import routes  # noqa: E402,F401
