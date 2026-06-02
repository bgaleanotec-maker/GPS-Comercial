"""Build script para Render - inicializa/actualiza BD."""
import os
os.environ['ENABLE_BACKGROUND_WORKER'] = 'false'

from app import create_app, db
from app.models import User, Setting

app = create_app()
with app.app_context():
    print("=== Creando/actualizando tablas ===")
    db.create_all()

    # Admin por defecto
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', full_name='Administrador',
                     email='admin@gps.com', role='admin')
        admin.set_password(os.environ.get('ADMIN_INITIAL_PASSWORD', 'admin123'))
        db.session.add(admin)
        print("Admin creado")

    # Settings por defecto
    defaults = {
        'start_time': '06:00', 'end_time': '20:00',
        'active_days': '1,2,3,4,5', 'visit_interval': '60',
        'report_time': '08:00', 'report_recipients': '',
        'sst_recipients': '', 'whatsapp_enabled': 'false',
        'ultramsg_instance_id': '', 'ultramsg_token': '',
        'whatsapp_report_time': '08:00',
    }
    for key, value in defaults.items():
        if not Setting.query.filter_by(key=key).first():
            db.session.add(Setting(key=key, value=value))

    db.session.commit()

    # === Reinicio masivo de claves (operacion de una sola vez) ===
    # Resetea la clave de TODOS los usuarios (excepto el/los admin) a 'Vanti2026*'.
    # Es idempotente: un flag en la tabla Setting garantiza que solo corre una vez,
    # asi futuros despliegues NO sobrescriben claves que los usuarios hayan cambiado.
    RESET_FLAG = 'pw_reset_vanti2026'
    if not Setting.query.filter_by(key=RESET_FLAG).first():
        reset_count = 0
        users = User.query.filter(
            User.username != 'admin',
            (User.role != 'admin') | (User.role.is_(None))
        ).all()
        for u in users:
            u.set_password('Vanti2026*')
            u.must_change_password = False
            reset_count += 1
        db.session.add(Setting(key=RESET_FLAG, value='done'))
        db.session.commit()
        print(f"=== Claves reiniciadas a 'Vanti2026*' para {reset_count} usuario(s) (admin excluido) ===")
    else:
        print("=== Reinicio de claves ya ejecutado previamente: omitido ===")

    print("=== Build completado ===")
