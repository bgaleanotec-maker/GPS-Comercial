# Ruta: GPS_Comercial/app/analytics/proximity.py
"""Reproceso en segundo plano de visitas por proximidad de trayectoria.

Para cada (usuario con GPS, dia), baja las posiciones de Traccar y registra una
ProximityVisit por cada aliado cuya ubicacion quedo a <= radius_m de la trayectoria
(maximo 1 por dia por aliado). Se ejecuta incrementalmente hacia atras en el tiempo
desde el worker de fondo, sin bloquear la web.
"""
import logging
from datetime import datetime, timedelta, date

import pytz

from app import db
from app.models import ProximityVisit, Ally, User, Visit, Setting

logger = logging.getLogger(__name__)
COLOMBIA_TZ = pytz.timezone('America/Bogota')

DEFAULT_RADIUS_M = 1000
MAX_LOOKBACK_DAYS = 365   # cuanto historico reprocesar como maximo

CURSOR_KEY = 'proximity_cursor_date'
START_KEY = 'proximity_start_date'
RADIUS_KEY = 'proximity_radius_m'


def _get(key, default=None):
    s = Setting.query.filter_by(key=key).first()
    return s.value if s else default


def _set(key, val):
    s = Setting.query.filter_by(key=key).first()
    if s:
        s.value = str(val)
    else:
        db.session.add(Setting(key=key, value=str(val)))
    db.session.commit()


def get_radius():
    try:
        return int(_get(RADIUS_KEY, DEFAULT_RADIUS_M))
    except (TypeError, ValueError):
        return DEFAULT_RADIUS_M


def _detect_day_for_user(user, day, allies, radius_m):
    """Detecta y guarda proximity visits de un usuario en un dia. Devuelve nº nuevas."""
    from app.traccar import get_device_positions
    from app.utils import haversine_distance

    day_start = COLOMBIA_TZ.localize(datetime.combine(day, datetime.min.time()))
    day_end = day_start + timedelta(days=1)
    positions = get_device_positions(user.traccar_device_id, day_start, day_end)
    if not positions:
        return 0

    seen = {}  # ally_id -> primer fixTime (UTC naive/aware)
    for p in positions:
        lat, lon = p.get('latitude'), p.get('longitude')
        if lat is None or lon is None:
            continue
        ft = p.get('fixTime')
        if not ft:
            continue
        try:
            t = datetime.fromisoformat(str(ft).replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            continue
        for a in allies:
            if a.id in seen:
                continue
            if haversine_distance(lat, lon, a.latitude, a.longitude) <= radius_m:
                seen[a.id] = t

    new = 0
    for aid, ft in seen.items():
        existing = ProximityVisit.query.filter_by(user_id=user.id, ally_id=aid, visit_date=day).first()
        if existing:
            existing.first_time = ft
            existing.radius_m = radius_m
        else:
            db.session.add(ProximityVisit(user_id=user.id, ally_id=aid, visit_date=day,
                                          first_time=ft, radius_m=radius_m))
            new += 1
    db.session.commit()
    return new


def detect_and_store_day(app, day, radius_m=None):
    """Procesa un dia para todos los usuarios con dispositivo."""
    with app.app_context():
        radius_m = radius_m or get_radius()
        allies = [a for a in Ally.query.all() if a.latitude is not None and a.longitude is not None]
        if not allies:
            return 0
        users = User.query.filter(User.traccar_device_id.isnot(None)).all()
        total = 0
        for u in users:
            try:
                total += _detect_day_for_user(u, day, allies, radius_m)
            except Exception as e:
                logger.debug("Proximity dia %s user %s: %s", day, u.username, e)
                db.session.rollback()
        return total


def _ensure_bounds(app):
    """Fija start_date (primera actividad, acotada) si no existe."""
    if _get(START_KEY):
        return
    today = datetime.now(COLOMBIA_TZ).date()
    fv = Visit.query.order_by(Visit.timestamp.asc()).first()
    if fv:
        t = fv.timestamp
        if t.tzinfo is None:
            t = pytz.utc.localize(t)
        sd = t.astimezone(COLOMBIA_TZ).date()
    else:
        sd = today
    floor = today - timedelta(days=MAX_LOOKBACK_DAYS)
    if sd < floor:
        sd = floor
    _set(START_KEY, sd.isoformat())


def backfill_proximity_step(app, max_days=2):
    """Procesa hacia atras algunos dias historicos. Devuelve nº dias procesados
    (o -1 si ya termino el historico)."""
    with app.app_context():
        _ensure_bounds(app)
        today = datetime.now(COLOMBIA_TZ).date()
        start_date = date.fromisoformat(_get(START_KEY))
        cur_s = _get(CURSOR_KEY)
        cur = date.fromisoformat(cur_s) if cur_s else today

        done = 0
        for _ in range(max_days):
            if cur < start_date:
                return -1
            detect_and_store_day(app, cur)
            done += 1
            cur = cur - timedelta(days=1)
            _set(CURSOR_KEY, cur.isoformat())
        return done


def refresh_proximity_today(app):
    """Reprocesa el dia de hoy (la trayectoria sigue creciendo durante el dia)."""
    today = datetime.now(COLOMBIA_TZ).date()
    return detect_and_store_day(app, today)


def proximity_progress():
    """Devuelve (dias_procesados, dias_totales) del backfill historico."""
    start_s = _get(START_KEY)
    if not start_s:
        return 0, 0
    today = datetime.now(COLOMBIA_TZ).date()
    start_date = date.fromisoformat(start_s)
    total = (today - start_date).days + 1
    cur_s = _get(CURSOR_KEY)
    cur = date.fromisoformat(cur_s) if cur_s else today
    done = (today - cur).days
    if done < 0:
        done = 0
    if done > total:
        done = total
    return done, total
