# Ruta: GPS_Comercial/app/analytics/commercial.py
"""Analitica comercial especializada (solo admin).

Incluye:
- Visitas en radio de aliados (solo L-V), con filtro de aliados y de permanencia (>=N min).
- Recorrido por dia via Traccar (daily summary): total, media y mediana dia/semana/mes,
  dias activos vs inactivos, excluyendo dias anomalos (> umbral km/dia, ej. viajes largos).
- Diversidad de aliados por ejecutivo (visita al mismo o a varios).
- Vista de detalle con mapa del recorrido (Leaflet) y desglose completo.
"""
import statistics
from collections import defaultdict
from datetime import datetime, timedelta

import pytz
from flask import render_template, request, abort, jsonify
from flask_login import login_required, current_user

from app.analytics import bp
from app.analytics.routes import _count_working_days, _count_months, COLOMBIA_TZ
from app.models import Visit, Ally, User
from app.traccar import get_devices, get_device_summary_daily, get_device_route

DEFAULT_ANOMALY_KM = 600
DEFAULT_MIN_DWELL = 0


def _fmt_dt_local(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    return dt.astimezone(COLOMBIA_TZ)


def _daily_km_map(daily_rows):
    """Convierte filas daily de Traccar en {fecha_local: km}."""
    out = defaultdict(float)
    for r in daily_rows or []:
        st = r.get('startTime') or r.get('startDate') or r.get('date')
        if not st:
            continue
        try:
            d = datetime.fromisoformat(str(st).replace('Z', '+00:00')).astimezone(COLOMBIA_TZ).date()
        except (ValueError, AttributeError):
            continue
        out[d] += (r.get('distance') or 0) / 1000.0
    return out


def _distance_stats(daily_rows, start_d, end_d, anomaly_km):
    """Estadisticas de recorrido sobre dias laborales (L-V), excluyendo dias anomalos."""
    day_km = _daily_km_map(daily_rows)

    series = []          # km por dia laboral (incluye 0 en dias sin recorrido)
    excluded = []        # dias anomalos excluidos
    weekly = defaultdict(float)
    monthly = defaultdict(float)

    d = start_d
    while d <= end_d:
        if d.weekday() < 5:  # solo L-V
            km = day_km.get(d, 0.0)
            if km > anomaly_km:
                excluded.append({'date': d.strftime('%d/%m/%Y'), 'km': round(km, 1)})
            else:
                series.append(km)
                iso = d.isocalendar()
                weekly[(iso[0], iso[1])] += km
                monthly[(d.year, d.month)] += km
        d += timedelta(days=1)

    if not series:
        return None

    total_km = sum(series)
    active_days = sum(1 for k in series if k > 0.1)
    inactive_days = len(series) - active_days
    working_days = len(series)
    weeks = max(1, len(weekly))
    months = max(1, len(monthly))

    week_sums = list(weekly.values())
    month_sums = list(monthly.values())

    return {
        'total': round(total_km, 1),
        'mean_day': round(total_km / working_days, 1) if working_days else 0,
        'median_day': round(statistics.median(series), 1),
        'mean_week': round(total_km / weeks, 1),
        'median_week': round(statistics.median(week_sums), 1) if week_sums else 0,
        'mean_month': round(total_km / months, 1),
        'median_month': round(statistics.median(month_sums), 1) if month_sums else 0,
        'active_days': active_days,
        'inactive_days': inactive_days,
        'working_days': working_days,
        'excluded': excluded,
    }


def _visit_passes(v, min_dwell):
    """True si la visita cuenta segun el filtro de permanencia."""
    if min_dwell <= 0:
        return True, False
    if v.dwell_minutes is None:
        return False, True   # pendiente de calculo
    return (v.dwell_minutes >= min_dwell), False


@bp.route('/commercial')
@login_required
def commercial_analytics():
    if current_user.role != 'admin':
        abort(403)

    now = datetime.now(COLOMBIA_TZ)
    today = now.date()

    first_visit = Visit.query.order_by(Visit.timestamp.asc()).first()
    default_start = _fmt_dt_local(first_visit.timestamp).date() if first_visit else today.replace(day=1)

    start_str = request.args.get('start_date', default_start.strftime('%Y-%m-%d'))
    end_str = request.args.get('end_date', today.strftime('%Y-%m-%d'))
    include_distance = request.args.get('include_distance', '1') == '1'
    selected_ids = request.args.getlist('employee_ids', type=int)
    selected_allies = request.args.getlist('ally_ids', type=int)
    min_dwell = request.args.get('min_dwell', DEFAULT_MIN_DWELL, type=int)
    anomaly_km = request.args.get('anomaly_km', DEFAULT_ANOMALY_KM, type=int)

    try:
        start_d = datetime.strptime(start_str, '%Y-%m-%d').date()
        end_d = datetime.strptime(end_str, '%Y-%m-%d').date()
    except ValueError:
        start_d, end_d = default_start, today

    start_utc = COLOMBIA_TZ.localize(datetime.combine(start_d, datetime.min.time())).astimezone(pytz.utc)
    end_utc = COLOMBIA_TZ.localize(datetime.combine(end_d + timedelta(days=1), datetime.min.time())).astimezone(pytz.utc)

    working_days = _count_working_days(start_d, end_d)
    months = _count_months(start_d, end_d)

    all_execs = User.query.filter_by(role='empleado').order_by(User.full_name).all()
    exec_by_id = {u.id: u for u in all_execs}
    target_execs = [exec_by_id[i] for i in selected_ids if i in exec_by_id] if selected_ids else all_execs
    target_ids = {u.id for u in target_execs}
    ally_filter = set(selected_allies) if selected_allies else None

    devices = get_devices() if include_distance else None
    device_map = {d['id']: d['name'] for d in devices} if devices else {}

    visits = Visit.query.filter(
        Visit.timestamp >= start_utc,
        Visit.timestamp < end_utc,
    ).all()

    per_exec = defaultdict(lambda: {'total': 0, 'gps': 0, 'manual': 0, 'allies': defaultdict(int),
                                    'last': None, 'pending': 0})
    ally_counter = defaultdict(int)
    total_weekday_visits = 0
    total_pending = 0

    for v in visits:
        local = _fmt_dt_local(v.timestamp)
        if local.weekday() >= 5:
            continue
        if v.user_id not in target_ids:
            continue
        if ally_filter and v.ally_id not in ally_filter:
            continue
        ok, pending = _visit_passes(v, min_dwell)
        if pending:
            per_exec[v.user_id]['pending'] += 1
            total_pending += 1
        if not ok:
            continue
        e = per_exec[v.user_id]
        e['total'] += 1
        if v.is_manual:
            e['manual'] += 1
        else:
            e['gps'] += 1
        if v.ally_id:
            e['allies'][v.ally_id] += 1
            ally_counter[v.ally_id] += 1
        if e['last'] is None or v.timestamp > e['last']:
            e['last'] = v.timestamp
        total_weekday_visits += 1

    rows = []
    for u in target_execs:
        d = per_exec.get(u.id)
        total = d['total'] if d else 0
        allies_dict = d['allies'] if d else {}
        distinct_allies = len(allies_dict)
        top_ally_share = round(max(allies_dict.values()) / total * 100, 0) if total and allies_dict else 0
        dstats = None
        if include_distance and u.traccar_device_id:
            daily = get_device_summary_daily(u.traccar_device_id, start_utc, end_utc)
            dstats = _distance_stats(daily, start_d, end_d, anomaly_km)
        rows.append({
            'id': u.id,
            'name': u.full_name or u.username,
            'categoria': u.categoria or '',
            'device': device_map.get(u.traccar_device_id, 'Sin dispositivo') if include_distance else None,
            'has_device': bool(u.traccar_device_id),
            'total': total,
            'gps': d['gps'] if d else 0,
            'manual': d['manual'] if d else 0,
            'pending': d['pending'] if d else 0,
            'allies': distinct_allies,
            'top_ally_share': top_ally_share,
            'avg_day': round(total / working_days, 2) if working_days else 0,
            'avg_month': round(total / months, 1),
            'km_total': dstats['total'] if dstats else None,
            'km_day': dstats['mean_day'] if dstats else None,
            'km_med_day': dstats['median_day'] if dstats else None,
            'km_week': dstats['mean_week'] if dstats else None,
            'km_month': dstats['mean_month'] if dstats else None,
            'active_days': dstats['active_days'] if dstats else None,
            'inactive_days': dstats['inactive_days'] if dstats else None,
            'last': _fmt_dt_local(d['last']).strftime('%d/%m/%Y') if (d and d['last']) else '—',
        })

    ranking_visitas = sorted(rows, key=lambda r: r['total'], reverse=True)
    ranking_recorrido = sorted([r for r in rows if r['km_total'] is not None],
                               key=lambda r: r['km_total'], reverse=True)

    allies_map = {a.id: a for a in Ally.query.all()}
    ally_rows = []
    for aid, cnt in ally_counter.items():
        a = allies_map.get(aid)
        if not a:
            continue
        unique_execs = sum(1 for e in per_exec.values() if aid in e['allies'])
        ally_rows.append({
            'name': a.name, 'category': a.category or '', 'filial': a.filial or '',
            'visits': cnt, 'execs': unique_execs,
            'avg_day': round(cnt / working_days, 2) if working_days else 0,
            'avg_month': round(cnt / months, 1),
        })
    ally_rows.sort(key=lambda r: r['visits'], reverse=True)

    active_execs = sum(1 for r in rows if r['total'] > 0)
    kpis = {
        'total_visitas': total_weekday_visits,
        'avg_dia': round(total_weekday_visits / working_days, 1) if working_days else 0,
        'avg_mes': round(total_weekday_visits / months, 1),
        'working_days': working_days,
        'months': months,
        'ejecutivos': len(target_execs),
        'activos': active_execs,
        'aliados_visitados': len(ally_counter),
        'aliados_total': len(allies_map),
        'gps_auto': sum(r['gps'] for r in rows),
        'manual': sum(r['manual'] for r in rows),
        'pending': total_pending,
    }

    # Progreso del backfill de permanencia
    from app.analytics.dwell import dwell_progress
    pend_all, total_all = dwell_progress()

    return render_template(
        'analytics/commercial.html',
        title='Analitica Comercial',
        kpis=kpis, rows=rows,
        ranking_visitas=ranking_visitas, ranking_recorrido=ranking_recorrido,
        ally_rows=ally_rows, all_execs=all_execs, all_allies_list=sorted(allies_map.values(), key=lambda a: a.name),
        selected_ids=selected_ids, selected_allies=selected_allies,
        min_dwell=min_dwell, anomaly_km=anomaly_km,
        start_date=start_str, end_date=end_str, include_distance=include_distance,
        default_start=default_start.strftime('%Y-%m-%d'), today=today.strftime('%Y-%m-%d'),
        month_start=today.replace(day=1).strftime('%Y-%m-%d'),
        two_months_start=(today.replace(day=1) - timedelta(days=1)).replace(day=1).strftime('%Y-%m-%d'),
        dwell_pending=pend_all, dwell_total=total_all,
    )


@bp.route('/commercial/executive/<int:user_id>')
@login_required
def commercial_executive_detail(user_id):
    if current_user.role != 'admin':
        abort(403)

    u = User.query.get_or_404(user_id)
    now = datetime.now(COLOMBIA_TZ)
    today = now.date()

    first_visit = Visit.query.filter_by(user_id=u.id).order_by(Visit.timestamp.asc()).first()
    default_start = _fmt_dt_local(first_visit.timestamp).date() if first_visit else today.replace(day=1)

    start_str = request.args.get('start_date', default_start.strftime('%Y-%m-%d'))
    end_str = request.args.get('end_date', today.strftime('%Y-%m-%d'))
    min_dwell = request.args.get('min_dwell', DEFAULT_MIN_DWELL, type=int)
    anomaly_km = request.args.get('anomaly_km', DEFAULT_ANOMALY_KM, type=int)
    map_date_str = request.args.get('map_date', '')

    try:
        start_d = datetime.strptime(start_str, '%Y-%m-%d').date()
        end_d = datetime.strptime(end_str, '%Y-%m-%d').date()
    except ValueError:
        start_d, end_d = default_start, today

    start_utc = COLOMBIA_TZ.localize(datetime.combine(start_d, datetime.min.time())).astimezone(pytz.utc)
    end_utc = COLOMBIA_TZ.localize(datetime.combine(end_d + timedelta(days=1), datetime.min.time())).astimezone(pytz.utc)

    working_days = _count_working_days(start_d, end_d)
    months = _count_months(start_d, end_d)

    visits = Visit.query.filter(
        Visit.user_id == u.id,
        Visit.timestamp >= start_utc,
        Visit.timestamp < end_utc,
    ).order_by(Visit.timestamp.desc()).all()

    allies_map = {a.id: a for a in Ally.query.all()}
    day_names = ['Lunes', 'Martes', 'Miercoles', 'Jueves', 'Viernes', 'Sabado', 'Domingo']

    per_ally = defaultdict(lambda: {'count': 0, 'dwell_sum': 0.0, 'dwell_n': 0})
    per_weekday = {i: 0 for i in range(7)}
    per_month = defaultdict(int)
    timeline = []
    weekday_total = gps_auto = manual = pending = 0
    active_dates = set()

    for v in visits:
        local = _fmt_dt_local(v.timestamp)
        wd = local.weekday()
        per_weekday[wd] += 1
        ok, is_pending = _visit_passes(v, min_dwell)
        if is_pending:
            pending += 1
        if wd < 5 and ok:
            weekday_total += 1
            active_dates.add(local.date())
            if v.ally_id:
                pa = per_ally[v.ally_id]
                pa['count'] += 1
                if v.dwell_minutes is not None:
                    pa['dwell_sum'] += v.dwell_minutes
                    pa['dwell_n'] += 1
            per_month[local.strftime('%Y-%m')] += 1
            if v.is_manual:
                manual += 1
            else:
                gps_auto += 1
        if len(timeline) < 100:
            a = allies_map.get(v.ally_id)
            hora = (v.start_time + (' - ' + v.end_time if v.end_time else '')) if v.start_time else local.strftime('%H:%M')
            timeline.append({
                'fecha': local.strftime('%d/%m/%Y'),
                'hora': hora,
                'ally': a.name if a else '—',
                'tipo': 'Manual' if v.is_manual else 'GPS',
                'categoria': v.category or '',
                'weekend': wd >= 5,
                'dwell': v.dwell_minutes,
                'obs': v.observations or '',
            })

    ally_rows = []
    max_ally = 0
    for aid, data in sorted(per_ally.items(), key=lambda kv: kv[1]['count'], reverse=True):
        a = allies_map.get(aid)
        if not a:
            continue
        max_ally = max(max_ally, data['count'])
        avg_dwell = round(data['dwell_sum'] / data['dwell_n'], 0) if data['dwell_n'] else None
        ally_rows.append({'name': a.name, 'category': a.category or '', 'visits': data['count'], 'avg_dwell': avg_dwell})

    weekday_rows = [{'name': day_names[i], 'count': per_weekday[i], 'laboral': i < 5} for i in range(7)]
    max_weekday = max(per_weekday.values()) if per_weekday else 0
    month_rows = [{'month': m, 'count': c} for m, c in sorted(per_month.items())]
    max_month = max((r['count'] for r in month_rows), default=0)

    # Recorrido: estadisticas por dia (mediana, activos/inactivos, anomalos)
    dstats = None
    daily = None
    if u.traccar_device_id:
        daily = get_device_summary_daily(u.traccar_device_id, start_utc, end_utc)
        dstats = _distance_stats(daily, start_d, end_d, anomaly_km)

    # Mapa: recorrido de un dia. Por defecto, el dia laboral mas reciente con visita.
    map_route = []
    map_date = None
    if u.traccar_device_id:
        if map_date_str:
            try:
                map_date = datetime.strptime(map_date_str, '%Y-%m-%d').date()
            except ValueError:
                map_date = None
        if map_date is None:
            if active_dates:
                map_date = max(active_dates)
            else:
                map_date = end_d
        m_start = COLOMBIA_TZ.localize(datetime.combine(map_date, datetime.min.time()))
        m_end = m_start + timedelta(days=1)
        route = get_device_route(u.traccar_device_id, m_start, m_end)
        if route:
            for p in route:
                lat, lon = p.get('latitude'), p.get('longitude')
                if lat is not None and lon is not None:
                    map_route.append({'latitude': lat, 'longitude': lon,
                                      'speed': round((p.get('speed') or 0) * 1.852, 0)})

    # Aliados del dia del mapa (para pintar marcadores)
    map_allies = [{'name': a.name, 'lat': a.latitude, 'lon': a.longitude, 'radius': a.radius}
                  for a in allies_map.values()]

    stats = {
        'total': weekday_total, 'gps': gps_auto, 'manual': manual, 'pending': pending,
        'allies': len(per_ally),
        'avg_day': round(weekday_total / working_days, 2) if working_days else 0,
        'avg_month': round(weekday_total / months, 1),
        'working_days': working_days, 'months': months,
        'active_days': len(active_dates),
        'repeat_ratio': round((weekday_total - len(per_ally)) / weekday_total * 100, 0) if weekday_total else 0,
    }

    return render_template(
        'analytics/commercial_detail.html',
        title='Detalle · ' + (u.full_name or u.username),
        user=u, stats=stats, dstats=dstats,
        ally_rows=ally_rows, max_ally=max_ally,
        weekday_rows=weekday_rows, max_weekday=max_weekday,
        month_rows=month_rows, max_month=max_month,
        timeline=timeline,
        map_route=map_route, map_allies=map_allies,
        map_date=map_date.strftime('%Y-%m-%d') if map_date else '',
        min_dwell=min_dwell, anomaly_km=anomaly_km,
        start_date=start_str, end_date=end_str,
        default_start=default_start.strftime('%Y-%m-%d'), today=today.strftime('%Y-%m-%d'),
        month_start=today.replace(day=1).strftime('%Y-%m-%d'),
        two_months_start=(today.replace(day=1) - timedelta(days=1)).replace(day=1).strftime('%Y-%m-%d'),
    )


@bp.route('/commercial/backfill-dwell', methods=['POST'])
@login_required
def commercial_backfill_dwell():
    """Dispara un lote de calculo de permanencia y devuelve el progreso. Solo admin."""
    if current_user.role != 'admin':
        abort(403)
    from flask import current_app
    from app.analytics.dwell import backfill_dwell_batch, dwell_progress
    processed = backfill_dwell_batch(current_app._get_current_object(), batch_size=120)
    pending, total = dwell_progress()
    return jsonify({'processed': processed, 'pending': pending, 'total': total,
                    'done': total - pending})
