# -*- coding: utf-8 -*-
"""Analisis puntual de uso del tiempo de los ejecutivos (Excel + CSV).
Uso:  python ops/analisis_tiempos/run_analisis.py 2026-09-01 2026-10-06 [salida_dir]
Toma las posiciones reales de Traccar (credenciales de .env), horario laboral de la
configuracion (06:00-20:00 L-V) y los aliados registrados. Excluye el dispositivo BRAGPS (Brayan)."""
import os, sys, io
from datetime import date, datetime
from types import SimpleNamespace
os.environ['ENABLE_BACKGROUND_WORKER'] = 'false'
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.models import Ally
import app.traccar as tr
import tracking_export as te

EXCLUIR_DISPOSITIVOS = {'BRAGPS'}
# Nombres de aliados de demostracion (semilla local) que no son reales
DEMO_ALLIES = ('Aliado Centro', 'Contratista Norte', 'Aliado Chapinero', 'Oficina Calle 72', 'Contratista Sur', 'Aliado Suba')

start_d = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2026, 9, 1)
end_d = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else date.today()
out_dir = sys.argv[3] if len(sys.argv) > 3 else os.path.join(os.path.expanduser('~'), 'OneDrive', 'Desktop')

app = create_app()
with app.app_context():
    devices = [d for d in (tr.get_devices() or []) if not d.get('disabled') and d['name'] not in EXCLUIR_DISPOSITIVOS]
    users = [SimpleNamespace(id=-d['id'], username=d['name'], full_name=d['name'], traccar_device_id=d['id']) for d in devices]
    print(f'Empleados (dispositivos): {len(users)} -> {[u.username for u in users]}')
    # Aliados reales de produccion (exportados de la BD de Render a aliados_produccion.json).
    # Oficinas = nombre con 'Vanti' o 'Calima'; el resto son aliados.
    import json
    jpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'aliados_produccion.json')
    real = [SimpleNamespace(**a) for a in json.load(open(jpath, encoding='utf8'))]
    print('Aliados usados:', len(real), '| oficinas:', [a.name for a in real if a.tipo == 'Oficina'])
    orig_query = Ally.query
    class _Q:   # el modulo consulta Ally.query.all(); se le entrega solo la lista real
        def all(self): return real
    Ally.query = _Q()
    try:
        ds = te.build_tracking_dataset(users, start_d, end_d, params={'reverse_geocode': True}, fetch_budget_s=600)
    finally:
        Ally.query = orig_query
    for k, v in ds.items():
        print(f'  {k}: {len(v)} filas')
    base = f'Analisis_Tiempos_Ejecutivos_{start_d}_a_{end_d}'
    xlsx = os.path.join(out_dir, base + '.xlsx'); zipp = os.path.join(out_dir, base + '_csv.zip')
    open(xlsx, 'wb').write(te.to_xlsx(ds)); open(zipp, 'wb').write(te.to_csv_zip(ds))
    print('OK ->', xlsx); print('OK ->', zipp)
