# Ruta: GPS_Comercial/app/traccar.py
"""Modulo centralizado para comunicacion con la API de Traccar."""

import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from flask import current_app
import pytz

logger = logging.getLogger(__name__)

TRACCAR_TIMEOUT = 10  # segundos

# Umbral de velocidad para clasificar modo de transporte (km/h)
WALKING_SPEED_THRESHOLD = 6.0  # <= 6 km/h = a pie
KNOTS_TO_KMH = 1.852


def _build_session(user, password):
    """Crea una sesion HTTP con retry y autenticacion."""
    session = requests.Session()
    session.auth = (user, password)
    retries = Retry(
        total=2,
        backoff_factor=0.5,
        status_forcelist=[500, 502, 503, 504]
    )
    session.mount('http://', HTTPAdapter(max_retries=retries))
    session.mount('https://', HTTPAdapter(max_retries=retries))
    return session


def _get_traccar_session():
    """Obtiene sesion con credenciales desde current_app (requiere app context)."""
    return _build_session(
        current_app.config['TRACCAR_USER'],
        current_app.config['TRACCAR_PASSWORD']
    )


def _get_traccar_session_for_app(app):
    """Obtiene sesion con credenciales desde un objeto app explicito (sin app context)."""
    return _build_session(
        app.config['TRACCAR_USER'],
        app.config['TRACCAR_PASSWORD']
    )


# ============================================================
# Funciones que requieren Flask app context (current_app)
# ============================================================

