"""Script para crear datos de prueba de concepto."""
from app import create_app, db
from app.models import User, Ally, Visit, Setting, UserAllyAssignment
from datetime import datetime, timezone, timedelta
import pytz

app = create_app()
with app.app_context():
    # 1. Settings
    default_settings = {
        'start_time': '06:00', 'end_time': '20:00',
        'active_days': '1,2,3,4,5', 'visit_interval': '60',
        'report_time': '08:00', 'report_recipients': '',
        'sst_recipients': '', 'whatsapp_enabled': 'false',
        'ultramsg_instance_id': '', 'ultramsg_token': '',
        'whatsapp_report_time': '08:00',
    }
    for key, value in default_settings.items():
        if not Setting.query.filter_by(key=key).first():
            db.session.add(Setting(key=key, value=value))
    db.session.commit()
    print("Settings OK")

    # 2. Admin
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', full_name='Administrador', email='admin@gps.com', role='admin')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        print("Admin creado")

    # 3. BRA
    bra = User.query.filter_by(username='bra').first()
    if not bra:
        bra = User(
            username='bra', full_name='BRA GPS', email='bra@gps.com',
            role='empleado', traccar_device_id=1, categoria='Comercial', filial='Vanti',
            home_address='Calle 66C #60-65, Bogota', home_latitude=4.6764, home_longitude=-74.0943,
            work_address='Calle 72 #5-38, Bogota', work_latitude=4.6584, work_longitude=-74.0558,
            phone_number='573001234567', employee_status='activo'
        )
        bra.set_password('bra2025')
        db.session.add(bra)
        db.session.commit()
        print(f"BRA creado: id={bra.id}")
    else:
        bra.home_address = 'Calle 66C #60-65, Bogota'
        bra.home_latitude = 4.6764
        bra.home_longitude = -74.0943
        bra.work_address = 'Calle 72 #5-38, Bogota'
        bra.work_latitude = 4.6584
        bra.work_longitude = -74.0558
        bra.traccar_device_id = 1
        bra.employee_status = 'activo'
        db.session.commit()
        print(f"BRA actualizado: id={bra.id}")

    # 4. Otros empleados desde Traccar
    traccar_employees = [
        ('ssarmiento', 'S. Sarmiento', 19, 'Comercial'),
        ('freyes', 'F. Reyes', 23, 'Residencial'),
        ('cmoreno', 'C. Moreno', 24, 'Vantilisto'),
        ('mcharry', 'M. Charry', 25, 'Comercial'),
        ('ohurtado', 'O. Hurtado', 26, 'Seguros'),
        ('yrozo', 'Y. Rozo', 27, 'VantiMax'),
        ('ysanchez', 'Y. Sanchez', 28, 'Nueva Edificacion'),
    ]
    for uname, fname, dev, cat in traccar_employees:
        if not User.query.filter_by(username=uname).first():
            u = User(username=uname, full_name=fname, email=f"{uname}@gps.com",
                     role='empleado', traccar_device_id=dev, categoria=cat, filial='Vanti',
                     employee_status='activo')
            u.set_password('Vanti2025')
            db.session.add(u)
    db.session.commit()
    print(f"Empleados: {User.query.count()}")

    # 5. Aliados Bogota
    aliados = [
        ('Aliado Centro - Carrera 7', 'Carrera 7 #32-16, Bogota', 4.6253, -74.0655, 'Comercial', 100),
        ('Contratista Norte - Usaquen', 'Calle 116 #15-20, Bogota', 4.6984, -74.0317, 'Contratista', 150),
        ('Aliado Chapinero', 'Calle 53 #13-40, Bogota', 4.6413, -74.0637, 'Comercial', 80),
        ('Oficina Calle 72 (Trabajo BRA)', 'Calle 72 #5-38, Bogota', 4.6584, -74.0558, 'Oficina', 100),
        ('Contratista Sur - Kennedy', 'Av Boyaca #38A Sur, Bogota', 4.6087, -74.1489, 'Contratista', 120),
        ('Aliado Suba', 'Av Suba #115-34, Bogota', 4.7078, -74.0527, 'Residencial', 100),
    ]
    for name, addr, lat, lon, cat, rad in aliados:
        if not Ally.query.filter_by(name=name).first():
            db.session.add(Ally(name=name, address=addr, latitude=lat, longitude=lon, category=cat, radius=rad))
    db.session.commit()
    print(f"Aliados: {Ally.query.count()}")

    # 6. Asignar aliados a BRA
    bra = User.query.filter_by(username='bra').first()
    for ally in Ally.query.filter(Ally.category.in_(['Comercial', 'Oficina'])).all():
        if not UserAllyAssignment.query.filter_by(user_id=bra.id, ally_id=ally.id).first():
            atype = 'contratista' if ally.category == 'Contratista' else 'aliado'
            db.session.add(UserAllyAssignment(user_id=bra.id, ally_id=ally.id, assignment_type=atype))
    db.session.commit()
    print(f"Asignaciones BRA: {UserAllyAssignment.query.filter_by(user_id=bra.id).count()}")

    # 7. Simular visitas
    colombia_tz = pytz.timezone('America/Bogota')
    now = datetime.now(colombia_tz)
    allies = Ally.query.all()
    vc = 0
    for days_ago in range(7):
        day = now - timedelta(days=days_ago)
        for hour in [9, 11, 14]:
            if vc >= 15:
                break
            vt = day.replace(hour=hour, minute=30)
            ally = allies[vc % len(allies)]
            v = Visit(timestamp=vt.astimezone(pytz.utc), device_id=1, user_id=bra.id,
                      ally_id=ally.id, is_manual=False, movement_type='vehicle', avg_speed=25.5)
            db.session.add(v)
            vc += 1
    # Visitas manuales
    for i in range(3):
        day = now - timedelta(days=i)
        vt = day.replace(hour=16, minute=0)
        ally = allies[i % len(allies)]
        v = Visit(timestamp=vt.astimezone(pytz.utc), device_id=1, user_id=bra.id,
                  ally_id=ally.id, is_manual=True, movement_type='walking', avg_speed=4.2,
                  observations=f'Visita manual prueba dia {i+1}', category='seguimiento')
        db.session.add(v)
    db.session.commit()
    print(f"Visitas: {Visit.query.count()}")

    # 8. Resumen
    print("\n=== PRUEBA DE CONCEPTO LISTA ===")
    print(f"Usuarios: {User.query.count()} | Aliados: {Ally.query.count()} | Visitas: {Visit.query.count()}")
    bra = User.query.filter_by(username='bra').first()
    print(f"BRA: device=1(BRAGPS) | Casa: {bra.home_address} | Trabajo: {bra.work_address}")
    print(f"BRA asignaciones: {UserAllyAssignment.query.filter_by(user_id=bra.id).count()} aliados")

    # Verificar posicion actual de BRAGPS
    from app.traccar import get_latest_position
    pos = get_latest_position(1)
    if pos:
        from app.utils import haversine_distance
        dist_home = haversine_distance(pos['latitude'], pos['longitude'], bra.home_latitude, bra.home_longitude)
        dist_work = haversine_distance(pos['latitude'], pos['longitude'], bra.work_latitude, bra.work_longitude)
        print(f"\nPosicion actual BRAGPS: {pos['latitude']:.6f}, {pos['longitude']:.6f}")
        print(f"  Distancia a CASA: {dist_home:.0f} metros ({dist_home/1000:.2f} km)")
        print(f"  Distancia a TRABAJO: {dist_work:.0f} metros ({dist_work/1000:.2f} km)")
        print(f"  Velocidad: {pos.get('speed', 0) * 1.852:.1f} km/h")
        print(f"  Ultima posicion: {pos.get('fixTime', '?')}")

        # Verificar cercania a aliados
        print("\nDistancias a aliados:")
        for ally in allies:
            dist = haversine_distance(pos['latitude'], pos['longitude'], ally.latitude, ally.longitude)
            dentro = " <-- DENTRO DEL RADIO!" if dist <= ally.radius else ""
            print(f"  {ally.name}: {dist:.0f}m (radio: {ally.radius}m){dentro}")
