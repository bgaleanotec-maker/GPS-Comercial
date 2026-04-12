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
    print("=== Build completado ===")
