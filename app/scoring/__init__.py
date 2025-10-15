# Ruta: SST/app/scoring/__init__.py
from flask import Blueprint

bp = Blueprint('scoring', __name__)

from app.scoring import routes