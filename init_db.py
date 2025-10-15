from app import create_app, db
from app.models import User, Setting

def init_database():
    app = create_app()
    with app.app_context():
        print("Creando tablas...")
        db.create_all()
        
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(
                username='admin',
                full_name='Administrador',
                email='admin@gps.com',
                role='admin',
                categoria='Vantilisto',
                filial='Vanti'
            )
            admin.set_password('admin123')
            db.session.add(admin)
            print("✅ Usuario admin creado")
        
        default_settings = {
            'start_time': '06:00',
            'end_time': '20:00',
            'active_days': '1,2,3,4,5',
            'visit_interval': '60',
            'report_time': '08:00',
            'report_recipients': '',
            'sst_recipients': ''
        }
        
        for key, value in default_settings.items():
            setting = Setting.query.filter_by(key=key).first()
            if not setting:
                db.session.add(Setting(key=key, value=value))
        
        db.session.commit()
        print("✅ Base de datos inicializada")

if __name__ == '__main__':
    init_database()