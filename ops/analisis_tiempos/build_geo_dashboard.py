# -*- coding: utf-8 -*-
"""Dashboard de GEOANALITICA y VIGILANCIA OPERACIONAL (HTML interactivo) a partir del libro
generado por run_analisis.py. Calcula KPIs geo-operativos por ejecutivo y segmento, y
redacta conclusiones automaticas con los datos.
Uso: python ops/analisis_tiempos/build_geo_dashboard.py <ruta.xlsx> [salida.html]"""
import io, json, math, os, sys, statistics
from collections import defaultdict, Counter
from datetime import date, timedelta
from openpyxl import load_workbook

XLSX = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(XLSX), 'VantiGo_Geoanalitica_Dashboard.html')
RESIDENCIAL = {'amgomez', 'jjbecerra', 'kvlamprea', 'vqherrera', 'gmalvarado', 'elmateus', 'lemurcia', 'dramaya', 'malejandra', 'kmlara', 'ajsuarez'}
SEG = lambda e: 'Residencial' if e in RESIDENCIAL else 'Mercado Comercial'
SPEED_LIMIT = 80          # km/h: umbral de exceso (conduccion segura)
LONG_STOP_MIN = 120       # parada > 2 h fuera de base = tiempo muerto potencial
PROD_STOP_MIN = 20        # parada productiva: >= 20 min fuera de base

wb = load_workbook(XLSX, read_only=True)
def sheet(name):
    it = wb[name].iter_rows(values_only=True); h = next(it); return [dict(zip(h, r)) for r in it if any(v not in (None, '') for v in r)]
diario, paradas, lugares, excl = sheet('Resumen diario'), sheet('Paradas'), sheet('Lugares frecuentes'), sheet('Dias excluidos')
wb.close()
num = lambda v: (float(v) if v not in (None, '') else None)
hav = lambda a, b, c, d: 2 * 6371000 * math.asin(math.sqrt(math.sin(math.radians(c - a) / 2) ** 2 + math.cos(math.radians(a)) * math.cos(math.radians(c)) * math.sin(math.radians(d - b) / 2) ** 2))
tm = lambda s: (int(s[:2]) * 60 + int(s[3:5])) if s else None
hm = lambda m: '' if m is None else f'{int(m) // 60:02d}:{int(m) % 60:02d}'

emps = sorted({r['Empleado'] for r in diario} | {r['Empleado'] for r in paradas})
bases = {l['Empleado']: (num(l['Latitud']), num(l['Longitud'])) for l in lugares if str(l.get('Tipo') or l.get('Tipo de lugar') or '').startswith('Posible')}
by_emp_d = defaultdict(list); by_emp_p = defaultdict(list)
for r in diario: by_emp_d[r['Empleado']].append(r)
for p in paradas: by_emp_p[p['Empleado']].append(p)

def convex_hull_area_km2(pts):
    pts = sorted(set(pts))
    if len(pts) < 3: return 0.0
    def cross(o, a, b): return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0: lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0: upper.pop()
        upper.append(p)
    hull = lower[:-1] + upper[:-1]
    # area en km2 (proyeccion local)
    lat0 = sum(p[0] for p in hull) / len(hull); kx = 111.32 * math.cos(math.radians(lat0)); ky = 110.57
    xy = [((p[1]) * kx, p[0] * ky) for p in hull]
    return abs(sum(xy[i][0] * xy[(i + 1) % len(xy)][1] - xy[(i + 1) % len(xy)][0] * xy[i][1] for i in range(len(xy)))) / 2, hull

kpi = {}
for e in emps:
    ds, ps = by_emp_d[e], by_emp_p[e]
    if not ds:
        continue
    base = bases.get(e)
    nb = [p for p in ps if not (base and hav(num(p['Latitud']), num(p['Longitud']), base[0], base[1]) <= 150)]   # paradas fuera de base
    inbase_min = sum(num(p['Duracion (min)']) or 0 for p in ps) - sum(num(p['Duracion (min)']) or 0 for p in nb)
    det_min = sum((num(r['Min en aliados']) or 0) + (num(r['Min en otros lugares']) or 0) for r in ds)
    jornada_min = sum((num(r['Jornada (h)']) or 0) * 60 for r in ds)
    stops_latlng = [(num(p['Latitud']), num(p['Longitud'])) for p in nb if p['Latitud'] is not None]
    if stops_latlng:
        clat = statistics.median(x[0] for x in stops_latlng); clng = statistics.median(x[1] for x in stops_latlng)
        dists = sorted(hav(a, b, clat, clng) / 1000 for a, b in stops_latlng)
        radio80 = dists[int(len(dists) * 0.8) - 1] if len(dists) > 1 else dists[0]
        area, hull = convex_hull_area_km2(stops_latlng) if len(stops_latlng) >= 3 else (0.0, [])
    else:
        clat = clng = None; radio80 = 0; area, hull = 0.0, []
    days = len(ds); km = sum(num(r['Km recorridos']) or 0 for r in ds)
    first_d, last_d = min(r['Fecha'] for r in ds), max(r['Fecha'] for r in ds)
    d0, d1 = date.fromisoformat(first_d), date.fromisoformat(last_d)
    business = sum(1 for i in range((d1 - d0).days + 1) if (d0 + timedelta(i)).weekday() < 5)
    inis = [tm(r['Inicio recorrido']) for r in ds if r['Inicio recorrido']]
    # velocidades > 200 km/h son ruido del GPS: no cuentan como exceso ni como maxima
    vmaxs = [min(num(r['Vel. max (km/h)']) or 0, 200) if (num(r['Vel. max (km/h)']) or 0) <= 200 else 0 for r in ds]
    speeding_days = sum(1 for v in vmaxs if v > SPEED_LIMIT)
    prod = [p for p in nb if (num(p['Duracion (min)']) or 0) >= PROD_STOP_MIN]
    dead = [p for p in nb if (num(p['Duracion (min)']) or 0) >= LONG_STOP_MIN]
    hf = [num(r.get('Horas fuera de base')) for r in ds if num(r.get('Horas fuera de base')) is not None]
    kpi[e] = {
        'e': e, 'seg': SEG(e), 'dias': days, 'desde': first_d, 'hasta': last_d, 'cobertura': round(100 * days / business, 0) if business else 0,
        'km': round(km, 1), 'kmd': round(km / days, 1), 'jornada': round(jornada_min / days / 60, 2),
        'ini': hm(statistics.mean(inis)) if inis else '', 'fin': hm(statistics.mean([tm(r['Fin recorrido']) for r in ds if r['Fin recorrido']])) if ds else '',
        'puntualidad_sd': round(statistics.pstdev(inis) / 60, 2) if len(inis) > 1 else 0,
        'base': bool(base), 'pct_base': round(100 * inbase_min / jornada_min, 1) if jornada_min else 0,
        'pct_detenido': round(100 * det_min / jornada_min, 1) if jornada_min else 0,
        'prod_dia': round(len(prod) / days, 2), 'prod_min_dia': round(sum(num(p['Duracion (min)']) or 0 for p in prod) / days),
        'muertos': len(dead), 'muertos_min': round(sum(num(p['Duracion (min)']) or 0 for p in dead)),
        'radio_km': round(radio80, 1), 'area_km2': round(area, 1), 'centro': [clat, clng] if clat is not None else None, 'hull': [[round(a, 5), round(b, 5)] for a, b in hull],
        'vmax_prom': round(statistics.mean(vmaxs)), 'vmax_abs': round(max(vmaxs)),
        'dias_exceso': speeding_days, 'pct_exceso': round(100 * speeding_days / days),
        'hf': round(statistics.mean(hf), 2) if hf else None, 'km_por_parada': round(km / len(prod), 1) if prod else None,
        'excluidos': sum(1 for x in excl if x['Empleado'] == e and x['Fecha']),
    }
