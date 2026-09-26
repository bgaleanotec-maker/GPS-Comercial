# Ruta: GPS_Comercial/app/sales/routes.py
"""Modulo Ventas (rol 'venta').

- Tablero del vendedor: negocios asignados (dia/semana/mes), marcar Ganado /
  Perdido / En Cotizacion, efectividad, ventas por dia y mes, origen de la venta,
  km recorridos y visitas del dia con hora inicio/fin y duracion.
- Gestion (admin/lider): precarga de negocios desde Excel (formato ciclo de
  ventas), asignacion diaria/semanal/mensual a vendedores y pipeline por vendedor.
"""
import logging
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, date

import pytz
from flask import render_template, request, flash, redirect, url_for, abort
from flask_login import login_required, current_user

from app import db
from app.models import SalesDeal, User, ProximityVisit, Ally
from app.sales import bp

logger = logging.getLogger(__name__)
COLOMBIA_TZ = pytz.timezone('America/Bogota')

DEAL_STATUSES = ('asignado', 'en_cotizacion', 'ganado', 'perdido')


def _norm_header(h):
    """Normaliza un encabezado de Excel: minusculas, sin acentos ni espacios extras."""
    if h is None:
        return ''
    s = str(h).strip().lower()
    s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    return ' '.join(s.split())


