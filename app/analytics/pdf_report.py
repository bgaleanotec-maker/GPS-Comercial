# Ruta: GPS_Comercial/app/analytics/pdf_report.py
"""Genera la presentacion PDF de la Analitica Comercial (reportlab, Python puro)."""
from datetime import datetime
from io import BytesIO

import pytz
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, PageBreak)
from reportlab.graphics.shapes import Drawing, PolyLine, Circle, Rect, String
from reportlab.graphics.charts.barcharts import HorizontalBarChart

COLOMBIA_TZ = pytz.timezone('America/Bogota')

INDIGO = colors.HexColor('#4f46e5')
INK = colors.HexColor('#1e293b')
SLATE = colors.HexColor('#475569')
LIGHT = colors.HexColor('#f1f5f9')
EMERALD = colors.HexColor('#059669')
AMBER = colors.HexColor('#d97706')
RED = colors.HexColor('#dc2626')


def _styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle('H1x', parent=ss['Title'], textColor=INK, fontSize=22, spaceAfter=4))
    ss.add(ParagraphStyle('Subx', parent=ss['Normal'], textColor=SLATE, fontSize=10, spaceAfter=2))
    ss.add(ParagraphStyle('H2x', parent=ss['Heading2'], textColor=INDIGO, fontSize=13, spaceBefore=10, spaceAfter=6))
    ss.add(ParagraphStyle('Smallx', parent=ss['Normal'], textColor=SLATE, fontSize=8))
    ss.add(ParagraphStyle('Cellx', parent=ss['Normal'], fontSize=8, textColor=INK))
    return ss


def _num(v, suf=''):
    if v is None:
        return '—'
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return f'{v}{suf}'


def _table(data, col_widths, header_bg=INDIGO, align_right_from=1):
    t = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        ('BACKGROUND', (0, 0), (-1, 0), header_bg),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('TEXTCOLOR', (0, 1), (-1, -1), INK),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, LIGHT]),
        ('LINEBELOW', (0, 0), (-1, 0), 0.5, INDIGO),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#e2e8f0')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (align_right_from, 1), (-1, -1), 'RIGHT'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
    ]
    t.setStyle(TableStyle(style))
    return t


