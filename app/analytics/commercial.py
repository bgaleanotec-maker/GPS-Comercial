# Ruta: GPS_Comercial/app/analytics/commercial.py
"""Analitica comercial especializada (solo admin):
- Visitas dentro del radio de aliados (solo dias laborales Lun-Vie)
- Promedios de visitas por dia / mes
- Ranking de ejecutivos por recorrido (Traccar): medio diario/semanal/mensual
- Seleccion de ejecutivos y vista de detalle con desglose completo (zoom)
"""
from collections import defaultdict
from datetime import datetime, timedelta

import pytz
from flask import render_template, request, abort
from flask_login import login_required, current_user

from app.analytics import bp
from app.analytics.routes import _count_working_days, _count_months, COLOMBIA_TZ
from app.models import Visit, Ally, User
from app.traccar import get_devices, get_device_summary


def _fmt_dt_local(dt):
    """Convierte un datetime (posiblemente naive UTC) a hora local de Colombia."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    return dt.astimezone(COLOMBIA_TZ)


@bp.route('/commercial')
@login_required
def commercial_analytics():
    """Panel de analitica comercial. Solo admin."""
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

    try:
        start_d = datetime.strptime(start_str, '%Y-%m-%d').date()
        end_d = datetime.strptime(end_str, '%Y-%m-%d').date()
    except ValueError:
        start_d, end_d = default_start, today

    start_utc = COLOMBIA_TZ.localize(datetime.combine(start_d, datetime.min.time())).astimezone(pytz.utc)
    end_utc = COLOMBIA_TZ.localize(datetime.combine(end_d + timedelta(days=1), datetime.min.time())).astimezone(pytz.utc)

    working_days = _count_working_days(start_d, end_d)
    total_days = (end_d - start_d).days + 1
    weeks = max(1.0, total_days / 7.0)
    months = _count_months(start_d, end_d)

    all_execs = User.query.filter_by(role='empleado').order_by(User.full_name).all()
    exec_by_id = {u.id: u for u in all_execs}
    target_execs = [exec_by_id[i] for i in selected_ids if i in exec_by_id] if selected_ids else all_execs
    target_ids = {u.id for u in target_execs}

    devices = get_devices() if include_distance else None
    device_map = {d['id']: d['name'] for d in devices} if devices else {}

    visits = Visit.query.filter(
        Visit.timestamp >= start_utc,
        Visit.timestamp < end_utc,
    ).all()

    per_exec = defaultdict(lambda: {'total': 0, 'gps': 0, 'manual': 0, 'allies': set(), 'last': None})
    ally_counter = defaultdict(int)
    total_weekday_visits = 0

    for v in visits:
        local = _fmt_dt_local(v.timestamp)
        if local.weekday() >= 5:        # solo Lun-Vie
            continue
        if v.user_id not in target_ids:
            continue
        e = per_exec[v.user_id]
        e['total'] += 1
        if v.is_manual:
            e['manual'] += 1
        else:
            e['gps'] += 1
        if v.ally_id:
            e['allies'].add(v.ally_id)
            ally_counter[v.ally_id] += 1
        if e['last'] is None or v.timestamp > e['last']:
            e['last'] = v.timestamp
        total_weekday_visits += 1

    rows = []
    for u in target_execs:
        d = per_exec.get(u.id, {'total': 0, 'gps': 0, 'manual': 0, 'allies': set(), 'last': None})
        distance_km = None
        if include_distance and u.traccar_device_id:
            summary = get_device_summary(u.traccar_device_id, start_utc, end_utc)
            if summary and summary.get('distance') is not None:
                distance_km = round(summary['distance'] / 1000.0, 1)
        rows.append({
            'id': u.id,
            'name': u.full_name or u.username,
            'categoria': u.categoria or '',
            'device': device_map.get(u.traccar_device_id, 'Sin dispositivo') if include_distance else None,
            'has_device': bool(u.traccar_device_id),
            'total': d['total'], 'gps': d['gps'], 'manual': d['manual'],
            'allies': len(d['allies']),
            'avg_day': round(d['total'] / working_days, 2) if working_days else 0,
            'avg_month': round(d['total'] / months, 1),
            'km_total': distance_km,
            'km_day': round(distance_km / working_days, 1) if (distance_km is not None and working_days) else None,
            'km_week': round(distance_km / weeks, 1) if distance_km is not None else None,
            'km_month': round(distance_km / months, 1) if distance_km is not None else None,
            'last': _fmt_dt_local(d['last']).strftime('%d/%m/%Y') if d['last'] else '—',
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
        ally_rows.append({
            'name': a.name, 'category': a.category or '', 'filial': a.filial or '',
            'visits': cnt,
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
    }

    return render_template(
        'analytics/commercial.html',
        title='Analitica Comercial',
        kpis=kpis, rows=rows,
        ranking_visitas=ranking_visitas, ranking_recorrido=ranking_recorrido,
        ally_rows=ally_rows, all_execs=all_execs, selected_ids=selected_ids,
        start_date=start_str, end_date=end_str, include_distance=include_distance,
        default_start=default_start.strftime('%Y-%m-%d'), today=today.strftime('%Y-%m-%d'),
    )


@bp.route('/commercial/executive/<int:user_id>')
@login_required
def commercial_executive_detail(user_id):
    """Detalle (zoom) de un ejecutivo. Solo admin."""
    if current_user.role != 'admin':
        abort(403)

    u = User.query.get_or_404(user_id)
    now = datetime.now(COLOMBIA_TZ)
    today = now.date()

    first_visit = Visit.query.filter_by(user_id=u.id).order_by(Visit.timestamp.asc()).first()
    default_start = _fmt_dt_local(first_visit.timestamp).date() if first_visit else today.replace(day=1)

    start_str = request.args.get('start_date', default_start.strftime('%Y-%m-%d'))
    end_str = request.args.get('end_date', today.strftime('%Y-%m-%d'))
    try:
        start_d = datetime.strptime(start_str, '%Y-%m-%d').date()
        end_d = datetime.strptime(end_str, '%Y-%m-%d').date()
    except ValueError:
        start_d, end_d = default_start, today

    start_utc = COLOMBIA_TZ.localize(datetime.combine(start_d, datetime.min.time())).astimezone(pytz.utc)
    end_utc = COLOMBIA_TZ.localize(datetime.combine(end_d + timedelta(days=1), datetime.min.time())).astimezone(pytz.utc)

    working_days = _count_working_days(start_d, end_d)
    total_days = (end_d - start_d).days + 1
    weeks = max(1.0, total_days / 7.0)
    months = _count_months(start_d, end_d)

    visits = Visit.query.filter(
        Visit.user_id == u.id,
        Visit.timestamp >= start_utc,
        Visit.timestamp < end_utc,
    ).order_by(Visit.timestamp.desc()).all()

    allies_map = {a.id: a for a in Ally.query.all()}
    day_names = ['Lunes', 'Martes', 'Miercoles', 'Jueves', 'Viernes', 'Sabado', 'Domingo']

    per_ally = defaultdict(int)
    per_weekday = {i: 0 for i in range(7)}
    per_month = defaultdict(int)
    timeline = []
    weekday_total = 0
    gps_auto = manual = 0

    for v in visits:
        local = _fmt_dt_local(v.timestamp)
        wd = local.weekday()
        per_weekday[wd] += 1
        if wd < 5:
            weekday_total += 1
            if v.ally_id:
                per_ally[v.ally_id] += 1
            per_month[local.strftime('%Y-%m')] += 1
            if v.is_manual:
                manual += 1
            else:
                gps_auto += 1
        if len(timeline) < 80:
            a = allies_map.get(v.ally_id)
            hora = (v.start_time + (' - ' + v.end_time if v.end_time else '')) if v.start_time else local.strftime('%H:%M')
            timeline.append({
                'fecha': local.strftime('%d/%m/%Y'),
                'hora': hora,
                'ally': a.name if a else '—',
                'tipo': 'Manual' if v.is_manual else 'GPS',
                'categoria': v.category or '',
                'weekend': wd >= 5,
                'obs': v.observations or '',
            })

    ally_rows = []
    max_ally = 0
    for aid, cnt in sorted(per_ally.items(), key=lambda kv: kv[1], reverse=True):
        a = allies_map.get(aid)
        if not a:
            continue
        max_ally = max(max_ally, cnt)
        ally_rows.append({'name': a.name, 'category': a.category or '', 'visits': cnt})

    weekday_rows = [{'name': day_names[i], 'count': per_weekday[i], 'laboral': i < 5} for i in range(7)]
    max_weekday = max(per_weekday.values()) if per_weekday else 0

    month_rows = [{'month': m, 'count': c} for m, c in sorted(per_month.items())]
    max_month = max((r['count'] for r in month_rows), default=0)

    dist = {'total': None, 'day': None, 'week': None, 'month': None, 'avg_speed': None, 'max_speed': None}
    if u.traccar_device_id:
        summary = get_device_summary(u.traccar_device_id, start_utc, end_utc)
        if summary and summary.get('distance') is not None:
            km = summary['distance'] / 1000.0
            dist['total'] = round(km, 1)
            dist['day'] = round(km / working_days, 1) if working_days else None
            dist['week'] = round(km / weeks, 1)
            dist['month'] = round(km / months, 1)
            if summary.get('averageSpeed') is not None:
                dist['avg_speed'] = round(summary['averageSpeed'] * 1.852, 1)
            if summary.get('maxSpeed') is not None:
                dist['max_speed'] = round(summary['maxSpeed'] * 1.852, 1)

    stats = {
        'total': weekday_total, 'gps': gps_auto, 'manual': manual,
        'allies': len(per_ally),
        'avg_day': round(weekday_total / working_days, 2) if working_days else 0,
        'avg_month': round(weekday_total / months, 1),
        'working_days': working_days, 'months': months,
    }

    return render_template(
        'analytics/commercial_detail.html',
        title='Detalle · ' + (u.full_name or u.username),
        user=u, stats=stats, dist=dist,
        ally_rows=ally_rows, max_ally=max_ally,
        weekday_rows=weekday_rows, max_weekday=max_weekday,
        month_rows=month_rows, max_month=max_month,
        timeline=timeline,
        start_date=start_str, end_date=end_str,
        default_start=default_start.strftime('%Y-%m-%d'), today=today.strftime('%Y-%m-%d'),
    )
