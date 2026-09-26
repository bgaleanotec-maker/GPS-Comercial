# Ruta: GPS_Comercial/app/sales/routing.py
"""Motor de rutas del Modulo de Ventas ("modo Uber").

- Geocodificacion de direcciones (Nominatim/OpenStreetMap) con contexto de ciudad
  parametrizable (por defecto Bogota, Colombia).
- Tiempos y trazado reales por via (OSRM publico) con respaldo por distancia
  haversine y velocidad urbana parametrizable si OSRM no responde.
- Optimizacion del orden de visitas (vecino mas cercano + mejora 2-opt).
- Plan del dia: por cada parada, minutos de desplazamiento, hora estimada de
  llegada, tiempo de visita (parametrizable, tope por defecto 60 min) y salida.
"""
import logging
from datetime import datetime, timedelta

import pytz
import requests

from app import db
from app.models import Setting
from app.utils import haversine_distance

logger = logging.getLogger(__name__)
COLOMBIA_TZ = pytz.timezone('America/Bogota')

NOMINATIM_URL = 'https://nominatim.openstreetmap.org/search'
OSRM_URL = 'https://router.project-osrm.org'
UA = {'User-Agent': 'VantiGo-Ventas/1.0 (contacto: bgaleanotec@gmail.com)'}

# Parametros (tabla Setting) y valores por defecto
PARAM_DEFAULTS = {
    'sales_city_context': 'Bogota, Colombia',   # se agrega a la direccion al geocodificar
    'sales_visit_minutes': '60',                 # tiempo estimado de visita (tope)
    'sales_avg_speed_kmh': '22',                 # velocidad urbana para el respaldo
    'sales_deviation_m': '300',                  # metros fuera de la ruta para avisar desvio (tipo Uber)
    'sales_road_factor': '1.35',                 # distancia por via vs linea recta
}


def get_param(key):
    s = Setting.query.filter_by(key=key).first()
    val = s.value if s and s.value not in (None, '') else PARAM_DEFAULTS[key]
    return val


def set_param(key, value):
    s = Setting.query.filter_by(key=key).first()
    if s:
        s.value = str(value)
    else:
        db.session.add(Setting(key=key, value=str(value)))


def get_params():
    return {
        'city': get_param('sales_city_context'),
        'visit_minutes': int(float(get_param('sales_visit_minutes'))),
        'avg_speed_kmh': float(get_param('sales_avg_speed_kmh')),
        'road_factor': float(get_param('sales_road_factor')),
        'deviation_m': int(float(get_param('sales_deviation_m'))),
    }


# ------------------------------------------------------------
# Geocodificacion
# ------------------------------------------------------------
def geocode_address(address, city_context=None):
    """Devuelve (lat, lng) o None. Respeta el limite de Nominatim (1 req/s)."""
    if not address:
        return None
    city_context = city_context or get_param('sales_city_context')
    query = f"{address}, {city_context}" if city_context.lower() not in address.lower() else address
    try:
        r = requests.get(NOMINATIM_URL, params={'q': query, 'format': 'json', 'limit': 1},
                         headers=UA, timeout=8)
        r.raise_for_status()
        data = r.json()
        if data:
            return float(data[0]['lat']), float(data[0]['lon'])
    except Exception as e:
        logger.debug('Geocode fallo para "%s": %s', address, e)
    return None


def geocode_pending_deals(app, max_items=4):
    """Geocodifica en segundo plano los negocios sin coordenadas (max_items por
    ciclo, ~1 req/s). Marca intentos para no reintentar infinitamente."""
    import time
    from app.models import SalesDeal
    with app.app_context():
        pend = (SalesDeal.query
                .filter(SalesDeal.latitude.is_(None), SalesDeal.address.isnot(None),
                        SalesDeal.geocode_attempts < 3)
                .order_by(SalesDeal.created_at.desc()).limit(max_items).all())
        if not pend:
            return 0
        city = get_param('sales_city_context')
        done = 0
        for d in pend:
            res = geocode_address(d.address, city)
            d.geocode_attempts = (d.geocode_attempts or 0) + 1
            if res:
                d.latitude, d.longitude = res
                d.geocoded_at = datetime.utcnow()
                done += 1
            db.session.commit()
            time.sleep(1.1)  # cortesia Nominatim
        return done


# ------------------------------------------------------------
# OSRM (rutas reales) con respaldo
# ------------------------------------------------------------
def _fmt_coords(points):
    return ';'.join(f"{lng},{lat}" for lat, lng in points)


def osrm_table(points):
    """Matriz de duraciones (segundos) entre puntos [(lat,lng)...] o None."""
    if len(points) < 2:
        return None
    try:
        r = requests.get(f"{OSRM_URL}/table/v1/driving/{_fmt_coords(points)}",
                         params={'annotations': 'duration'}, headers=UA, timeout=8)
        r.raise_for_status()
        data = r.json()
        if data.get('code') == 'Ok':
            return data['durations']
    except Exception as e:
        logger.debug('OSRM table fallo: %s', e)
    return None


