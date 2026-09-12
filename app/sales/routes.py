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

    return render_template('sales/manage.html', title='Gestion de Ventas',
                           deals=deals, sellers=sellers, resumen=resumen,
                           totales=totales, status_f=status_f, seller_f=seller_f,
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