def _parse_any_date(v):
    """Acepta datetime, date o textos '25.04.2025' / '2025-04-25' / '25/04/2025'."""
    if v is None or v == '' or v == '#':
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ('%d.%m.%Y', '%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _map_status(v):
    s = _norm_header(v)
    if s.startswith('ganad'):
        return 'ganado'
    if s.startswith('perdid'):
        return 'perdido'
    if 'cotiz' in s:
        return 'en_cotizacion'
    return 'asignado'


def _clean(v, maxlen=None):
    if v is None or v == '#':
        return None
    s = str(v).strip()
    if not s or s == '#':
        return None
    return s[:maxlen] if maxlen else s


def _fmt_local(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    return dt.astimezone(COLOMBIA_TZ)


def _parse_client_time(value):
    """ISO 8601 enviado por el celular -> datetime UTC (None si no es valido)."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = COLOMBIA_TZ.localize(dt)
    return dt.astimezone(pytz.utc)


def _sellers_query():
    return User.query.filter_by(role='venta').order_by(User.full_name)


def _import_precarga(file_storage, created_by_id):
    """Importa el Excel de precarga (formato ciclo de ventas). Devuelve (nuevos, saltados, errores)."""
    import openpyxl
    wb = openpyxl.load_workbook(file_storage, data_only=True)
    ws = wb.worksheets[0]

    rows = ws.iter_rows(values_only=True)
    try:
        headers = [_norm_header(h) for h in next(rows)]
    except StopIteration:
        return 0, 0, ['El archivo esta vacio.']

    def col(row, *names):
        """Valor de la primera columna cuyo encabezado contenga alguno de los nombres."""
        for name in names:
            for i, h in enumerate(headers):
                if h == name or h.startswith(name):
                    return row[i] if i < len(row) else None
        return None

    # Vendedores para asignacion opcional por columna 'vendedor'/'usuario'
    sellers = {u.username.lower(): u.id for u in User.query.filter_by(role='venta').all()}
    for u in User.query.filter_by(role='venta').all():
        if u.full_name:
            sellers[_norm_header(u.full_name)] = u.id

    nuevos = saltados = 0
    errores = []
    today = datetime.now(COLOMBIA_TZ).date()

    for idx, row in enumerate(rows, start=2):
        if row is None or all(v in (None, '', '#') for v in row):
            continue
        try:
            client_name = _clean(col(row, 'cliente'), 200)
            opportunity_id = _clean(col(row, 'id oportunidad'), 50)
            client_number = _clean(col(row, 'numero de cliente', 'n de cliente'), 50)
            if not client_name and not opportunity_id:
                continue

            # Evitar duplicados por ID de oportunidad
            if opportunity_id and SalesDeal.query.filter_by(opportunity_id=opportunity_id).first():
                saltados += 1
                continue

            demanda = _norm_header(col(row, 'demanda espontanea')) in ('si', 'x', 'true', '1')
            origen = _clean(col(row, 'origen'), 100)
            if demanda:
                origen = 'Demanda'
            elif not origen:
                origen = 'Dispersa'

            deal = SalesDeal(
                opportunity_id=opportunity_id,
                client_number=client_number,
                client_name=client_name or ('Cliente ' + (client_number or '')),
                address=_clean(col(row, 'direccion'), 300),
                phone=_clean(col(row, 'telefono movil', 'telefono fijo'), 50),
                campaign=_clean(col(row, 'campana'), 200),
                market=_clean(col(row, 'mercado'), 100),
                sales_org=_clean(col(row, 'organizacion de ventas'), 150),
                origen=origen,
                status=_map_status(col(row, 'estado de ciclo de vida', 'estado')),
                status_reason=_clean(col(row, 'motivo del estado', 'motivo'), 300),
                start_date=_parse_any_date(col(row, 'fecha de inicio')),
                close_date=_parse_any_date(col(row, 'fecha de cierre')),
                notes=_clean(col(row, 'notas')),
                created_by=created_by_id,
            )

            # Estados finales de la precarga conservan su fecha de cierre
            if deal.status in ('ganado', 'perdido') and deal.close_date:
                deal.status_date = datetime.combine(deal.close_date, datetime.min.time())

            # Asignacion opcional por columna 'vendedor' / 'usuario asignado'
            seller_v = _norm_header(col(row, 'vendedor', 'usuario asignado', 'asignado a'))
            if seller_v and seller_v in sellers:
                deal.assigned_to = sellers[seller_v]
                deal.assigned_date = today

            db.session.add(deal)
            nuevos += 1
        except Exception as e:
            errores.append(f'Fila {idx}: {e}')
            if len(errores) >= 10:
                errores.append('(demasiados errores, se detiene el detalle)')
                break

    db.session.commit()
    return nuevos, saltados, errores


def _period_range(period, today):
    if period == 'semana':
        start = today - timedelta(days=today.weekday())
        return start, start + timedelta(days=6)
    if period == 'mes':
        start = today.replace(day=1)
        nxt = (start + timedelta(days=32)).replace(day=1)
        return start, nxt - timedelta(days=1)
    if period == 'todo':
        return date(2000, 1, 1), today
    return today, today  # dia


def _seller_stats(user, start_d, end_d):
    """KPIs del vendedor en el rango: negocios, efectividad, ventas, visitas y km."""
    deals = SalesDeal.query.filter(
        SalesDeal.assigned_to == user.id,
        SalesDeal.assigned_date.isnot(None),
        SalesDeal.assigned_date >= start_d,
        SalesDeal.assigned_date <= end_d,
    ).order_by(SalesDeal.status, SalesDeal.client_name).all()

    total = len(deals)
    ganados = sum(1 for d in deals if d.status == 'ganado')
    perdidos = sum(1 for d in deals if d.status == 'perdido')
    cotizacion = sum(1 for d in deals if d.status == 'en_cotizacion')
    pendientes = total - ganados - perdidos - cotizacion
    efectividad = round(ganados / total * 100, 1) if total else 0

    # Ventas (ganados por fecha de estado) por dia y por mes dentro del rango
    ventas_dia = defaultdict(int)
    ventas_mes = defaultdict(int)
    origen_counter = defaultdict(int)
    won = SalesDeal.query.filter(
        SalesDeal.assigned_to == user.id,
        SalesDeal.status == 'ganado',
        SalesDeal.status_date.isnot(None),
    ).all()
    for d in won:
        fd = d.status_date.date() if isinstance(d.status_date, datetime) else d.status_date
        if start_d <= fd <= end_d:
            ventas_dia[fd] += 1
            ventas_mes[fd.strftime('%Y-%m')] += 1
            origen_counter[d.origen or 'Sin origen'] += 1

    today = datetime.now(COLOMBIA_TZ).date()
    ventas_hoy = ventas_dia.get(today, 0)
    ventas_mes_actual = ventas_mes.get(today.strftime('%Y-%m'), 0)

    # Visitas (proximidad) en el rango: # por dia, # por cliente, inicio/fin/duracion
    pvisits = ProximityVisit.query.filter(
        ProximityVisit.user_id == user.id,
        ProximityVisit.visit_date >= start_d,
        ProximityVisit.visit_date <= end_d,
    ).order_by(ProximityVisit.visit_date.desc()).all()
    allies_map = {a.id: a for a in Ally.query.all()}

    visitas_total = len(pvisits)
    dias_con_visita = len({v.visit_date for v in pvisits})
    visitas_x_dia = round(visitas_total / dias_con_visita, 1) if dias_con_visita else 0
    por_cliente = defaultdict(lambda: {'count': 0, 'dur': 0.0})
    detalle_visitas = []
    for v in pvisits:
        a = allies_map.get(v.ally_id)
        nombre = a.name if a else 'Punto'
        por_cliente[nombre]['count'] += 1
        por_cliente[nombre]['dur'] += v.duration_minutes or 0
        if len(detalle_visitas) < 60:
            ini = _fmt_local(v.first_time)
            fin = _fmt_local(v.last_time)
            detalle_visitas.append({
                'fecha': v.visit_date.strftime('%d/%m/%Y'),
                'cliente': nombre,
                'inicio': ini.strftime('%H:%M') if ini else '—',
                'fin': fin.strftime('%H:%M') if fin else '—',
                'duracion': int(v.duration_minutes or 0),
            })
    visitas_cliente = sorted(
        [{'cliente': k, 'count': c['count'], 'dur_prom': round(c['dur'] / c['count'], 0) if c['count'] else 0}
         for k, c in por_cliente.items()], key=lambda x: x['count'], reverse=True)

    # Km recorridos (reporte agregado de Traccar, liviano)
    km = None
    if user.traccar_device_id:
        from app.main.routes import _summary_distance_m
        start_dt = COLOMBIA_TZ.localize(datetime.combine(start_d, datetime.min.time()))
        end_dt = COLOMBIA_TZ.localize(datetime.combine(end_d + timedelta(days=1), datetime.min.time()))
        km = round(_summary_distance_m(user.traccar_device_id, start_dt, min(end_dt, datetime.now(COLOMBIA_TZ))) / 1000.0, 1)

    return {
        'deals': deals, 'total': total, 'ganados': ganados, 'perdidos': perdidos,
        'cotizacion': cotizacion, 'pendientes': pendientes, 'efectividad': efectividad,
        'ventas_hoy': ventas_hoy, 'ventas_mes': ventas_mes_actual,
        'ventas_por_dia': sorted(ventas_dia.items()),
        'ventas_por_mes': sorted(ventas_mes.items()),
        'origen': sorted(origen_counter.items(), key=lambda kv: kv[1], reverse=True),
        'visitas_total': visitas_total, 'visitas_x_dia': visitas_x_dia,
        'dias_con_visita': dias_con_visita,
        'visitas_cliente': visitas_cliente, 'detalle_visitas': detalle_visitas,
        'km': km,
    }


# ============================================================
# TABLERO DEL VENDEDOR
# ============================================================
@bp.route('/board')
@login_required
def board():
    """Tablero del vendedor. Admin/lider pueden ver el de cualquier vendedor con ?user_id."""
    if current_user.role == 'venta':
        seller = current_user
    elif current_user.role in ('admin', 'lider'):
        uid = request.args.get('user_id', type=int)
        seller = db.session.get(User, uid) if uid else _sellers_query().first()
        if seller is None:
            flash('Aun no hay usuarios con rol Venta. Crealos en Gestionar Usuarios.', 'warning')
            return redirect(url_for('sales.manage'))
    else:
        abort(403)

    period = request.args.get('period', 'dia')
    if period not in ('dia', 'semana', 'mes', 'todo'):
        period = 'dia'
    today = datetime.now(COLOMBIA_TZ).date()
    start_d, end_d = _period_range(period, today)

    stats = _seller_stats(seller, start_d, end_d)
    sellers = _sellers_query().all() if current_user.role in ('admin', 'lider') else []

    return render_template('sales/board.html', title='Mis Negocios',
                           seller=seller, stats=stats, period=period,
                           start_d=start_d, end_d=end_d, sellers=sellers)


@bp.route('/deal/<int:deal_id>/status', methods=['POST'])
@login_required
def set_deal_status(deal_id):
    """Marcar un negocio como Ganado / Perdido / En Cotizacion (con motivo)."""
    deal = SalesDeal.query.get_or_404(deal_id)
    if current_user.role == 'venta' and deal.assigned_to != current_user.id:
        abort(403)
    if current_user.role not in ('venta', 'admin', 'lider'):
        abort(403)

    new_status = request.form.get('status')
    if new_status not in DEAL_STATUSES:
        flash('Estado invalido.', 'danger')
        return redirect(request.form.get('next') or url_for('sales.board'))

    deal.status = new_status
    deal.status_reason = (request.form.get('reason') or '').strip() or deal.status_reason
    deal.status_date = datetime.now(pytz.utc)
    db.session.commit()
    flash(f'Negocio "{deal.client_name}" marcado como {deal.status_display}.', 'success')
    return redirect(request.form.get('next') or url_for('sales.board'))


# ============================================================
# GESTION (ADMIN / LIDER): PRECARGA Y ASIGNACION
# ============================================================
@bp.route('/manage', methods=['GET', 'POST'])
@login_required
def manage():
    if current_user.role not in ('admin', 'lider'):
        abort(403)

    # Subida de precarga Excel
    if request.method == 'POST' and 'precarga' in request.files:
        f = request.files['precarga']
        if not f or not f.filename:
            flash('Selecciona un archivo .xlsx.', 'danger')
            return redirect(url_for('sales.manage'))
        if not f.filename.lower().endswith(('.xlsx', '.xlsm')):
            flash('El archivo debe ser Excel (.xlsx).', 'danger')
            return redirect(url_for('sales.manage'))
        try:
            nuevos, saltados, errores = _import_precarga(f, current_user.id)
            msg = f'Precarga procesada: {nuevos} negocio(s) nuevo(s), {saltados} ya existian.'
            flash(msg, 'success')
            for e in errores[:5]:
                flash(e, 'warning')
        except Exception as e:
            logger.exception('Error importando precarga')
            flash(f'No se pudo procesar el archivo: {e}', 'danger')
        return redirect(url_for('sales.manage'))

    # Filtros del listado
    status_f = request.args.get('status', 'all')
    seller_f = request.args.get('seller_id', type=int)
    q = SalesDeal.query
    if status_f == 'sin_asignar':
        q = q.filter(SalesDeal.assigned_to.is_(None))
    elif status_f in DEAL_STATUSES:
        q = q.filter_by(status=status_f)
    if seller_f:
        q = q.filter_by(assigned_to=seller_f)
    deals = q.order_by(SalesDeal.created_at.desc()).limit(400).all()

    sellers = _sellers_query().all()

    # Resumen por vendedor (efectividad global)
    resumen = []
    for s in sellers:
        sd = SalesDeal.query.filter_by(assigned_to=s.id).all()
        t = len(sd)
        g = sum(1 for d in sd if d.status == 'ganado')
        resumen.append({
            'seller': s, 'total': t, 'ganados': g,
            'perdidos': sum(1 for d in sd if d.status == 'perdido'),
            'cotizacion': sum(1 for d in sd if d.status == 'en_cotizacion'),
            'efectividad': round(g / t * 100, 1) if t else 0,
        })

    totales = {
        'total': SalesDeal.query.count(),
        'sin_asignar': SalesDeal.query.filter(SalesDeal.assigned_to.is_(None)).count(),
        'ganados': SalesDeal.query.filter_by(status='ganado').count(),
        'perdidos': SalesDeal.query.filter_by(status='perdido').count(),
        'cotizacion': SalesDeal.query.filter_by(status='en_cotizacion').count(),
    }

    from app.sales.routing import get_params as _gp
    return render_template('sales/manage.html', title='Gestion de Ventas',
                           deals=deals, sellers=sellers, resumen=resumen,
                           totales=totales, status_f=status_f, seller_f=seller_f,
                           params=_gp(),
                           today=datetime.now(COLOMBIA_TZ).date().strftime('%Y-%m-%d'))


@bp.route('/assign', methods=['POST'])
@login_required
def assign_deals():
    """Asignar negocios seleccionados a un vendedor (diaria/semanal/mensual)."""
    if current_user.role not in ('admin', 'lider'):
        abort(403)

    deal_ids = request.form.getlist('deal_ids', type=int)
    seller_id = request.form.get('seller_id', type=int)
    period = request.form.get('assignment_period', 'diaria')
    date_str = request.form.get('assigned_date', '')

    seller = db.session.get(User, seller_id) if seller_id else None
    if not deal_ids or seller is None or seller.role != 'venta':
        flash('Selecciona al menos un negocio y un vendedor (rol Venta).', 'danger')
        return redirect(url_for('sales.manage'))

    try:
        assigned_date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else datetime.now(COLOMBIA_TZ).date()
    except ValueError:
        assigned_date = datetime.now(COLOMBIA_TZ).date()
    if period not in ('diaria', 'semanal', 'mensual'):
        period = 'diaria'

    count = 0
    for did in deal_ids:
        deal = db.session.get(SalesDeal, did)
        if deal:
            deal.assigned_to = seller.id
            deal.assigned_date = assigned_date
            deal.assignment_period = period
            if deal.status not in ('ganado', 'perdido'):
                deal.status = deal.status if deal.status == 'en_cotizacion' else 'asignado'
            count += 1
    db.session.commit()
    flash(f'{count} negocio(s) asignado(s) a {seller.full_name or seller.username} ({period}).', 'success')
    return redirect(url_for('sales.manage'))


# ============================================================
# MODO UBER: JORNADA (RELOJ), RUTA OPTIMA, DEMANDA DISPERSA, MONITOREO EN VIVO
# ============================================================
from flask import jsonify, Response
from app.models import WorkShift, DealPhoto
from app.sales.routing import build_plan, get_params, set_param, PARAM_DEFAULTS

BOGOTA_CENTER = (4.6533, -74.0836)
AVATAR_COLORS = ['#6366f1', '#10b981', '#f59e0b', '#ec4899', '#06b6d4', '#8b5cf6', '#ef4444', '#14b8a6']


def _avatar(user):
    name = (user.full_name or user.username or '?').strip()
    parts = [p for p in name.split() if p]
    initials = (parts[0][0] + (parts[1][0] if len(parts) > 1 else '')).upper() if parts else '?'
    return {'initials': initials, 'color': AVATAR_COLORS[user.id % len(AVATAR_COLORS)]}


def _today():
    return datetime.now(COLOMBIA_TZ).date()


def _shift_today(user_id, create=False):
    sh = WorkShift.query.filter_by(user_id=user_id, shift_date=_today()).first()
    if sh is None and create:
        sh = WorkShift(user_id=user_id, shift_date=_today())
        db.session.add(sh)
    return sh


def _shift_json(sh):
    if not sh:
        return {'status': 'sin_iniciar', 'start': None, 'end': None, 'worked_min': 0}
    return {
        'status': sh.status,
        'start': _fmt_local(sh.start_at).strftime('%H:%M') if sh.start_at else None,
        'end': _fmt_local(sh.end_at).strftime('%H:%M') if sh.end_at else None,
        'worked_min': sh.worked_minutes,
    }


def _resolve_seller():
    """Vendedor objetivo: el propio (rol venta) o ?user_id (admin/lider)."""
    if current_user.role == 'venta':
        return current_user
    if current_user.role in ('admin', 'lider'):
        uid = request.args.get('user_id', type=int) or request.form.get('user_id', type=int)
        return db.session.get(User, uid) if uid else _sellers_query().first()
    abort(403)


def _latest_positions(users, budget_s=12):
    """Ultima posicion Traccar de varios usuarios EN PARALELO."""
    from app.traccar import get_latest_position
    from app.analytics.commercial import _parallel_fetch
    ids = [u.traccar_device_id for u in users if u.traccar_device_id]
    return _parallel_fetch(ids, lambda did: get_latest_position(did), budget_s=budget_s)


def _pos_from_traccar(p):
    if not p:
        return None
    try:
        ts = datetime.fromisoformat(str(p.get('fixTime', '')).replace('Z', '+00:00'))
        age_min = int((datetime.now(pytz.utc) - ts).total_seconds() // 60)
    except Exception:
        age_min = None
    return {'lat': p.get('latitude'), 'lng': p.get('longitude'),
            'speed_kmh': round((p.get('speed') or 0) * 1.852), 'age_min': age_min,
            'course': p.get('course')}


@bp.route('/app')
@login_required
def mobile_app():
    """Vista movil del vendedor (modo Uber): reloj de jornada, mapa, ruta optima."""
    seller = _resolve_seller()
    if seller is None:
        flash('Aun no hay usuarios con rol Venta.', 'warning')
        return redirect(url_for('sales.manage'))
    sh = _shift_today(seller.id)
    pending = SalesDeal.query.filter(
        SalesDeal.assigned_to == seller.id,
        SalesDeal.status.in_(('asignado', 'en_cotizacion')),
    ).count()
    sellers = _sellers_query().all() if current_user.role in ('admin', 'lider') else []
    return render_template('sales/app.html', title='Mi Ruta', seller=seller, avatar=_avatar(seller),
                           shift=_shift_json(sh), params=get_params(), pending=pending, sellers=sellers,
                           is_self=(current_user.id == seller.id))


@bp.route('/shift/<action>', methods=['POST'])
@login_required
def shift_action(action):
    """Marcar inicio o fin de jornada con ubicacion GPS (JSON: lat, lng)."""
    if current_user.role != 'venta':
        abort(403)
    if action not in ('start', 'end'):
        abort(404)
    data = request.get_json(silent=True) or {}
    lat, lng = data.get('lat'), data.get('lng')
    # 'at': hora real en que el vendedor toco el boton (la app la envia cuando
    # estuvo sin internet y sincroniza despues). Solo se acepta si es pasada
    # y de las ultimas 36 horas; si no, se usa la hora del servidor.
    now = datetime.now(pytz.utc)
    at = _parse_client_time(data.get('at'))
    if at and now - timedelta(hours=36) <= at <= now + timedelta(minutes=5):
        now = at
    shift_date = now.astimezone(COLOMBIA_TZ).date()
    sh = None
    if action == 'end':
        # Cerrar la jornada abierta aunque haya empezado ayer (cruce de medianoche)
        sh = WorkShift.query.filter(WorkShift.user_id == current_user.id, WorkShift.start_at.isnot(None),
                                    WorkShift.end_at.is_(None), WorkShift.shift_date >= shift_date - timedelta(days=1)
                                    ).order_by(WorkShift.shift_date.desc()).first()
    if sh is None:
        sh = WorkShift.query.filter_by(user_id=current_user.id, shift_date=shift_date).first()
    if sh is None:
        sh = WorkShift(user_id=current_user.id, shift_date=shift_date)
        db.session.add(sh)
    if action == 'start':
        if sh.start_at and not sh.end_at:
            return jsonify({'ok': False, 'msg': 'La jornada ya esta iniciada.', 'shift': _shift_json(sh)})
        if sh.start_at and at:
            # Reenvio de una accion encolada sin internet: ya quedo registrada, no se reabre
            return jsonify({'ok': False, 'msg': 'El inicio de jornada ya estaba registrado.', 'shift': _shift_json(sh)})
        sh.start_at, sh.end_at = now, None
        sh.start_lat, sh.start_lng = lat, lng
        msg = 'Jornada iniciada. Buen recorrido!'
    else:
        if not sh.start_at:
            return jsonify({'ok': False, 'msg': 'Primero inicia la jornada.', 'shift': _shift_json(sh)})
        sh.end_at = now
        sh.end_lat, sh.end_lng = lat, lng
        msg = 'Jornada finalizada. Buen trabajo!'
    db.session.commit()
    return jsonify({'ok': True, 'msg': msg, 'shift': _shift_json(sh)})


@bp.route('/api/plan')
@login_required
def api_plan():
    """Ruta optima del vendedor desde su posicion actual (JSON para el mapa)."""
    seller = _resolve_seller()
    if seller is None:
        return jsonify({'error': 'sin vendedor'}), 404

    lat = request.args.get('lat', type=float)
    lng = request.args.get('lng', type=float)
    origin_src = 'gps_celular'
    if lat is None or lng is None:
        pos = None
        if seller.traccar_device_id:
            pos = _pos_from_traccar(_latest_positions([seller]).get(seller.traccar_device_id))
        if pos and pos['lat'] is not None:
            lat, lng, origin_src = pos['lat'], pos['lng'], 'traccar'
        else:
            sh = _shift_today(seller.id)
            if sh and sh.start_lat is not None:
                lat, lng, origin_src = sh.start_lat, sh.start_lng, 'inicio_jornada'
            else:
                lat, lng, origin_src = BOGOTA_CENTER[0], BOGOTA_CENTER[1], 'ciudad'

    deals = SalesDeal.query.filter(
        SalesDeal.assigned_to == seller.id,
        SalesDeal.status.in_(('asignado', 'en_cotizacion')),
    ).order_by(SalesDeal.assigned_date).all()

    plan = build_plan((lat, lng), deals)
    for s in plan['stops']:
        s['photos'] = DealPhoto.query.filter_by(deal_id=s['deal_id']).count()
    plan['origin'] = {'lat': lat, 'lng': lng, 'source': origin_src}
    plan['end_time'] = plan['end_time'].strftime('%H:%M')
    plan['seller'] = {'id': seller.id, 'name': seller.full_name or seller.username, **_avatar(seller)}
    plan['shift'] = _shift_json(_shift_today(seller.id))
    plan['params'] = get_params()
    return jsonify(plan)


@bp.route('/api/live')
@login_required
def api_live():
    """Monitoreo en vivo (admin/lider): posicion, jornada y pendientes de cada vendedor."""
    if current_user.role not in ('admin', 'lider'):
        abort(403)
    sellers = _sellers_query().all()
    positions = _latest_positions(sellers)
    today = _today()
    shifts = {s.user_id: s for s in WorkShift.query.filter_by(shift_date=today).all()}
    day_start_utc = COLOMBIA_TZ.localize(datetime.combine(today, datetime.min.time())).astimezone(pytz.utc)
    # Desvios recientes (ultimos 15 min) reportados por la app de cada vendedor
    from app.models import RouteEvent
    since = datetime.now(pytz.utc) - timedelta(minutes=15)
    deviations = {}
    for ev in RouteEvent.query.filter(RouteEvent.kind == 'desvio', RouteEvent.at >= since.replace(tzinfo=None)
                                      ).order_by(RouteEvent.at.asc()).all():
        deviations[ev.user_id] = {'at': _fmt_local(ev.at).strftime('%H:%M'), 'distance_m': ev.distance_m,
                                  'min_ago': int((datetime.now(pytz.utc) - pytz.utc.localize(ev.at)).total_seconds() // 60),
                                  'detail': ev.detail}
    out = []
    for u in sellers:
        pend = SalesDeal.query.filter(SalesDeal.assigned_to == u.id,
                                      SalesDeal.status.in_(('asignado', 'en_cotizacion'))).count()
        won_today = SalesDeal.query.filter(SalesDeal.assigned_to == u.id, SalesDeal.status == 'ganado',
                                           SalesDeal.status_date >= day_start_utc).count()
        pos = _pos_from_traccar(positions.get(u.traccar_device_id)) if u.traccar_device_id else None
        out.append({
            'id': u.id, 'name': u.full_name or u.username, **_avatar(u),
            'position': pos, 'shift': _shift_json(shifts.get(u.id)),
            'pending': pend, 'won_today': won_today, 'has_device': bool(u.traccar_device_id),
            'deviation': deviations.get(u.id),
        })
    return jsonify({'sellers': out, 'ts': datetime.now(COLOMBIA_TZ).strftime('%H:%M:%S')})


@bp.route('/api/potential')
@login_required
def api_potential():
    """Potencial en el mapa (admin/lider): todos los negocios pendientes con ubicacion."""
    if current_user.role not in ('admin', 'lider'):
        abort(403)
    sellers = {u.id: u for u in _sellers_query().all()}
    deals = SalesDeal.query.filter(SalesDeal.status.in_(('asignado', 'en_cotizacion')),
                                   SalesDeal.latitude.isnot(None), SalesDeal.longitude.isnot(None)).all()
    out = []
    for d in deals:
        s = sellers.get(d.assigned_to)
        out.append({'id': d.id, 'client': d.client_name, 'lat': d.latitude, 'lng': d.longitude,
                    'status': d.status, 'status_display': d.status_display, 'origen': d.origen or '',
                    'seller_id': d.assigned_to, 'seller': (s.full_name or s.username) if s else 'Sin asignar',
                    'color': _avatar(s)['color'] if s else '#64748b', 'address': d.address or ''})
    return jsonify({'deals': out, 'total': len(out)})


@bp.route('/api/deviation', methods=['POST'])
@login_required
def api_deviation():
    """La app del vendedor reporta un desvio significativo de la ruta sugerida.
    Se registra maximo uno cada 5 minutos por vendedor."""
    if current_user.role != 'venta':
        abort(403)
    from app.models import RouteEvent
    data = request.get_json(silent=True) or {}
    now = datetime.now(pytz.utc)
    last = RouteEvent.query.filter_by(user_id=current_user.id, kind='desvio').order_by(RouteEvent.at.desc()).first()
    if last and (now - pytz.utc.localize(last.at)).total_seconds() < 300:
        return jsonify({'ok': True, 'stored': False})
    try:
        dist = int(float(data.get('distance_m') or 0))
    except (TypeError, ValueError):
        dist = 0
    ev = RouteEvent(user_id=current_user.id, kind='desvio', at=now, lat=data.get('lat'), lng=data.get('lng'),
                    distance_m=dist, detail=_clean(data.get('detail'), 200))
    db.session.add(ev)
    db.session.commit()
    return jsonify({'ok': True, 'stored': True, 'id': ev.id})


@bp.route('/monitor')
@login_required
def monitor():
    """Centro de monitoreo en vivo de vendedores (admin/lider)."""
    if current_user.role not in ('admin', 'lider'):
        abort(403)
    return render_template('sales/monitor.html', title='Monitoreo de Ventas', params=get_params(),
                           sellers=_sellers_query().all())


@bp.route('/deal/new', methods=['GET', 'POST'])
@login_required
def new_deal():
    """Demanda DISPERSA: el vendedor registra un negocio encontrado en campo, con
    latitud/longitud capturadas automaticamente del celular."""
    if current_user.role not in ('venta', 'admin', 'lider'):
        abort(403)
    if request.method == 'POST':
        # La app movil envia por fetch (y reenvia lo registrado sin internet): responde JSON
        as_json = request.headers.get('X-Requested-With') == 'fetch'
        client_name = (request.form.get('client_name') or '').strip()
        if not client_name:
            if as_json:
                return jsonify({'ok': False, 'msg': 'El nombre del cliente es obligatorio.'}), 400
            flash('El nombre del cliente es obligatorio.', 'danger')
            return redirect(url_for('sales.new_deal'))
        ref = _clean(request.form.get('client_ref'), 48)
        if ref:
            dup = SalesDeal.query.filter_by(client_ref=ref).first()
            if dup:
                if as_json:
                    return jsonify({'ok': True, 'msg': 'El negocio ya estaba registrado.', 'deal_id': dup.id})
                return redirect(url_for('sales.mobile_app'))
        lat = request.form.get('latitude', type=float)
        lng = request.form.get('longitude', type=float)
        if current_user.role == 'venta':
            seller_id = current_user.id
        else:
            seller_id = request.form.get('seller_id', type=int) or current_user.id
        status = request.form.get('status')
        # Fecha real del registro si se hizo sin internet y llega despues (max 7 dias)
        reg_date = _today()
        at = _parse_client_time(request.form.get('at'))
        if at and datetime.now(pytz.utc) - timedelta(days=7) <= at <= datetime.now(pytz.utc) + timedelta(minutes=5):
            reg_date = at.astimezone(COLOMBIA_TZ).date()
        deal = SalesDeal(
            client_ref=ref or None,
            client_name=client_name,
            client_number=_clean(request.form.get('client_number'), 50),
            address=_clean(request.form.get('address'), 300),
            phone=_clean(request.form.get('phone'), 50),
            market=_clean(request.form.get('market'), 100),
            campaign=_clean(request.form.get('campaign'), 200),
            notes=_clean(request.form.get('notes')),
            origen='Dispersa',
            status=status if status in DEAL_STATUSES else 'asignado',
            latitude=lat, longitude=lng,
            geocoded_at=datetime.utcnow() if lat is not None else None,
            assigned_to=seller_id, assigned_date=reg_date, assignment_period='diaria',
            created_by=current_user.id, start_date=reg_date,
        )
        db.session.add(deal)
        db.session.commit()
        if as_json:
            return jsonify({'ok': True, 'msg': f'Negocio "{client_name}" registrado como Demanda Dispersa.', 'deal_id': deal.id})
        flash(f'Negocio "{client_name}" registrado como Demanda Dispersa.', 'success')
        if current_user.role == 'venta':
            return redirect(url_for('sales.mobile_app'))
        return redirect(url_for('sales.manage'))
    sellers = _sellers_query().all() if current_user.role in ('admin', 'lider') else []
    return render_template('sales/deal_form.html', title='Nuevo negocio (Dispersa)', sellers=sellers)


@bp.route('/params', methods=['POST'])
@login_required
def save_params():
    """Parametros del modo ruta (ciudad para geocodificar, tiempo de visita, velocidad)."""
    if current_user.role != 'admin':
        abort(403)
    for key in PARAM_DEFAULTS:
        val = (request.form.get(key) or '').strip()
        if val:
            set_param(key, val)
    db.session.commit()
    flash('Parametros de ruta actualizados.', 'success')
    return redirect(url_for('sales.manage'))


# ============================================================
# FOTOS DE EVIDENCIA EN SITIO
# ============================================================
MAX_PHOTO_BYTES = 2 * 1024 * 1024  # el celular comprime a ~1280px antes de subir


def _image_mime(data):
    """Detecta el tipo por los primeros bytes; el mimetype del navegador no es confiable."""
    if data[:3] == b'\xff\xd8\xff':
        return 'image/jpeg'
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return 'image/png'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'image/webp'
    return None


@bp.route('/deal/<int:deal_id>/photo', methods=['POST'])
@login_required
def upload_photo(deal_id):
    """Sube una foto del sitio (fachada / evidencia). Multipart: photo, lat, lng, note."""
    deal = SalesDeal.query.get_or_404(deal_id)
    if current_user.role == 'venta' and deal.assigned_to != current_user.id:
        abort(403)
    if current_user.role not in ('venta', 'admin', 'lider'):
        abort(403)
    # Reintento de una foto tomada sin internet: si ya llego, no se duplica
    ref = _clean(request.form.get('client_ref'), 48)
    if ref:
        dup = DealPhoto.query.filter_by(deal_id=deal.id, client_ref=ref).first()
        if dup:
            total = DealPhoto.query.filter_by(deal_id=deal.id).count()
            return jsonify({'ok': True, 'msg': 'Foto ya estaba guardada.', 'photo_id': dup.id, 'total': total})
    f = request.files.get('photo')
    if not f or not f.filename:
        return jsonify({'ok': False, 'msg': 'No llego la foto.'}), 400
    data = f.read()
    if len(data) > MAX_PHOTO_BYTES:
        return jsonify({'ok': False, 'msg': 'La foto es muy pesada (max 2 MB).'}), 400
    mime = _image_mime(data)
    if not mime:
        return jsonify({'ok': False, 'msg': 'El archivo no es una imagen (JPG, PNG o WebP).'}), 400
    ph = DealPhoto(deal_id=deal.id, user_id=current_user.id, image=data, mime=mime,
                   size_bytes=len(data), lat=request.form.get('lat', type=float),
                   lng=request.form.get('lng', type=float), note=_clean(request.form.get('note'), 300),
                   client_ref=ref or None)
    # Hora real de la toma (si la foto se hizo sin internet y se subio despues)
    taken = _parse_client_time(request.form.get('taken_at'))
    now = datetime.now(pytz.utc)
    if taken and now - timedelta(days=7) <= taken <= now + timedelta(minutes=5):
        ph.created_at = taken
    db.session.add(ph)
    db.session.commit()
    total = DealPhoto.query.filter_by(deal_id=deal.id).count()
    return jsonify({'ok': True, 'msg': 'Foto guardada.', 'photo_id': ph.id, 'total': total})


@bp.route('/photo/<int:photo_id>')
@login_required
def photo(photo_id):
    ph = DealPhoto.query.get_or_404(photo_id)
    if current_user.role == 'venta' and ph.deal and ph.deal.assigned_to != current_user.id:
        abort(403)
    return Response(ph.image, mimetype=ph.mime or 'image/jpeg',
                    headers={'Cache-Control': 'private, max-age=86400'})


@bp.route('/deal/<int:deal_id>/photos')
@login_required
def deal_photos(deal_id):
    """Lista JSON de fotos de un negocio (para la app y el monitoreo)."""
    deal = SalesDeal.query.get_or_404(deal_id)
    if current_user.role == 'venta' and deal.assigned_to != current_user.id:
        abort(403)
    items = [{'id': p.id, 'url': url_for('sales.photo', photo_id=p.id),
              'at': _fmt_local(p.created_at).strftime('%d/%m %H:%M') if p.created_at else '',
              'note': p.note or ''} for p in deal.photos.order_by(DealPhoto.created_at.desc()).all()]
    return jsonify({'deal': deal.client_name, 'photos': items})