# Indice operativo compuesto (0-100), transparente: cobertura GPS 20, jornada en rango 20, paradas productivas 25,
# bajo tiempo en base 15, puntualidad 10, conduccion segura 10
def score(k):
    s = 0
    s += 20 * min(1, k['cobertura'] / 100)
    s += 20 * (1 if 8 <= k['jornada'] <= 12 else max(0, 1 - abs(k['jornada'] - 10) / 6))
    s += 25 * min(1, k['prod_dia'] / 4)
    s += 15 * max(0, 1 - k['pct_base'] / 40)
    s += 10 * max(0, 1 - k['puntualidad_sd'] / 2)
    s += 10 * max(0, 1 - k['pct_exceso'] / 50)
    return round(s)
for k in kpi.values(): k['indice'] = score(k)

# Solapamiento de lugares entre ejecutivos (mismo sitio frecuente, <=150 m)
overlap = []
L = [l for l in lugares if l['Latitud'] is not None]
for i in range(len(L)):
    for j in range(i + 1, len(L)):
        a, b = L[i], L[j]
        if a['Empleado'] != b['Empleado'] and hav(num(a['Latitud']), num(a['Longitud']), num(b['Latitud']), num(b['Longitud'])) <= 150:
            overlap.append({'a': a['Empleado'], 'b': b['Empleado'], 'lat': num(a['Latitud']), 'lng': num(a['Longitud']), 'dir': (a.get('Direccion') or b.get('Direccion') or '')[:70], 'va': num(a['Veces']), 'vb': num(b['Veces'])})

# --------- Conclusiones automaticas ---------
ks = sorted(kpi.values(), key=lambda k: -k['indice'])
seg_stats = {}
for sg in ('Mercado Comercial', 'Residencial'):
    g = [k for k in kpi.values() if k['seg'] == sg and k['dias'] >= 5]
    if g:
        seg_stats[sg] = {'n': len(g), 'kmd': statistics.mean(k['kmd'] for k in g), 'jornada': statistics.mean(k['jornada'] for k in g), 'prod': statistics.mean(k['prod_dia'] for k in g),
                         'base': statistics.mean(k['pct_base'] for k in g), 'radio': statistics.mean(k['radio_km'] for k in g), 'exceso': statistics.mean(k['pct_exceso'] for k in g), 'indice': statistics.mean(k['indice'] for k in g), 'cob': statistics.mean(k['cobertura'] for k in g)}
concl = []
if len(seg_stats) == 2:
    c, r = seg_stats['Mercado Comercial'], seg_stats['Residencial']
    concl.append(f"Segmentos: Mercado Comercial ({c['n']} ejecutivos con datos suficientes) promedia {c['kmd']:.0f} km/dia, {c['prod']:.1f} paradas productivas/dia y un radio de operacion de {c['radio']:.0f} km; Residencial ({r['n']}) promedia {r['kmd']:.0f} km/dia, {r['prod']:.1f} paradas productivas/dia y radio de {r['radio']:.0f} km. Indice operativo promedio: Comercial {c['indice']:.0f} vs Residencial {r['indice']:.0f}.")
    concl.append(f"Tiempo en base durante la jornada: Comercial {c['base']:.0f}% vs Residencial {r['base']:.0f}% del tiempo laboral se pasa en el domicilio/base detectado.")
