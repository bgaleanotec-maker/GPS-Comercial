# Ruta: GPS_Comercial/app/models.py
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app import db, login
import secrets


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), index=True, unique=True)
    full_name = db.Column(db.String(120), index=True)
    email = db.Column(db.String(120), index=True, unique=True)
    password_hash = db.Column(db.String(256))
    role = db.Column(db.String(20), index=True, default='empleado')
    traccar_device_id = db.Column(db.Integer, index=True)

    # Clasificacion
    categoria = db.Column(db.String(50), index=True, default='Vantilisto')
    filial = db.Column(db.String(50), index=True, default='Vanti')

    # Direcciones
    home_address = db.Column(db.String(300))  # Direccion de residencia
    home_latitude = db.Column(db.Float)
    home_longitude = db.Column(db.Float)
    work_address = db.Column(db.String(300))  # Direccion de trabajo
    work_latitude = db.Column(db.Float)
    work_longitude = db.Column(db.Float)

    # Contacto
    phone_number = db.Column(db.String(20))  # Para WhatsApp (formato: 573001234567)

    # Estado del empleado
    employee_status = db.Column(db.String(30), default='activo')  # activo, vacaciones, incapacidad, licencia, retirado
    status_start_date = db.Column(db.Date)  # Inicio del estado (ej: inicio vacaciones)
    status_end_date = db.Column(db.Date)  # Fin del estado
    status_notes = db.Column(db.Text)  # Notas sobre el estado

    def __repr__(self):
        return f'<User {self.username}>'

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
    timestamp = db.Column(db.DateTime, index=True, default=lambda: datetime.now(timezone.utc))
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
    timestamp = db.Column(db.DateTime, index=True, default=lambda: datetime.now(timezone.utc))
    device_id = db.Column(db.Integer, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', name='fk_visit_user_id_user'))
    ally_id = db.Column(db.Integer, db.ForeignKey('ally.id'))
    is_manual = db.Column(db.Boolean, default=False)
    category = db.Column(db.String(100))
    observations = db.Column(db.Text)
    evidence_path = db.Column(db.String(200))

    # Clasificacion de movimiento
    movement_type = db.Column(db.String(20), default='vehicle')  # 'vehicle', 'walking', 'manual'
    avg_speed = db.Column(db.Float, default=0.0)

    ally = db.relationship('Ally', backref='visits')
    user = db.relationship('User', backref='visits')


class UserAllyAssignment(db.Model):
    """Asignacion de aliados/contratistas a usuarios."""
    __tablename__ = 'user_ally_assignment'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', name='fk_uaa_user_id'), nullable=False)
    ally_id = db.Column(db.Integer, db.ForeignKey('ally.id', name='fk_uaa_ally_id'), nullable=False)
    assignment_type = db.Column(db.String(30), default='aliado')  # 'aliado', 'contratista'
    assigned_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    is_active = db.Column(db.Boolean, default=True)

    user = db.relationship('User', backref='ally_assignments')
    ally = db.relationship('Ally', backref='user_assignments')


class Setting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.String(200), nullable=False)


# ============================================================
# MODELO API KEY
# ============================================================
class ApiKey(db.Model):
    __tablename__ = 'api_key'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    key = db.Column(db.String(64), unique=True, nullable=False, index=True)
    prefix = db.Column(db.String(8), nullable=False)

    user_id = db.Column(db.Integer, db.ForeignKey('user.id', name='fk_apikey_user_id_user'), nullable=False)
    user = db.relationship('User', backref='api_keys')

    permissions = db.Column(db.String(50), nullable=False, default='read')
    scopes = db.Column(db.String(200), nullable=False, default='devices')

    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=True)
    last_used_at = db.Column(db.DateTime, nullable=True)

    usage_count = db.Column(db.Integer, default=0, nullable=False)
    notes = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f'<ApiKey {self.prefix}... ({self.name})>'

    @staticmethod
    def generate_key():
        """Genera un token seguro con prefijo gps_ para identificacion visual."""
        raw = secrets.token_urlsafe(32)
        prefix = 'gps_' + raw[:8]
        full_key = 'gps_' + raw
        return prefix, full_key

    @property
    def is_expired(self):
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) > self.expires_at

    @property
    def status_label(self):
        if not self.is_active:
            return 'revocada'
        if self.is_expired:
            return 'expirada'
        return 'activa'

    @property
    def scopes_list(self):
        return [s.strip() for s in self.scopes.split(',') if s.strip()]

    def record_usage(self):
        self.last_used_at = datetime.now(timezone.utc)
        self.usage_count += 1


# ============================================================
# MODELO SCHEDULED TASK - Cronograma de actividades
# ============================================================
class ScheduledTask(db.Model):
    """Tarea agendada por un empleado (ej: visitar aliado X el lunes)."""
    __tablename__ = 'scheduled_task'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', name='fk_task_user_id'), nullable=False)
    ally_id = db.Column(db.Integer, db.ForeignKey('ally.id', name='fk_task_ally_id'), nullable=True)

    # Fecha y descripcion
    scheduled_date = db.Column(db.Date, nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    task_type = db.Column(db.String(30), default='visita')  # visita, reunion, gestion, otro

    # Tiempo minimo en sitio para marcar como cumplida (minutos)
    min_time_on_site = db.Column(db.Integer, default=30)

    # Tipo de validacion: 'gps' (requiere presencia GPS) o 'manual' (checklist, ej: cargar presupuesto)
    validation_type = db.Column(db.String(20), default='gps')  # gps, manual

    # Estado de la tarea
    status = db.Column(db.String(20), default='pendiente', index=True)
    # pendiente, cumplida, no_cumplida, en_progreso, cancelada

    # Validacion automatica
    auto_validated = db.Column(db.Boolean, default=False)  # True si el GPS la valido
    validated_at = db.Column(db.DateTime)  # Cuando se valido
    time_on_site_minutes = db.Column(db.Float, default=0)  # Minutos en el sitio

    # Metadata
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = db.Column(db.DateTime)
    notes = db.Column(db.Text)  # Notas del empleado al completar

    # Relaciones
    user = db.relationship('User', backref='scheduled_tasks')
    ally = db.relationship('Ally', backref='scheduled_tasks')

    @property
    def is_overdue(self):
        """Tarea vencida si la fecha ya paso y no esta cumplida."""
        if self.status in ('cumplida', 'cancelada'):
            return False
        today = datetime.now(timezone.utc).date()
        return self.scheduled_date < today

    @property
    def status_display(self):
        if self.status == 'cumplida':
            return 'Cumplida' if not self.auto_validated else 'Validada GPS'
        if self.is_overdue:
            return 'Vencida'
        return {
            'pendiente': 'Pendiente',
            'en_progreso': 'En Progreso',
            'no_cumplida': 'No Cumplida',
            'cancelada': 'Cancelada',
        }.get(self.status, self.status)


@login.user_loader
def load_user(id):
    return db.session.get(User, int(id))
