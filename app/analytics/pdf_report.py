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


def build_commercial_pdf(ctx):
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

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    buf.seek(0)
    return buf


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont('Helvetica', 7)
    canvas.setFillColor(SLATE)
    canvas.drawString(1.2 * cm, 0.6 * cm, 'GPS Comercial — Analitica Comercial')
    canvas.drawRightString(doc.pagesize[0] - 1.2 * cm, 0.6 * cm, f'Pagina {doc.page}')
    canvas.restoreState()
