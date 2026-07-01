# Ruta: GPS_Comercial/app/analytics/dwell.py
"""Calculo de permanencia (dwell time) de las visitas dentro del radio del aliado.

Una 'visita' en la tabla Visit solo indica que el GPS estuvo en el radio al menos
una vez ese dia. Para distinguir visitas reales (>=30 min) de pasadas rapidas,
calculamos cuantos minutos permanecio el dispositivo dentro del radio usando el
historial de posiciones de Traccar. El resultado se guarda en Visit.dwell_minutes.

El backfill corre de forma incremental en el worker de fondo para no bloquear la web.
"""
import logging
from datetime import datetime, timedelta

import pytz

from app import db
from app.models import Visit, Ally

logger = logging.getLogger(__name__)
COLOMBIA_TZ = pytz.timezone('America/Bogota')

# Hueco maximo entre puntos consecutivos para seguir contando permanencia (min).
# Si hay mas de esto sin señal, no se acumula ese tramo (evita inflar por apagados).
MAX_GAP_MIN = 20.0


def _dwell_minutes_for_ally(positions, ally):
    """Minutos que el dispositivo permanecio dentro del radio del aliado."""
    from app.utils import haversine_distance
    if not positions or ally is None:
        return 0.0

    pts = []
    for p in positions:
        try:
            t = datetime.fromisoformat(p['fixTime'].replace('Z', '+00:00'))
        except (KeyError, ValueError, AttributeError):
            continue
        lat, lon = p.get('latitude'), p.get('longitude')
        if lat is None or lon is None:
            continue
        pts.append((t, lat, lon))
    pts.sort(key=lambda x: x[0])

    total = 0.0
    for i in range(1, len(pts)):
        t0, la0, lo0 = pts[i - 1]
        t1, la1, lo1 = pts[i]
        d0 = haversine_distance(la0, lo0, ally.latitude, ally.longitude)
        d1 = haversine_distance(la1, lo1, ally.latitude, ally.longitude)
        if d0 <= ally.radius and d1 <= ally.radius:
            dt = (t1 - t0).total_seconds() / 60.0
            if 0 < dt <= MAX_GAP_MIN:
                total += dt
    return round(total, 1)


def _process_visits_group(device_id, day, visits, allies_map):
    """Calcula dwell para todas las visitas de un (dispositivo, dia) con 1 sola
    llamada a Traccar. Devuelve numero de visitas procesadas, o -1 si Traccar fallo."""
    from app.traccar import get_device_positions
    day_start = COLOMBIA_TZ.localize(datetime.combine(day, datetime.min.time()))
    day_end = day_start + timedelta(days=1)
    positions = get_device_positions(device_id, day_start, day_end)
    if positions is None:
        return -1  # error Traccar: no marcar, reintentar luego
    processed = 0
    for v in visits:
        ally = allies_map.get(v.ally_id)
        if not v.device_id or ally is None:
            v.dwell_minutes = 0.0
        else:
            v.dwell_minutes = _dwell_minutes_for_ally(positions, ally)
        processed += 1
    return processed


def _group_by_device_day(visits):
    groups = {}
    for v in visits:
        local = v.timestamp
        if local.tzinfo is None:
            local = pytz.utc.localize(local)
        local = local.astimezone(COLOMBIA_TZ)
        groups.setdefault((v.device_id, local.date()), []).append(v)
    return groups


def backfill_dwell_batch(app, batch_size=60):
    """Procesa un lote de visitas sin dwell calculado. Pensado para el worker."""
    with app.app_context():
        pending = (Visit.query
                   .filter(Visit.dwell_minutes.is_(None))
                   .order_by(Visit.timestamp.desc())
                   .limit(batch_size).all())
        if not pending:
            return 0
        allies_map = {a.id: a for a in Ally.query.all()}
        processed = 0
        for (device_id, day), visits in _group_by_device_day(pending).items():
            n = _process_visits_group(device_id, day, visits, allies_map)
            if n > 0:
                processed += n
                db.session.commit()
        return processed


def refresh_today_dwell(app):
    """Recalcula el dwell de las visitas de HOY (siguen acumulando durante el dia)."""
    with app.app_context():
        today = datetime.now(COLOMBIA_TZ).date()
        today_start = COLOMBIA_TZ.localize(datetime.combine(today, datetime.min.time())).astimezone(pytz.utc)
        todays = Visit.query.filter(Visit.timestamp >= today_start).all()
        if not todays:
            return 0
        allies_map = {a.id: a for a in Ally.query.all()}
        processed = 0
        for (device_id, day), visits in _group_by_device_day(todays).items():
            n = _process_visits_group(device_id, day, visits, allies_map)
            if n > 0:
                processed += n
                db.session.commit()
        return processed


def dwell_progress():
    """Devuelve (pendientes, total) de visitas para reportar avance del backfill."""
    total = Visit.query.count()
    pending = Visit.query.filter(Visit.dwell_minutes.is_(None)).count()
    return pending, total