top = [k for k in ks if k['dias'] >= 5][:3]; bot = [k for k in reversed(ks) if k['dias'] >= 5][:3]
concl.append("Mejor desempeno operativo (indice): " + ', '.join(f"{k['e']} ({k['indice']}, {k['prod_dia']:.1f} paradas productivas/dia, {k['pct_base']:.0f}% en base)" for k in top) + '.')
concl.append("Menor desempeno operativo: " + ', '.join(f"{k['e']} ({k['indice']}: {k['prod_dia']:.1f} paradas productivas/dia, {k['pct_base']:.0f}% en base, cobertura GPS {k['cobertura']:.0f}%)" for k in bot) + '.')
hb = [k for k in kpi.values() if k['pct_base'] >= 30 and k['dias'] >= 5]
if hb: concl.append("Alto tiempo en base/domicilio en horario laboral (>=30%): " + ', '.join(f"{k['e']} {k['pct_base']:.0f}%" for k in sorted(hb, key=lambda k: -k['pct_base'])) + '. Revisar si el trabajo es remoto o si hay inactividad.')
dm = sorted([k for k in kpi.values() if k['muertos'] >= 3], key=lambda k: -k['muertos_min'])[:5]
if dm: concl.append("Tiempos muertos (paradas de mas de 2 h fuera de base): " + ', '.join(f"{k['e']} {k['muertos']} veces / {k['muertos_min'] / 60:.0f} h" for k in dm) + '.')
sp = sorted([k for k in kpi.values() if k['pct_exceso'] >= 25 and k['dias'] >= 5], key=lambda k: -k['pct_exceso'])
if sp: concl.append(f"Conduccion segura: superan {SPEED_LIMIT} km/h en al menos 1 de cada 4 dias " + ', '.join(f"{k['e']} ({k['pct_exceso']}% de los dias, max {k['vmax_abs']} km/h)" for k in sp) + '.')
lowcov = [k for k in kpi.values() if k['cobertura'] < 60]
if lowcov: concl.append("Cobertura GPS baja (<60% de los dias habiles de su periodo): " + ', '.join(f"{k['e']} {k['cobertura']:.0f}%" for k in lowcov) + '. Verificar dispositivo, bateria o permisos de ubicacion.')
late = sorted([k for k in kpi.values() if k['ini'] and tm(k['ini']) >= 9 * 60 and k['dias'] >= 5], key=lambda k: -tm(k['ini']))
if late: concl.append("Inicio tardio (primer registro GPS despues de las 09:00 en promedio): " + ', '.join(f"{k['e']} {k['ini']}" for k in late) + '.')
longd = sorted([k for k in kpi.values() if k['jornada'] >= 12 and k['dias'] >= 5], key=lambda k: -k['jornada'])
if longd: concl.append("Jornadas extensas (>=12 h entre primer y ultimo registro): " + ', '.join(f"{k['e']} {k['jornada']} h" for k in longd) + '. Revisar carga o uso del vehiculo fuera de horario.')
wide = sorted([k for k in kpi.values() if k['radio_km'] >= 25 and k['dias'] >= 5], key=lambda k: -k['radio_km'])
if wide: concl.append("Territorios muy amplios (radio P80 >= 25 km): " + ', '.join(f"{k['e']} {k['radio_km']} km / {k['area_km2']:.0f} km2" for k in wide) + '. Candidatos a reasignar zonas para reducir desplazamientos.')
if overlap:
    pares = Counter((min(o['a'], o['b']), max(o['a'], o['b'])) for o in overlap)
    concl.append("Solapamiento de territorio (mismo sitio frecuente visitado por dos ejecutivos): " + ', '.join(f"{a}–{b} ({n} sitios)" for (a, b), n in pares.most_common(5)) + '.')
concl.append(f"Dias excluidos por incoherencia: {len([x for x in excl if x['Fecha']])} (viajes fuera de zona y dias sin GPS suficiente); no afectan los promedios.")

data = {'kpi': kpi, 'segmentos': {e: SEG(e) for e in emps}, 'bases': {e: list(b) for e, b in bases.items()},
        'diario': [{'e': r['Empleado'], 'f': r['Fecha'], 'ini': r['Inicio recorrido'], 'fin': r['Fin recorrido'], 'h': num(r['Jornada (h)']), 'km': num(r['Km recorridos']), 'p': num(r['Paradas']), 'vmax': num(r['Vel. max (km/h)']), 'sb': r.get('Salida de base/domicilio') or '', 'lb': r.get('Llegada a base/domicilio') or ''} for r in diario],
        'paradas': [{'e': p['Empleado'], 'f': p['Fecha'], 'n': p['Parada #'], 'll': p['Llegada'], 'sa': p['Salida'], 'min': num(p['Duracion (min)']), 'lat': num(p['Latitud']), 'lng': num(p['Longitud']), 'dir': p.get('Direccion') or '', 'lf': p.get('Lugar frecuente') or '', 'tr': num(p['Desplazamiento desde anterior (min)'])} for p in paradas if p['Latitud'] is not None],
        'lugares': [{'e': l['Empleado'], 't': str(l.get('Tipo') or l.get('Tipo de lugar') or ''), 'v': num(l['Veces']), 'mt': num(l['Minutos totales']), 'lat': num(l['Latitud']), 'lng': num(l['Longitud']), 'dir': l.get('Direccion') or '', 'll': l['Llegada promedio']} for l in lugares if l['Latitud'] is not None],
        'overlap': overlap, 'conclusiones': concl, 'periodo': [min(r['Fecha'] for r in diario), max(r['Fecha'] for r in diario)], 'seg_stats': seg_stats,
        'umbrales': {'vel': SPEED_LIMIT, 'muerto': LONG_STOP_MIN, 'prod': PROD_STOP_MIN}}