def _kpi_band(kpis, ss):
    cells = [
        (str(kpis['total_visitas']), 'Visitas en radio'),
        (str(kpis['avg_dia']), 'Prom / dia laboral'),
        (str(kpis['avg_mes']), 'Prom / mes'),
        (str(kpis['gps_auto']), 'GPS auto'),
        (str(kpis['manual']), 'Manuales'),
        (f"{kpis['aliados_visitados']}/{kpis['aliados_total']}", 'Aliados visit.'),
    ]
    row_vals = [Paragraph(f"<b><font size=15 color='#4f46e5'>{v}</font></b>", ss['Cellx']) for v, _ in cells]
    row_lbls = [Paragraph(f"<font size=7 color='#475569'>{l}</font>", ss['Cellx']) for _, l in cells]
    t = Table([row_vals, row_lbls], colWidths=[3.0 * cm] * 6)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), LIGHT),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('INNERGRID', (0, 0), (-1, -1), 0.25, colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    return t


def _nivel_color(n):
    return {'Alto': EMERALD, 'Medio': AMBER, 'Bajo': RED}.get(n, SLATE)


def _score_bar_chart(ranking):
    """Grafico de barras horizontales del score de productividad."""
    r = list(reversed(ranking))  # mejor arriba
    names = [x['name'] for x in r]
    scores = [x['score'] for x in r]
    n = len(names)
    h = max(90, 16 * n + 40)
    d = Drawing(760, h)
    bc = HorizontalBarChart()
    bc.x = 150
    bc.y = 15
    bc.height = h - 30
    bc.width = 570
    bc.data = [scores]
    bc.strokeColor = colors.white
    bc.valueAxis.valueMin = 0
    bc.valueAxis.valueMax = 100
    bc.valueAxis.valueStep = 20
    bc.valueAxis.labels.fontSize = 7
    bc.categoryAxis.categoryNames = names
    bc.categoryAxis.labels.fontSize = 7
    bc.categoryAxis.labels.dx = -2
    bc.bars[0].fillColor = INDIGO
    bc.bars[0].strokeColor = colors.white
    bc.barLabels.fontSize = 7
    bc.barLabelFormat = '%d'
    bc.barLabels.dx = 6
    d.add(bc)
    return d


def _sample(points, maxn=400):
    if len(points) <= maxn:
        return points
    step = len(points) / maxn
    return [points[int(i * step)] for i in range(maxn)]


def _route_plot(points, name, day, w=175, h=135):
    """Dibuja la silueta del recorrido (sin tiles) normalizada a un recuadro."""
    points = _sample(points)
    d = Drawing(w, h)
    d.add(Rect(0, 0, w, h, fillColor=colors.HexColor('#f8fafc'), strokeColor=colors.HexColor('#e2e8f0')))
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    minlat, maxlat = min(lats), max(lats)
    minlon, maxlon = min(lons), max(lons)
    span_lat = (maxlat - minlat) or 1e-6
    span_lon = (maxlon - minlon) or 1e-6
    pad = 10
    top = 16  # espacio para el titulo
    s = min((w - 2 * pad) / span_lon, (h - pad - top) / span_lat)
    off_x = ((w - 2 * pad) - span_lon * s) / 2
    off_y = ((h - pad - top) - span_lat * s) / 2

    def tx(lon):
        return pad + off_x + (lon - minlon) * s

    def ty(lat):
        return pad + off_y + (lat - minlat) * s

    coords = []
    for la, lo in points:
        coords.extend([tx(lo), ty(la)])
    d.add(PolyLine(coords, strokeColor=INDIGO, strokeWidth=1.1))
    d.add(Circle(tx(points[0][1]), ty(points[0][0]), 2.4, fillColor=EMERALD, strokeColor=EMERALD))
    d.add(Circle(tx(points[-1][1]), ty(points[-1][0]), 2.4, fillColor=RED, strokeColor=RED))
    d.add(String(6, h - 11, f'{name[:26]}  ({day})', fontSize=7, fillColor=INK))
    return d


def build_commercial_pdf(ctx, routes=None):
    """Construye el PDF y devuelve un BytesIO listo para enviar."""
    buf = BytesIO()
    ss = _styles()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                            leftMargin=1.2 * cm, rightMargin=1.2 * cm,
                            topMargin=1.0 * cm, bottomMargin=1.0 * cm,
                            title='Analitica Comercial')
    story = []
    gen = datetime.now(COLOMBIA_TZ).strftime('%d/%m/%Y %H:%M')

    # --- Portada / encabezado ---
    story.append(Paragraph('Analitica Comercial · GPS Comercial', ss['H1x']))
    story.append(Paragraph(
        f"Periodo {ctx['start_date']} a {ctx['end_date']} · Solo dias laborales (Lun-Vie) · "
        f"{ctx['kpis']['working_days']} dias laborales · {ctx['kpis']['months']} mes(es)", ss['Subx']))
    filtro = []
    if ctx['min_dwell']:
        filtro.append(f"permanencia >= {ctx['min_dwell']} min")
    filtro.append(f"dias > {ctx['anomaly_km']} km excluidos")
    story.append(Paragraph('Filtros: ' + ' · '.join(filtro) + f" · Generado {gen}", ss['Smallx']))
    story.append(Spacer(1, 8))
    story.append(_kpi_band(ctx['kpis'], ss))
    story.append(Spacer(1, 10))

    # --- Comparativo de productividad ---
    comp = ctx.get('comparison')
    if comp:
        story.append(Paragraph('Comparativo de productividad entre ejecutivos', ss['H2x']))
        data = [['#', 'Ejecutivo', 'Score', 'Nivel', 'Perfil', 'Se parece a']]
        for x in comp['ranking']:
            data.append([str(x['rank']), x['name'], _num(x['score']), x['nivel'],
                         x['perfil'], x['similar_to']])
        t = _table(data, [1.0 * cm, 5.5 * cm, 1.6 * cm, 1.8 * cm, 6.5 * cm, 5.0 * cm], align_right_from=2)
        # colorear columna Nivel
        st = [('ALIGN', (2, 1), (3, -1), 'CENTER')]
        for i, x in enumerate(comp['ranking'], start=1):
            st.append(('TEXTCOLOR', (3, i), (3, i), _nivel_color(x['nivel'])))
            st.append(('FONTNAME', (3, i), (3, i), 'Helvetica-Bold'))
        t.setStyle(TableStyle(st))
        story.append(t)
        story.append(Spacer(1, 10))

        # Grafico de barras del score
        story.append(Paragraph('Ranking de productividad (score 0-100)', ss['H2x']))
        story.append(_score_bar_chart(comp['ranking']))
        story.append(Spacer(1, 8))

        # Grupos: los que se parecen
        story.append(Paragraph('Grupos con perfil similar', ss['H2x']))
        gdata = [['Nivel', 'Perfil', 'Ejecutivos']]
        for g in comp['grupos']:
            gdata.append([g['nivel'], g['perfil'], ', '.join(g['miembros'])])
        gt = _table(gdata, [1.8 * cm, 6.5 * cm, 16.0 * cm], header_bg=SLATE, align_right_from=99)
        story.append(gt)
        story.append(Spacer(1, 6))
        tops = ', '.join(x['name'] for x in comp['top'])
        bottoms = ', '.join(x['name'] for x in comp['bottom'])
        story.append(Paragraph(f"<b>Mas productivos:</b> {tops or '—'}", ss['Cellx']))
        story.append(Paragraph(f"<b>Menos productivos:</b> {bottoms or '—'}", ss['Cellx']))
        story.append(Paragraph(
            "Score de productividad: visitas efectivas por dia (40%), permanencia media (25%), "
            "consistencia de dias activos (20%) y cobertura de aliados (15%). El recorrido en km "
            "es esfuerzo/costo y no suma al score.", ss['Smallx']))
        story.append(PageBreak())

    # --- Resumen por ejecutivo ---
    story.append(Paragraph('Resumen por ejecutivo', ss['H2x']))
    header = ['Ejecutivo', 'Visitas', 'Aliados', 'Prom/dia', 'Perm.med', 'Km tot', 'Km/dia',
              'Med km/dia', 'Km/mes', 'Dias act/inact', 'Ult.']
    data = [header]
    for r in ctx['rows']:
        act = f"{r['active_days']}/{r['inactive_days']}" if r['active_days'] is not None else '—'
        data.append([
            r['name'], str(r['total']), str(r['allies']), _num(r['avg_day']),
            _num(r['avg_dwell'], ' min') if r['avg_dwell'] is not None else '—',
            _num(r['km_total']), _num(r['km_day']), _num(r['km_med_day']),
            _num(r['km_month']), act, r['last'],
        ])
    story.append(_table(data, [4.8 * cm, 1.6 * cm, 1.5 * cm, 1.6 * cm, 1.9 * cm, 1.7 * cm,
                               1.6 * cm, 2.0 * cm, 1.7 * cm, 2.3 * cm, 2.0 * cm], align_right_from=1))
    story.append(Spacer(1, 10))

    # --- Aliados mas visitados ---
    story.append(Paragraph('Aliados mas visitados', ss['H2x']))
    adata = [['Aliado', 'Categoria', 'Filial', 'Visitas', 'Ejecutivos', 'Prom/dia', 'Prom/mes']]
    for a in ctx['ally_rows'][:25]:
        adata.append([a['name'], a['category'], a['filial'], str(a['visits']),
                      str(a['execs']), _num(a['avg_day']), _num(a['avg_month'])])
    story.append(_table(adata, [7.0 * cm, 3.5 * cm, 2.5 * cm, 2.0 * cm, 2.3 * cm, 2.0 * cm, 2.0 * cm],
                        header_bg=EMERALD, align_right_from=3))

    # --- Recorridos (mapa de ruta por ejecutivo, dia representativo) ---
    if routes:
        story.append(PageBreak())
        story.append(Paragraph('Recorridos por ejecutivo', ss['H2x']))
        story.append(Paragraph('Silueta del recorrido GPS del ultimo dia con visita de cada ejecutivo '
                               '(verde = inicio, rojo = fin).', ss['Smallx']))
        story.append(Spacer(1, 6))
        plots = [_route_plot(r['points'], r['name'], r['date']) for r in routes]
        per_row = 4
        grid = []
        for i in range(0, len(plots), per_row):
            row = plots[i:i + per_row]
            while len(row) < per_row:
                row.append('')
            grid.append(row)
        gt = Table(grid, colWidths=[6.4 * cm] * per_row)
        gt.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(gt)

    # --- Ficha tecnica / metodologia ---
    _append_ficha(story, ss)

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    buf.seek(0)
    return buf


