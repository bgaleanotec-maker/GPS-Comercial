# Ruta: SST/app/traccar.py
import requests
from flask import current_app
from datetime import datetime, time
import pytz

def _get_traccar_session():
    """Helper function to get a session with Traccar credentials."""
    session = requests.Session()
    session.auth = (
        current_app.config['TRACCAR_USER'],
        current_app.config['TRACCAR_PASSWORD']
    )
    return session

def get_devices():
    """Se conecta a la API de Traccar y obtiene una lista de todos los dispositivos."""
    base_url = current_app.config['TRACCAR_URL']
    session = _get_traccar_session()
    try:
        response = session.get(f"{base_url}/api/devices")
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error de conexión con Traccar (get_devices): {e}")
        return None

def get_device_by_id(device_id):
    """Obtiene los detalles de un dispositivo específico por su ID."""
    base_url = current_app.config['TRACCAR_URL']
    session = _get_traccar_session()
    try:
        response = session.get(f"{base_url}/api/devices")
        response.raise_for_status()
        devices = response.json()
        for device in devices:
            if device['id'] == device_id:
                return device
        return None
    except requests.exceptions.RequestException as e:
        print(f"Error de conexión con Traccar (get_device_by_id): {e}")
        return None

def get_latest_position(device_id):
    """Obtiene la última posición registrada para un dispositivo específico."""
    base_url = current_app.config['TRACCAR_URL']
    session = _get_traccar_session()
    try:
        response = session.get(f"{base_url}/api/positions", params={'deviceId': device_id})
        response.raise_for_status()
        positions = response.json()
        return positions[0] if positions else None
    except requests.exceptions.RequestException as e:
        print(f"Error de conexión con Traccar (get_latest_position): {e}")
        return None

def get_device_summary(device_id, from_time, to_time):
    """
    Obtiene un reporte de resumen para un dispositivo en un rango de fechas.
    """
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
        response = session.get(f"{base_url}/api/reports/summary", params=params)
        response.raise_for_status()
        # Verificamos que la respuesta no esté vacía antes de intentar decodificarla como JSON
        if response.text:
            report_data = response.json()
            return report_data[0] if report_data else None
        return None # Si la respuesta está vacía, no hay reporte
    except requests.exceptions.RequestException as e:
        print(f"Error al obtener el reporte de Traccar para el dispositivo {device_id}: {e}")
        return None

def get_device_route(device_id, from_time, to_time):
    """
    Obtiene el reporte de ruta (lista de puntos) para un dispositivo.
    """
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
        response = session.get(f"{base_url}/api/reports/route", params=params)
        response.raise_for_status()

        # Si la respuesta tiene contenido, la procesamos. Si no, devolvemos una lista vacía.
        if response.text:
            return response.json()
        else:
            return [] # Devolvemos una lista vacía en lugar de fallar

    except requests.exceptions.RequestException as e:
        print(f"Error al obtener la ruta de Traccar para el dispositivo {device_id}: {e}")
        return None # Devolvemos None en caso de un error de conexión real