HTML = r'''<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>VantiGo · Geoanalitica y Vigilancia Operacional</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet.heat@0.2.0/dist/leaflet-heat.js"></script>
<style>
:root{--bg:#0b1020;--card:#121a30;--card2:#1a2340;--line:#243052;--ind:#6366f1;--ind2:#818cf8;--em:#10b981;--am:#f59e0b;--red:#ef4444;--cy:#22d3ee;--tx:#f1f5f9;--mu:#94a3b8}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);font-family:Inter,Segoe UI,system-ui,sans-serif;font-size:14px}.wrap{max-width:1560px;margin:0 auto;padding:16px}
h1{font-size:24px;margin:0}h2{font-size:14px;margin:0 0 10px;color:var(--mu);text-transform:uppercase;letter-spacing:.5px}
.top{display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between;margin-bottom:14px}.note{font-size:11px;color:var(--mu);margin-top:6px}
.badge{display:inline-block;padding:3px 10px;border-radius:999px;font-size:11px;font-weight:700}.b-com{background:rgba(99,102,241,.2);color:#a5b4fc;border:1px solid rgba(99,102,241,.4)}.b-res{background:rgba(16,185,129,.18);color:#6ee7b7;border:1px solid rgba(16,185,129,.4)}
.filters{display:flex;flex-wrap:wrap;gap:8px;align-items:center;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:10px 12px;margin-bottom:14px}.filters label{font-size:11px;color:var(--mu)}
select,input[type=date]{background:#0f172a;color:var(--tx);border:1px solid var(--line);border-radius:10px;padding:7px 9px;font-size:13px}
.chip{cursor:pointer;padding:6px 12px;border-radius:999px;border:1px solid var(--line);background:#0f172a;color:var(--mu);font-size:12px;font-weight:700}.chip.on{background:var(--ind);color:#fff;border-color:var(--ind)}
.btn{cursor:pointer;padding:7px 12px;border-radius:10px;border:1px solid var(--line);background:#0f172a;color:var(--tx);font-size:12px;font-weight:700}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:14px}.kpi{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px 14px}.kpi .v{font-size:24px;font-weight:800}.kpi .l{font-size:11px;color:var(--mu);margin-top:2px}.kpi .s{font-size:11px;margin-top:4px;color:var(--mu)}
.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:12px}.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;grid-column:span 12}
@media(min-width:900px){.c6{grid-column:span 6}.c4{grid-column:span 4}.c8{grid-column:span 8}.c3{grid-column:span 3}.c9{grid-column:span 9}}
.chart{position:relative;height:300px}.chart.tall{height:460px}
table{width:100%;border-collapse:collapse;font-size:12.5px}th{text-align:left;color:var(--mu);font-size:10.5px;text-transform:uppercase;padding:8px 5px;border-bottom:1px solid var(--line);cursor:pointer;white-space:nowrap}
td{padding:7px 5px;border-bottom:1px solid rgba(36,48,82,.5);white-space:nowrap}tr:hover td{background:rgba(99,102,241,.06)}td.r,th.r{text-align:right}
#map{height:620px;border-radius:12px}.leaflet-container{background:#dce8d5}.lay{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}
.lay .chip{font-size:11px;padding:5px 10px}.legend{font-size:11px;color:var(--mu);display:flex;flex-wrap:wrap;gap:12px;margin-top:8px}.legend i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:4px}
.score{display:inline-block;min-width:38px;text-align:center;padding:3px 6px;border-radius:8px;font-weight:800;color:#0f172a}
.concl{display:flex;flex-direction:column;gap:8px}.concl .it{background:var(--card2);border-left:4px solid var(--ind);border-radius:10px;padding:10px 12px;font-size:13px;line-height:1.45}
.tl{display:flex;flex-direction:column;gap:6px;max-height:560px;overflow:auto}.tl .it{display:grid;grid-template-columns:48px 1fr;gap:8px}.tl .t{color:var(--ind2);font-weight:700;font-size:12px}.tl .box{background:var(--card2);border-radius:10px;padding:7px 10px;font-size:12px}.tl .mv{color:var(--mu);font-size:11px;padding:1px 10px}
.heat{display:grid;grid-template-columns:repeat(auto-fill,minmax(42px,1fr));gap:3px;font-size:10px}.heat div{padding:4px 2px;text-align:center;border-radius:4px;color:#e2e8f0;cursor:pointer}
.pill{font-size:10px;padding:2px 7px;border-radius:999px;background:#0f172a;border:1px solid var(--line);color:var(--mu)}.foot{color:var(--mu);font-size:11px;margin:18px 0 6px;text-align:center}
.formula{font-size:11px;color:var(--mu);background:#0f172a;border-radius:10px;padding:8px 10px;margin-top:8px}
</style></head><body><div class="wrap">
<div class="top"><div><h1>Geoanalitica y Vigilancia Operacional</h1><div class="note">VantiGo · Periodo <b id="per"></b> · Horario laboral 06:00–20:00 L–V · GPS depurado · Vista de experto: territorio, uso del tiempo, productividad de paradas, conduccion segura</div></div>
<div><span class="badge b-com">Mercado Comercial</span> <span class="badge b-res">Residencial</span></div></div>
<div class="filters"><span class="chip on" data-seg="Todos">Todos</span><span class="chip" data-seg="Mercado Comercial">Mercado Comercial</span><span class="chip" data-seg="Residencial">Residencial</span>
<label>Ejecutivo</label><select id="fEmp"><option value="">Todos</option></select><label>Desde</label><input type="date" id="fIni"><label>Hasta</label><input type="date" id="fFin"><button class="btn" id="fReset">Limpiar</button><span class="note" id="fInfo"></span></div>
<div class="kpis" id="kpis"></div>
<div class="grid">
 <div class="card c9"><h2>Mapa operacional <span class="pill">capas activables · clic en un punto para el detalle</span></h2>
  <div class="lay"><span class="chip on" data-l="heat">Calor de paradas (minutos)</span><span class="chip" data-l="stops">Paradas</span><span class="chip on" data-l="places">Lugares frecuentes</span><span class="chip on" data-l="bases">Bases / domicilios</span><span class="chip" data-l="terr">Territorios (radio P80)</span><span class="chip" data-l="hull">Area cubierta</span><span class="chip" data-l="over">Solapamientos</span><span class="chip on" data-l="route">Recorrido del dia</span>
   <span style="margin-left:auto" class="note">Color:</span><span class="chip on" data-c="seg">por segmento</span><span class="chip" data-c="emp">por ejecutivo</span></div>
  <div id="map"></div><div class="legend" id="legend"></div></div>
 <div class="card c3"><h2>Ejecutivos en el mapa</h2><div style="overflow:auto;max-height:620px"><table id="tEmp"><thead><tr><th>Ejecutivo</th><th class="r">Indice</th><th class="r">Radio km</th></tr></thead><tbody></tbody></table></div></div>
 <div class="card"><h2>Conclusiones del analisis</h2><div class="concl" id="concl"></div></div>
 <div class="card"><h2>Tablero de KPIs operativos por ejecutivo <span class="pill">clic en encabezado para ordenar · clic en fila para ver su territorio y detalle</span></h2><div style="overflow-x:auto"><table id="rank"><thead><tr>
  <th data-k="e">Ejecutivo</th><th data-k="seg">Seg.</th><th class="r" data-k="indice">Indice</th><th class="r" data-k="cobertura">Cobertura GPS</th><th class="r" data-k="dias">Dias</th><th class="r" data-k="kmd">Km/dia</th><th class="r" data-k="jornada">Jornada h</th><th class="r" data-k="ini">Inicio</th><th class="r" data-k="fin">Fin</th><th class="r" data-k="puntualidad_sd">Var. inicio (h)</th><th class="r" data-k="prod_dia">Paradas prod./dia</th><th class="r" data-k="prod_min_dia">Min prod./dia</th><th class="r" data-k="pct_base">% en base</th><th class="r" data-k="muertos">Tiempos muertos</th><th class="r" data-k="radio_km">Radio P80 km</th><th class="r" data-k="area_km2">Area km2</th><th class="r" data-k="km_por_parada">Km/parada</th><th class="r" data-k="pct_exceso">% dias >80 km/h</th><th class="r" data-k="vmax_abs">Vmax</th></tr></thead><tbody></tbody></table></div>
  <div class="formula"><b>Indice operativo (0–100)</b> = cobertura GPS (20) + jornada entre 8 y 12 h (20) + paradas productivas/dia, meta 4 (25) + poco tiempo en base, meta <40% (15) + puntualidad: variabilidad del inicio <2 h (10) + conduccion segura: pocos dias sobre 80 km/h (10). Parada productiva = parada ≥20 min fuera de la base. Tiempo muerto = parada ≥2 h fuera de la base. Radio P80 = radio que contiene el 80% de sus paradas desde su centro de operacion.</div></div>
 <div class="card c6"><h2>Productividad vs kilometraje</h2><div class="chart tall"><canvas id="cScatter"></canvas></div><div class="note">Cada punto es un ejecutivo: km por dia (x) vs paradas productivas por dia (y). Arriba-izquierda = eficiente; abajo-derecha = mucho recorrido con pocas visitas.</div></div>
 <div class="card c6"><h2>Uso del tiempo de la jornada</h2><div class="chart tall"><canvas id="cUso"></canvas></div><div class="note">% del tiempo laboral: en base/domicilio, detenido fuera de base, en movimiento.</div></div>
 <div class="card c6"><h2>Conduccion segura: % de dias con exceso de velocidad</h2><div class="chart"><canvas id="cVel"></canvas></div></div>
 <div class="card c6"><h2>Territorio: radio P80 y area cubierta</h2><div class="chart"><canvas id="cTerr"></canvas></div></div>
 <div class="card c8"><h2>Detalle: <span id="detName" style="color:var(--ind2)">(selecciona un ejecutivo)</span> <span class="pill">clic en un dia para dibujar su recorrido en el mapa</span></h2><div class="heat" id="cal"></div></div>
 <div class="card c4"><h2>Recorrido del dia <span id="detDay"></span></h2><div class="tl" id="tl"><div class="note">Elige un dia.</div></div></div>
</div><div class="foot">VantiGo · Estrategia comercial, planificacion y conduccion segura · Generado __FECHA__</div></div>
<script>
const D=__DATA__; const SEGC={'Mercado Comercial':'#6366f1','Residencial':'#10b981'}; const PAL=['#6366f1','#10b981','#f59e0b','#ef4444','#22d3ee','#a855f7','#f97316','#84cc16','#ec4899','#14b8a6','#eab308','#3b82f6','#fb7185','#34d399','#c084fc','#f87171','#38bdf8','#a3e635','#fbbf24','#818cf8'];
const emps=Object.keys(D.segmentos).sort(); const EC={}; emps.forEach((e,i)=>EC[e]=PAL[i%PAL.length]);
const st={seg:'Todos',emp:'',ini:'',fin:'',layers:{heat:1,stops:0,places:1,bases:1,terr:0,hull:0,over:0,route:1},color:'seg',det:'',day:'',sortK:'indice',sortD:-1};
const $=s=>document.querySelector(s); const fmt=(n,d=1)=>n==null?'—':Number(n).toLocaleString('es-CO',{maximumFractionDigits:d}); const tm=s=>s?parseInt(s.slice(0,2))*60+parseInt(s.slice(3,5)):null; const hm=m=>m==null?'—':`${String(Math.floor(m/60)).padStart(2,'0')}:${String(Math.round(m%60)).padStart(2,'0')}`;
$('#per').textContent=D.periodo.join(' a '); emps.forEach(e=>{const o=document.createElement('option');o.value=e;o.textContent=e;$('#fEmp').appendChild(o)});
document.querySelectorAll('.filters .chip').forEach(c=>c.onclick=()=>{document.querySelectorAll('.filters .chip').forEach(x=>x.classList.remove('on'));c.classList.add('on');st.seg=c.dataset.seg;render()});
document.querySelectorAll('.lay .chip[data-l]').forEach(c=>c.onclick=()=>{st.layers[c.dataset.l]=st.layers[c.dataset.l]?0:1;c.classList.toggle('on');drawMap()});
document.querySelectorAll('.lay .chip[data-c]').forEach(c=>c.onclick=()=>{document.querySelectorAll('.lay .chip[data-c]').forEach(x=>x.classList.remove('on'));c.classList.add('on');st.color=c.dataset.c;drawMap()});
$('#fEmp').onchange=e=>{st.emp=e.target.value;st.det=st.emp;st.day='';render()};$('#fIni').onchange=e=>{st.ini=e.target.value;render()};$('#fFin').onchange=e=>{st.fin=e.target.value;render()};
$('#fReset').onclick=()=>{st.seg='Todos';st.emp='';st.ini='';st.fin='';st.det='';st.day='';$('#fEmp').value='';$('#fIni').value='';$('#fFin').value='';document.querySelectorAll('.filters .chip').forEach(x=>x.classList.toggle('on',x.dataset.seg==='Todos'));render()};
const keepE=e=>(st.seg==='Todos'||D.segmentos[e]===st.seg)&&(!st.emp||e===st.emp); const keepR=r=>keepE(r.e)&&(!st.ini||r.f>=st.ini)&&(!st.fin||r.f<=st.fin);
const col=e=>st.color==='seg'?SEGC[D.segmentos[e]]:EC[e]; const scoreCol=v=>v>=70?'#6ee7b7':v>=50?'#fcd34d':'#fca5a5';
const charts={};function mk(id,cfg){if(charts[id])charts[id].destroy();charts[id]=new Chart(document.getElementById(id),cfg)} Chart.defaults.color='#94a3b8';Chart.defaults.borderColor='rgba(36,48,82,.6)';
const map=L.map('map').setView([4.7,-74.1],7); L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19}).addTo(map); const LY={}; ['heat','stops','places','bases','terr','hull','over','route'].forEach(k=>LY[k]=L.layerGroup().addTo(map)); let heatLayer=null;
function drawMap(){
  Object.values(LY).forEach(l=>l.clearLayers()); if(heatLayer){map.removeLayer(heatLayer);heatLayer=null}
  const par=D.paradas.filter(keepR), pts=[];
  if(st.layers.heat&&par.length){heatLayer=L.heatLayer(par.map(p=>[p.lat,p.lng,Math.min(1,(p.min||10)/120)]),{radius:22,blur:18,maxZoom:14,gradient:{0.2:'#312e81',0.4:'#6366f1',0.6:'#22d3ee',0.8:'#f59e0b',1:'#ef4444'}}).addTo(map)}
  if(st.layers.stops)par.forEach(p=>{L.circleMarker([p.lat,p.lng],{radius:3+Math.min(10,Math.sqrt(p.min||10)/2),color:'#fff',weight:.6,fillColor:col(p.e),fillOpacity:.75}).addTo(LY.stops).bindPopup(`<b>${p.e}</b> · ${p.f}<br>${p.ll}–${p.sa} (${fmt(p.min,0)} min)<br>${p.lf||'Parada'}<br><small>${p.dir||''}</small>`);pts.push([p.lat,p.lng])});
  if(st.layers.places)D.lugares.filter(l=>keepE(l.e)&&!l.t.startsWith('Posible')).forEach(l=>{L.circleMarker([l.lat,l.lng],{radius:5+Math.min(18,Math.sqrt(l.mt||1)/3),color:'#fff',weight:1,fillColor:col(l.e),fillOpacity:.8}).addTo(LY.places).bindPopup(`<b>${l.e}</b><br>${l.t}<br>${l.v} veces · ${fmt(l.mt,0)} min · llega ${l.ll||''}<br><small>${l.dir||''}</small>`);pts.push([l.lat,l.lng])});
  if(st.layers.bases)Object.entries(D.bases).filter(([e])=>keepE(e)).forEach(([e,b])=>{L.marker(b,{icon:L.divIcon({className:'',iconSize:[22,22],iconAnchor:[11,11],html:`<div style="width:22px;height:22px;border-radius:50%;background:#ef4444;border:2px solid #fff;box-shadow:0 1px 4px #000;color:#fff;font-size:10px;font-weight:900;text-align:center;line-height:18px">B</div>`})}).addTo(LY.bases).bindPopup(`<b>${e}</b><br>Base / domicilio detectado`);pts.push(b)});
  if(st.layers.terr)Object.values(D.kpi).filter(k=>keepE(k.e)&&k.centro).forEach(k=>{L.circle(k.centro,{radius:k.radio_km*1000,color:col(k.e),weight:1.5,fillColor:col(k.e),fillOpacity:.07,dashArray:'4 4'}).addTo(LY.terr).bindPopup(`<b>${k.e}</b><br>Radio P80: ${k.radio_km} km · Area: ${k.area_km2} km2`)});
  if(st.layers.hull)Object.values(D.kpi).filter(k=>keepE(k.e)&&k.hull.length>=3).forEach(k=>{L.polygon(k.hull,{color:col(k.e),weight:1.5,fillOpacity:.08}).addTo(LY.hull).bindPopup(`<b>${k.e}</b><br>Area cubierta: ${k.area_km2} km2`)});
  if(st.layers.over)D.overlap.filter(o=>keepE(o.a)||keepE(o.b)).forEach(o=>{L.circleMarker([o.lat,o.lng],{radius:9,color:'#fbbf24',weight:2,fillColor:'#fbbf24',fillOpacity:.5}).addTo(LY.over).bindPopup(`<b>Solapamiento</b><br>${o.a} (${o.va}x) y ${o.b} (${o.vb}x)<br><small>${o.dir}</small>`)});
  if(st.layers.route&&st.det&&st.day){const ps=D.paradas.filter(p=>p.e===st.det&&p.f===st.day).sort((a,b)=>a.n-b.n); if(ps.length){const ll=ps.map(p=>[p.lat,p.lng]); const b=D.bases[st.det]; if(b&&ps[0].lf.includes('Posible')===false){} L.polyline(ll,{color:'#fbbf24',weight:4,opacity:.9}).addTo(LY.route); ps.forEach(p=>L.marker([p.lat,p.lng],{icon:L.divIcon({className:'',iconSize:[24,24],iconAnchor:[12,12],html:`<div style="width:24px;height:24px;border-radius:50%;background:#f59e0b;border:2px solid #fff;color:#0f172a;font-weight:900;font-size:11px;text-align:center;line-height:20px">${p.n}</div>`})}).addTo(LY.route).bindPopup(`<b>Parada ${p.n}</b> ${p.ll}–${p.sa} (${fmt(p.min,0)} min)<br>${p.lf||''}<br><small>${p.dir||''}</small>`)); map.fitBounds(ll,{padding:[40,40]}); return}}
  if(pts.length&&!st.day)map.fitBounds(pts,{padding:[20,20]});
  $('#legend').innerHTML=(st.color==='seg'?Object.entries(SEGC).map(([s,c])=>`<span><i style="background:${c}"></i>${s}</span>`).join(''):emps.filter(keepE).map(e=>`<span><i style="background:${EC[e]}"></i>${e}</span>`).join(''))+'<span><i style="background:#ef4444"></i>Base/domicilio</span><span><i style="background:#fbbf24"></i>Recorrido del dia / solapamiento</span>';
}
function render(){
  const rows=D.diario.filter(keepR), ks=Object.values(D.kpi).filter(k=>keepE(k.e)); $('#fInfo').textContent=`${ks.length} ejecutivos · ${rows.length} dias-persona`;
  const w=(f)=>{const g=ks.filter(k=>k.dias>=5);return g.length?g.reduce((a,k)=>a+f(k)*k.dias,0)/g.reduce((a,k)=>a+k.dias,0):null};
  const K=[['Indice operativo prom.',fmt(w(k=>k.indice),0),'0–100 (ver formula)'],['Cobertura GPS',fmt(w(k=>k.cobertura),0)+'%','dias con datos / dias habiles'],['Km por dia',fmt(w(k=>k.kmd)),'promedio ponderado'],['Jornada',fmt(w(k=>k.jornada))+' h','primer a ultimo registro'],
   ['Paradas productivas/dia',fmt(w(k=>k.prod_dia)),'≥20 min fuera de base'],['% tiempo en base',fmt(w(k=>k.pct_base),0)+'%','domicilio/base en horario laboral'],['Tiempos muertos',ks.reduce((a,k)=>a+k.muertos,0),'paradas ≥2 h fuera de base'],['Radio de operacion',fmt(w(k=>k.radio_km))+' km','P80 promedio'],
   ['Dias con exceso >80 km/h',fmt(w(k=>k.pct_exceso),0)+'%','conduccion segura'],['Km por parada productiva',fmt(w(k=>k.km_por_parada||0)),'eficiencia de desplazamiento']];
  $('#kpis').innerHTML=K.map(x=>`<div class="kpi"><div class="v">${x[1]}</div><div class="l">${x[0]}</div><div class="s">${x[2]}</div></div>`).join('');
  $('#concl').innerHTML=D.conclusiones.map((c,i)=>`<div class="it"><b>${i+1}.</b> ${c}</div>`).join('');
  const key=k=>{const v=k[st.sortK]; return v==null?-1e9:(typeof v==='string'&&/^\d\d:\d\d$/.test(v)?tm(v):v)};
  const sorted=[...ks].sort((a,b)=>{const x=key(a),y=key(b);return (x>y?1:x<y?-1:0)*st.sortD});
  $('#rank tbody').innerHTML=sorted.map(k=>`<tr data-e="${k.e}" ${st.det===k.e?'style="background:rgba(99,102,241,.12)"':''}><td><b>${k.e}</b><div class="note">${k.desde} → ${k.hasta}</div></td><td><span class="badge ${k.seg==='Residencial'?'b-res':'b-com'}">${k.seg==='Residencial'?'Res':'Com'}</span></td><td class="r"><span class="score" style="background:${scoreCol(k.indice)}">${k.indice}</span></td><td class="r">${k.cobertura}%</td><td class="r">${k.dias}</td><td class="r">${fmt(k.kmd)}</td><td class="r">${fmt(k.jornada)}</td><td class="r">${k.ini}</td><td class="r">${k.fin}</td><td class="r">${fmt(k.puntualidad_sd)}</td><td class="r">${fmt(k.prod_dia)}</td><td class="r">${k.prod_min_dia}</td><td class="r">${k.base?k.pct_base+'%':'<span class="note">sin base</span>'}</td><td class="r">${k.muertos} <span class="note">(${fmt(k.muertos_min/60,0)} h)</span></td><td class="r">${fmt(k.radio_km)}</td><td class="r">${fmt(k.area_km2,0)}</td><td class="r">${fmt(k.km_por_parada)}</td><td class="r">${k.pct_exceso}%</td><td class="r">${k.vmax_abs}</td></tr>`).join('');
  document.querySelectorAll('#rank tbody tr').forEach(tr=>tr.onclick=()=>{st.det=tr.dataset.e;st.day='';renderDetail();render()});
  $('#tEmp tbody').innerHTML=[...ks].sort((a,b)=>b.indice-a.indice).map(k=>`<tr data-e="${k.e}" style="cursor:pointer"><td><i style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${col(k.e)};margin-right:5px"></i>${k.e}</td><td class="r"><span class="score" style="background:${scoreCol(k.indice)}">${k.indice}</span></td><td class="r">${fmt(k.radio_km)}</td></tr>`).join('');
  document.querySelectorAll('#tEmp tbody tr').forEach(tr=>tr.onclick=()=>{st.det=tr.dataset.e;st.day='';const k=D.kpi[st.det];if(k.centro)map.setView(k.centro,11);renderDetail();render()});
  const g=ks.filter(k=>k.dias>=3);
  mk('cScatter',{type:'bubble',data:{datasets:g.map(k=>({label:k.e,data:[{x:k.kmd,y:k.prod_dia,r:6+k.indice/8}],backgroundColor:col(k.e)+'bb',borderColor:'#fff',borderWidth:.5}))},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>`${c.dataset.label}: ${fmt(c.raw.x)} km/dia · ${fmt(c.raw.y)} paradas prod./dia · indice ${D.kpi[c.dataset.label].indice}`}}},scales:{x:{title:{display:true,text:'km por dia'},beginAtZero:true},y:{title:{display:true,text:'paradas productivas por dia'},beginAtZero:true}}}});
  const gu=[...g].sort((a,b)=>b.pct_base-a.pct_base);
  mk('cUso',{type:'bar',data:{labels:gu.map(k=>k.e),datasets:[{label:'% en base/domicilio',data:gu.map(k=>k.pct_base),backgroundColor:'#ef4444bb',borderRadius:4},{label:'% detenido fuera de base',data:gu.map(k=>+(k.pct_detenido-k.pct_base).toFixed(1)),backgroundColor:'#f59e0bbb',borderRadius:4},{label:'% en movimiento',data:gu.map(k=>+(100-k.pct_detenido).toFixed(1)),backgroundColor:'#38bdf8bb',borderRadius:4}]},options:{indexAxis:'y',responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'bottom'}},scales:{x:{stacked:true,max:100},y:{stacked:true}}}});
  const gv=[...g].sort((a,b)=>b.pct_exceso-a.pct_exceso);
  mk('cVel',{type:'bar',data:{labels:gv.map(k=>k.e),datasets:[{label:'% dias con Vmax > '+D.umbrales.vel+' km/h',data:gv.map(k=>k.pct_exceso),backgroundColor:gv.map(k=>k.pct_exceso>=25?'#ef4444cc':'#6366f1cc'),borderRadius:5}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>`${c.raw}% de los dias · Vmax absoluta ${D.kpi[c.label].vmax_abs} km/h · promedio diario ${D.kpi[c.label].vmax_prom} km/h`}}},scales:{y:{beginAtZero:true,max:100}}}});
  const gt=[...g].sort((a,b)=>b.radio_km-a.radio_km);
  mk('cTerr',{type:'bar',data:{labels:gt.map(k=>k.e),datasets:[{label:'Radio P80 (km)',data:gt.map(k=>k.radio_km),backgroundColor:'#22d3eecc',borderRadius:5,yAxisID:'y'},{label:'Area cubierta (km2)',data:gt.map(k=>k.area_km2),type:'line',borderColor:'#f59e0b',backgroundColor:'#f59e0b',yAxisID:'y2',tension:.3}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'bottom'}},scales:{y:{beginAtZero:true,title:{display:true,text:'km'}},y2:{position:'right',beginAtZero:true,grid:{drawOnChartArea:false},title:{display:true,text:'km2'}}}}});
  renderDetail(); drawMap();
}
function renderDetail(){
  const e=st.det; if(!e){$('#detName').textContent='(selecciona un ejecutivo)';$('#cal').innerHTML='';return}
  const k=D.kpi[e]; $('#detName').textContent=`${e} · ${k.seg} · indice ${k.indice} · radio P80 ${k.radio_km} km · base ${k.base?'detectada':'no detectada'}`;
  const rows=D.diario.filter(r=>r.e===e&&(!st.ini||r.f>=st.ini)&&(!st.fin||r.f<=st.fin)).sort((a,b)=>a.f<b.f?-1:1); const mx=Math.max(...rows.map(r=>r.km||0),1);
  $('#cal').innerHTML=rows.map(r=>`<div data-f="${r.f}" title="${r.f} · ${fmt(r.km)} km · ${r.ini}-${r.fin} · ${r.p} paradas · vmax ${r.vmax}" style="background:rgba(99,102,241,${(0.1+0.85*(r.km||0)/mx).toFixed(2)});${st.day===r.f?'outline:2px solid #fbbf24':''}${(r.vmax||0)>D.umbrales.vel?';border-bottom:3px solid #ef4444':''}"><div style="font-size:9px;color:#cbd5e1">${r.f.slice(5)}</div><b>${fmt(r.km,0)}</b><div style="font-size:9px">${r.ini}</div></div>`).join('');
  document.querySelectorAll('#cal div[data-f]').forEach(d=>d.onclick=()=>{st.day=d.dataset.f;renderDetail();drawMap()});
  if(!st.day){$('#detDay').textContent='';$('#tl').innerHTML='<div class="note">Elige un dia (borde rojo = exceso de velocidad ese dia).</div>';return}
  const r=rows.find(x=>x.f===st.day); const ps=D.paradas.filter(p=>p.e===e&&p.f===st.day).sort((a,b)=>a.n-b.n);
  $('#detDay').textContent=st.day+(r?` · ${r.ini}–${r.fin} · ${fmt(r.km)} km · vmax ${r.vmax} km/h`:'');
  let h=`<div class="it"><div class="t">${r?r.ini:''}</div><div class="box">Primer registro GPS${r&&r.sb?` · sale de base ${r.sb}`:''}</div></div>`;
  ps.forEach(p=>{h+=`<div class="mv">⟶ ${fmt(p.tr,0)} min en desplazamiento</div><div class="it"><div class="t">${p.ll}</div><div class="box"><b>${p.lf||'Parada'}</b> · ${fmt(p.min,0)} min (hasta ${p.sa})${p.min>=D.umbrales.muerto&&!(p.lf||'').includes('Posible')?' <span style="color:#fca5a5">· tiempo muerto</span>':''}<div class="note">${p.dir||''}</div></div></div>`});
  h+=`<div class="it"><div class="t">${r?r.fin:''}</div><div class="box">Ultimo registro GPS${r&&r.lb?` · llega a base ${r.lb}`:''}</div></div>`; $('#tl').innerHTML=h;
}
document.querySelectorAll('#rank th').forEach(th=>th.onclick=()=>{const k=th.dataset.k;if(st.sortK===k)st.sortD*=-1;else{st.sortK=k;st.sortD=(k==='e'||k==='seg'||k==='ini'||k==='fin')?1:-1}render()});
render();
</script></body></html>'''
from datetime import datetime
html = HTML.replace('__DATA__', json.dumps(data, ensure_ascii=False, separators=(',', ':'))).replace('__FECHA__', datetime.now().strftime('%Y-%m-%d %H:%M'))
io.open(OUT, 'w', encoding='utf8').write(html)
print('HTML ->', OUT, f'({len(html)//1024} KB)')
print('\n=== CONCLUSIONES ===')
for i, c in enumerate(concl, 1): print(f'{i}. {c}')
print('\n=== KPI por ejecutivo (indice, cobertura, km/dia, jornada, prod/dia, %base, muertos, radio, %exceso) ===')
for k in ks: print(f"{k['e']:14} {k['seg'][:3]} idx={k['indice']:3} cob={k['cobertura']:3.0f}% km/d={k['kmd']:5.1f} jor={k['jornada']:5.2f} prod={k['prod_dia']:4.2f} base={k['pct_base']:4.1f}% muertos={k['muertos']:2} radio={k['radio_km']:5.1f} exc={k['pct_exceso']:3}% vmax={k['vmax_abs']}")