def osrm_route(points):
    """Trazado y duracion real de la ruta en el orden dado. Devuelve dict o None."""
    if len(points) < 2:
        return None
    try:
        r = requests.get(f"{OSRM_URL}/route/v1/driving/{_fmt_coords(points)}",
                         params={'overview': 'full', 'geometries': 'geojson', 'steps': 'false'},
                         headers=UA, timeout=8)
        r.raise_for_status()
        data = r.json()
        if data.get('code') == 'Ok' and data.get('routes'):
            route = data['routes'][0]
            geom = [[c[1], c[0]] for c in route['geometry']['coordinates']]  # a [lat,lng]
            legs = [{'duration_s': leg['duration'], 'distance_m': leg['distance']} for leg in route['legs']]
            return {'geometry': geom, 'legs': legs,
                    'duration_s': route['duration'], 'distance_m': route['distance']}
    except Exception as e:
        logger.debug('OSRM route fallo: %s', e)
    return None


def _fallback_matrix(points, params):
    """Duraciones estimadas por haversine x factor via / velocidad media."""
    speed_ms = max(5.0, params['avg_speed_kmh']) * 1000 / 3600.0
    n = len(points)
    m = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j:
                dist = haversine_distance(points[i][0], points[i][1], points[j][0], points[j][1]) * params['road_factor']
                m[i][j] = dist / speed_ms
    return m


# ------------------------------------------------------------
# Optimizacion del orden (TSP abierto: origen fijo, sin regreso)
# ------------------------------------------------------------
def optimize_order(matrix, n_stops):
    """matrix incluye el origen en indice 0. Devuelve orden de paradas (indices 1..n)."""
    if n_stops == 0:
        return []
    unvisited = set(range(1, n_stops + 1))
    order, cur = [], 0
    while unvisited:
        nxt = min(unvisited, key=lambda j: matrix[cur][j] if matrix[cur][j] is not None else 1e12)
        order.append(nxt)
        unvisited.remove(nxt)
        cur = nxt

    def cost(seq):
        total, prev = 0.0, 0
        for j in seq:
            total += matrix[prev][j] or 0
            prev = j
        return total

    # 2-opt
    improved = True
    while improved and len(order) > 2:
        improved = False
        for i in range(len(order) - 1):
            for k in range(i + 1, len(order)):
                cand = order[:i] + order[i:k + 1][::-1] + order[k + 1:]
                if cost(cand) + 1e-6 < cost(order):
                    order = cand
                    improved = True
    return order


# ------------------------------------------------------------
# Plan del dia
# ------------------------------------------------------------
def build_plan(origin, deals, start_time=None, params=None):
    """origin=(lat,lng); deals = negocios con coordenadas. Devuelve dict con paradas
    ordenadas, tiempos y trazado."""
    params = params or get_params()
    now = start_time or datetime.now(COLOMBIA_TZ)
    stops = [d for d in deals if d.has_coords]
    if not stops:
        return {'stops': [], 'geometry': [], 'total_travel_min': 0, 'total_visit_min': 0,
                'end_time': now, 'source': 'none', 'sin_coords': len(deals)}

    points = [origin] + [(d.latitude, d.longitude) for d in stops]
    matrix = osrm_table(points) if len(points) <= 25 else None
    source = 'osrm'
    if not matrix:
        matrix = _fallback_matrix(points, params)
        source = 'estimado'

    order = optimize_order(matrix, len(stops))
    ordered_points = [origin] + [points[j] for j in order]

    # Trazado real y duraciones por tramo (si OSRM responde), si no, matriz
    route = osrm_route(ordered_points) if source == 'osrm' else None
    legs = route['legs'] if route else None
    geometry = route['geometry'] if route else ordered_points

    visit_min = params['visit_minutes']
    t = now
    prev = 0
    result_stops = []
    total_travel = 0.0
    for k, j in enumerate(order):
        leg_s = legs[k]['duration_s'] if legs else (matrix[prev][j] or 0)
        leg_min = max(1, round(leg_s / 60.0))
        dist_km = (legs[k]['distance_m'] / 1000.0) if legs else \
            haversine_distance(points[prev][0], points[prev][1], points[j][0], points[j][1]) * params['road_factor'] / 1000.0
        arrive = t + timedelta(minutes=leg_min)
        depart = arrive + timedelta(minutes=visit_min)
        d = stops[j - 1]
        result_stops.append({
            'order': k + 1, 'deal_id': d.id, 'client': d.client_name,
            'address': d.address or '', 'phone': d.phone or '', 'origen': d.origen or '',
            'status': d.status, 'lat': d.latitude, 'lng': d.longitude,
            'travel_min': leg_min, 'distance_km': round(dist_km, 1),
            'arrive': arrive.strftime('%H:%M'), 'depart': depart.strftime('%H:%M'),
            'visit_min': visit_min,
        })
        total_travel += leg_min
        t = depart
        prev = j

    return {
        'stops': result_stops, 'geometry': geometry, 'source': source,
        'total_travel_min': int(total_travel), 'total_visit_min': visit_min * len(result_stops),
        'end_time': t, 'sin_coords': len(deals) - len(stops),
    }