def get_devices():
    """Obtiene la lista de todos los dispositivos."""
    base_url = current_app.config['TRACCAR_URL']
    session = _get_traccar_session()
    try:
        response = session.get(f"{base_url}/api/devices", timeout=TRACCAR_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error("Error de conexion con Traccar (get_devices): %s", e)
        return None


def get_device_by_id(device_id):
    """Obtiene los detalles de un dispositivo especifico por su ID."""
    base_url = current_app.config['TRACCAR_URL']
    session = _get_traccar_session()
    try:
        response = session.get(f"{base_url}/api/devices", timeout=TRACCAR_TIMEOUT)
        response.raise_for_status()
        devices = response.json()
        for device in devices:
            if device['id'] == device_id:
                return device
        return None
    except requests.exceptions.RequestException as e:
        logger.error("Error de conexion con Traccar (get_device_by_id): %s", e)
        return None


def get_latest_position(device_id):
    """Obtiene la ultima posicion registrada para un dispositivo."""
    base_url = current_app.config['TRACCAR_URL']
    session = _get_traccar_session()
    try:
        response = session.get(
            f"{base_url}/api/positions",
            params={'deviceId': device_id, 'limit': 1},
            timeout=TRACCAR_TIMEOUT
        )
        response.raise_for_status()
        positions = response.json()
        return positions[0] if positions else None
    except requests.exceptions.RequestException as e:
        logger.error("Error de conexion con Traccar (get_latest_position): %s", e)
        return None


def get_device_positions(device_id, from_time, to_time):
    """
    Obtiene la lista de posiciones GPS crudas para un dispositivo en un rango de fechas.
    Util para evaluar infracciones y calcular distancias detalladas.
    """
    base_url = current_app.config['TRACCAR_URL']
    session = _get_traccar_session()
    params = {
        'deviceId': device_id,
        'from': from_time.astimezone(pytz.utc).isoformat(),
        'to': to_time.astimezone(pytz.utc).isoformat(),
    }
    try:
        response = session.get(
            f"{base_url}/api/positions",
            params=params,
            timeout=TRACCAR_TIMEOUT
        )
        response.raise_for_status()
        try:
            return response.json()
        except requests.exceptions.JSONDecodeError:
            logger.warning("Traccar devolvio respuesta no-JSON para dispositivo %s", device_id)
            return []
    except requests.exceptions.RequestException as e:
        logger.error("Error de conexion con Traccar (get_device_positions): %s", e)
        return None


def get_device_summary(device_id, from_time, to_time):
    """Obtiene un reporte de resumen para un dispositivo en un rango de fechas."""
    base_url = current_app.config['TRACCAR_URL']
    session = _get_traccar_session()

    from_utc = from_time.astimezone(pytz.utc).isoformat()
    to_utc = to_time.astimezone(pytz.utc).isoformat()

    params = {
        'deviceId': [device_id],
        'from': from_utc,
        'to': to_utc,
    }

    try:
        response = session.get(
            f"{base_url}/api/reports/summary",
            params=params,
            timeout=TRACCAR_TIMEOUT
        )
        response.raise_for_status()
        if response.text:
            report_data = response.json()
            return report_data[0] if report_data else None
        return None
    except requests.exceptions.RequestException as e:
        logger.error("Error al obtener reporte de Traccar para dispositivo %s: %s", device_id, e)
        return None


def get_device_route(device_id, from_time, to_time):
    """Obtiene el reporte de ruta (lista de puntos) para un dispositivo."""
    base_url = current_app.config['TRACCAR_URL']
    session = _get_traccar_session()

    from_utc = from_time.astimezone(pytz.utc).isoformat()
    to_utc = to_time.astimezone(pytz.utc).isoformat()

    params = {
        'deviceId': [device_id],
        'from': from_utc,
        'to': to_utc,
    }

    try:
        response = session.get(
            f"{base_url}/api/reports/route",
            params=params,
            timeout=TRACCAR_TIMEOUT
        )
        response.raise_for_status()
        if response.text:
            return response.json()
        return []
    except requests.exceptions.RequestException as e:
        logger.error("Error al obtener ruta de Traccar para dispositivo %s: %s", device_id, e)
        return None


# ============================================================
# Funciones para el background worker (reciben app explicito)
# ============================================================

def get_devices_for_app(app):
    """Obtiene dispositivos usando un objeto app explicito (para background worker)."""
    session = _get_traccar_session_for_app(app)
    base_url = app.config['TRACCAR_URL']
    try:
        response = session.get(f"{base_url}/api/devices", timeout=TRACCAR_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error("Error de conexion con Traccar (get_devices_for_app): %s", e)
        return None


def get_latest_position_for_app(app, device_id):
    """Obtiene ultima posicion usando un objeto app explicito (para background worker)."""
    session = _get_traccar_session_for_app(app)
    base_url = app.config['TRACCAR_URL']
    try:
        response = session.get(
            f"{base_url}/api/positions",
            params={'deviceId': device_id, 'limit': 1},
            timeout=TRACCAR_TIMEOUT
        )
        response.raise_for_status()
        positions = response.json()
        return positions[0] if positions else None
    except requests.exceptions.RequestException as e:
        logger.error("Error al obtener posicion para dispositivo %s: %s", device_id, e)
        return None


# ============================================================
# Utilidades de clasificacion de movimiento - BOGOTA
# ============================================================
# En Bogota los trancones hacen que vehiculos vayan a 3-4 km/h.
# No basta con velocidad instantanea. Usamos ventana de contexto:
# - Si en los ultimos N puntos hubo velocidad > 15 km/h, es vehiculo en trancon
# - Si la velocidad maxima reciente nunca pasa de 8 km/h, es a pie
# - Umbral puro solo aplica si no hay contexto

WALKING_MAX_SPEED = 8.0  # km/h - velocidad maxima realista caminando rapido
VEHICLE_INDICATOR_SPEED = 15.0  # km/h - si alguna vez llego a esto, es vehiculo
CONTEXT_WINDOW = 10  # ultimos N puntos para evaluar contexto


def calculate_route_distances(positions):
    """
    Calcula distancias recorridas separadas por modo de transporte.
    Logica adaptada para Bogota (trancones = vehiculo lento, no es caminar).

    Algoritmo:
    1. Analiza ventana de contexto de ultimos N puntos
    2. Si max velocidad en ventana > 15 km/h -> vehiculo (incluye trancon)
    3. Si max velocidad en ventana <= 8 km/h sostenido -> a pie
    4. Zona gris (8-15 km/h) -> vehiculo (en Bogota es mas probable trancon)
    """
    from app.utils import haversine_distance

    if not positions or len(positions) < 2:
        return {
            'walking_km': 0, 'vehicle_km': 0, 'total_km': 0,
            'max_speed_kmh': 0, 'avg_speed_kmh': 0,
        }

    walking_meters = 0.0
    vehicle_meters = 0.0
    max_speed_kmh = 0.0
    speed_readings = []

    # Pre-calcular velocidades en km/h
    speeds_kmh = [p.get('speed', 0) * KNOTS_TO_KMH for p in positions]

    for i in range(1, len(positions)):
        prev = positions[i - 1]
        curr = positions[i]

        distance = haversine_distance(
            prev.get('latitude', 0), prev.get('longitude', 0),
            curr.get('latitude', 0), curr.get('longitude', 0)
        )

        speed_kmh = speeds_kmh[i]

        if speed_kmh > max_speed_kmh:
            max_speed_kmh = speed_kmh

        if speed_kmh > 1.0:
            speed_readings.append(speed_kmh)

        # Ventana de contexto: max velocidad en ultimos N puntos
        window_start = max(0, i - CONTEXT_WINDOW)
        window_max = max(speeds_kmh[window_start:i + 1])

        # Tambien mirar adelante (si hay pico futuro cercano, es vehiculo arrancando)
        window_end = min(len(speeds_kmh), i + CONTEXT_WINDOW)
        forward_max = max(speeds_kmh[i:window_end]) if i < len(speeds_kmh) else 0

        # Clasificacion con contexto Bogota
        if window_max > VEHICLE_INDICATOR_SPEED or forward_max > VEHICLE_INDICATOR_SPEED:
            # Hubo o habra velocidad alta cercana -> vehiculo (trancon)
            vehicle_meters += distance
        elif window_max <= WALKING_MAX_SPEED and speed_kmh <= WALKING_MAX_SPEED:
            # Nunca paso de 8 km/h en la ventana -> caminando
            walking_meters += distance
        else:
            # Zona gris -> en Bogota = vehiculo en trancon
            vehicle_meters += distance

    avg_speed = sum(speed_readings) / len(speed_readings) if speed_readings else 0.0

    return {
        'walking_km': walking_meters / 1000,
        'vehicle_km': vehicle_meters / 1000,
        'total_km': (walking_meters + vehicle_meters) / 1000,
        'max_speed_kmh': max_speed_kmh,
        'avg_speed_kmh': avg_speed,
    }