def _append_ficha(story, ss):
    """Explica como se calculan Score, Nivel, Perfil y las definiciones usadas."""
    try:
        from app.analytics.commercial import SCORE_WEIGHTS as W
    except Exception:
        W = {'v': 0.50, 'a': 0.30, 'd': 0.20}

    story.append(PageBreak())
    story.append(Paragraph('Ficha tecnica — como se calcula', ss['H1x']))
    story.append(Paragraph('Metodologia de la analitica comercial. Todos los calculos consideran '
                           'solo dias laborales (Lunes a Viernes).', ss['Subx']))
    story.append(Spacer(1, 8))

    story.append(Paragraph('1. Que cuenta como VISITA', ss['H2x']))
    story.append(Paragraph(
        'Una visita se cuenta cuando la trayectoria GPS del ejecutivo pasa a menos de '
        '<b>1000 metros</b> de la ubicacion (latitud/longitud) registrada del aliado ese dia. '
        'Se cuenta <b>maximo 1 visita por dia por aliado</b> (aunque pase varias veces), para no '
        'generar ruido. No exige permanencia minima: basta con pasar por el radio.', ss['Cellx']))
    story.append(Spacer(1, 6))

    story.append(Paragraph('2. Score de productividad (0 a 100)', ss['H2x']))
    story.append(Paragraph(
        'Se calcula con 3 componentes. Cada componente se <b>normaliza de 0 a 1</b> comparando a '
        'cada ejecutivo contra el resto del grupo (min-max: el mayor del grupo = 1, el menor = 0). '
        'Luego se ponderan y se multiplica por 100:', ss['Cellx']))
    story.append(Spacer(1, 4))
    wtbl = [['Componente', 'Que mide', 'Peso'],
            ['Actividad', 'Visitas por dia laboral (avg/dia)', f"{int(W['v']*100)}%"],
            ['Consistencia', 'Proporcion de dias activos (con recorrido) vs dias laborales', f"{int(W['a']*100)}%"],
            ['Cobertura', 'Cantidad de aliados distintos visitados', f"{int(W['d']*100)}%"]]
    story.append(_table(wtbl, [4.5 * cm, 13.0 * cm, 2.5 * cm], align_right_from=2))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        'Formula: <b>Score = (' + f"{W['v']:.2f}" + '·Actividad + ' + f"{W['a']:.2f}" +
        '·Consistencia + ' + f"{W['d']:.2f}" + '·Cobertura) × 100</b>, con cada factor entre 0 y 1. '
        'El <b>recorrido en km NO entra al score</b>: es esfuerzo/costo, no resultado (mucho km con '
        'pocas visitas no es productivo). El km se muestra aparte como contexto.', ss['Smallx']))
    story.append(Spacer(1, 6))

    story.append(Paragraph('3. Nivel (Alto / Medio / Bajo)', ss['H2x']))
    story.append(Paragraph(
        'Es <b>relativo al grupo analizado</b>, por tercios segun el score: el tercio superior es '
        '<b>Alto</b>, el del medio <b>Medio</b> y el inferior <b>Bajo</b>. Al cambiar el rango de '
        'fechas o la seleccion de ejecutivos, los niveles se recalculan sobre ese grupo.', ss['Cellx']))
    story.append(Spacer(1, 6))

    story.append(Paragraph('4. Perfil (patron de comportamiento)', ss['H2x']))
    ptbl = [['Perfil', 'Condicion'],
            ['Productivo (activo y constante)', 'Actividad alta y buena consistencia de dias activos'],
            ['Mucho desplazamiento, pocas visitas', 'Km/dia alto pero pocas visitas (se mueve pero no visita)'],
            ['Baja consistencia (pocos dias activos)', 'Trabaja pocos dias dentro del periodo'],
            ['Buena cobertura de aliados', 'Visita muchos aliados distintos con actividad razonable'],
            ['Estandar', 'No cae en ninguno de los patrones anteriores']]
    story.append(_table(ptbl, [6.5 * cm, 13.5 * cm], header_bg=SLATE, align_right_from=99))
    story.append(Spacer(1, 6))

    story.append(Paragraph('5. "Se parece a" y grupos similares', ss['H2x']))
    story.append(Paragraph(
        'Para cada ejecutivo se busca al mas parecido midiendo la <b>distancia</b> entre sus '
        'indicadores normalizados (visitas/dia, km/dia, consistencia y cobertura). Los "grupos que '
        'se parecen" agrupan a quienes comparten el mismo Nivel y Perfil.', ss['Cellx']))
    story.append(Spacer(1, 6))

    story.append(Paragraph('6. Recorrido (km)', ss['H2x']))
    story.append(Paragraph(
        'Se toma de Traccar por dia. Para el analisis de productividad se <b>excluyen los dias '
        'anomalos</b> (recorrido mayor al umbral configurado, por defecto 600 km/dia, ej. viajes '
        'largos fuera de lo normal). Se reportan total, media y mediana por dia/semana/mes, y los '
        'dias activos vs inactivos.', ss['Cellx']))


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont('Helvetica', 7)
    canvas.setFillColor(SLATE)
    canvas.drawString(1.2 * cm, 0.6 * cm, 'GPS Comercial — Analitica Comercial')
    canvas.drawRightString(doc.pagesize[0] - 1.2 * cm, 0.6 * cm, f'Pagina {doc.page}')
    canvas.restoreState()
