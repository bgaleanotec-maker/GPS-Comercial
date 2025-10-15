# Ruta: SST/app/models.py
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app import db, login
from datetime import datetime, time

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), index=True, unique=True)
    full_name = db.Column(db.String(120), index=True)
    email = db.Column(db.String(120), index=True, unique=True)
    password_hash = db.Column(db.String(256))
    role = db.Column(db.String(20), index=True, default='empleado')
    traccar_device_id = db.Column(db.Integer, index=True)
    
    # === NUEVOS CAMPOS DE CLASIFICACIÓN ===
    categoria = db.Column(db.String(50), index=True, default='Vantilisto')  # Vantilisto, Seguros, VantiMax, Comercial, Residencial, Nueva Edificacion
    filial = db.Column(db.String(50), index=True, default='Vanti')  # Vanti, GOR, Nacer, Cundi

    def __repr__(self):
        return '<User {}>'.format(self.username)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Rule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    rule_type = db.Column(db.String(50), nullable=False)
    value = db.Column(db.Float, nullable=False)
    points = db.Column(db.Integer, nullable=False, default=1)
    is_active = db.Column(db.Boolean, default=True)

    def __repr__(self):
        return f'<Rule {self.name}>'

class Infraction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow)
    device_id = db.Column(db.Integer, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    rule_id = db.Column(db.Integer, db.ForeignKey('rule.id'))
    measured_value = db.Column(db.String(100))
    user = db.relationship('User', backref='infractions')
    rule = db.relationship('Rule', backref='infractions')

    def __repr__(self):
        return f'<Infraction by Device {self.device_id} at {self.timestamp}>'

class Ally(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(140), nullable=False)
    address = db.Column(db.String(200))
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(50), index=True)
    radius = db.Column(db.Integer, default=50)

class Visit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow)
    device_id = db.Column(db.Integer, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', name='fk_visit_user_id_user'))
    ally_id = db.Column(db.Integer, db.ForeignKey('ally.id'))
    is_manual = db.Column(db.Boolean, default=False)
    category = db.Column(db.String(100))
    observations = db.Column(db.Text)
    evidence_path = db.Column(db.String(200))
    
    # === CAMPOS DE CLASIFICACIÓN DE MOVIMIENTO ===
    movement_type = db.Column(db.String(20), default='vehicle')  # 'vehicle', 'walking', 'manual'
    avg_speed = db.Column(db.Float, default=0.0)
    
    ally = db.relationship('Ally', backref='visits')
    user = db.relationship('User', backref='visits')

class Setting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.String(200), nullable=False)

@login.user_loader
def load_user(id):
    return User.query.get(int(id))