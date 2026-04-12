from flask import Blueprint

bp = Blueprint('api_keys', __name__)

from app.api_keys import routes
