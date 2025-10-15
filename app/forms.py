# Ruta: SST/app/forms.py
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField, SelectField, FloatField, IntegerField, TextAreaField, SelectMultipleField, widgets
from wtforms.validators import DataRequired, ValidationError, Email, EqualTo
from flask_wtf.file import FileField, FileAllowed
from app.models import User

# --- Formularios de Autenticación ---
class LoginForm(FlaskForm):
    username = StringField('Usuario', validators=[DataRequired()])
    password = PasswordField('Contraseña', validators=[DataRequired()])
    remember_me = BooleanField('Recuérdame')
    submit = SubmitField('Iniciar Sesión')

# --- Formularios de Configuración ---
class RuleForm(FlaskForm):
    name = StringField('Nombre Descriptivo', validators=[DataRequired()])
    rule_type = SelectField(
        'Tipo de Regla',
        choices=[
            ('max_speed', 'Exceso de Velocidad (km/h)'),
            ('harsh_acceleration', 'Aceleración Brusca'),
            ('harsh_braking', 'Frenada Brusca')
        ],
        validators=[DataRequired()]
    )
    value = FloatField('Valor Límite (si aplica)', default=0, description='Ej. 60 para velocidad. Para aceleración/frenada, dejar en 0.')
    points = IntegerField('Puntos de Infracción', validators=[DataRequired()], default=1)
    submit = SubmitField('Crear Regla')

# Busca esta sección en forms.py y reemplázala

class SettingsForm(FlaskForm):
    start_time = StringField('Hora de Inicio de Operación', validators=[DataRequired()])
    end_time = StringField('Hora de Fin de Operación', validators=[DataRequired()])
    active_days = SelectMultipleField(
        'Días de Operación',
        choices=[
            ('1', 'Lunes'), ('2', 'Martes'), ('3', 'Miércoles'),
            ('4', 'Jueves'), ('5', 'Viernes'), ('6', 'Sábado'), ('0', 'Domingo')
        ],
        widget=widgets.ListWidget(prefix_label=False),
        option_widget=widgets.CheckboxInput()
    )
    visit_interval = IntegerField('Intervalo de Repetición de Visita (minutos)', default=60, validators=[DataRequired()])
    report_time = StringField('Hora de Envío del Reporte Diario', validators=[DataRequired()])
    report_recipients = TextAreaField('Correos para Reportes (separados por coma)')
    sst_recipients = TextAreaField('Correos para Alertas SST (separados por coma)')  # <-- NOMBRE CORRECTO
    submit = SubmitField('Guardar Configuración')
    send_report = SubmitField('Enviar Reporte de Hoy Ahora')

# --- Formularios Comerciales y de Visitas ---
class AllyForm(FlaskForm):
    name = StringField('Nombre del Aliado', validators=[DataRequired()])
    address = StringField('Dirección')
    latitude = FloatField('Latitud', validators=[DataRequired()])
    longitude = FloatField('Longitud', validators=[DataRequired()])
    category = StringField('Categoría', description='Ej: Carnes, Eléctricos, Retail')
    radius = IntegerField('Radio de Geozona (metros)', default=50, validators=[DataRequired()])
    submit = SubmitField('Guardar Aliado')

class VisitForm(FlaskForm):
    ally_id = SelectField('Aliado Visitado', coerce=int, validators=[DataRequired()])
    category = SelectField('Categoría de la Visita', choices=[
        ('Mantenimiento', 'Mantenimiento'),
        ('Formación', 'Formación'),
        ('Plan de Ventas', 'Plan de Ventas'),
        ('Otro', 'Otro')
    ], validators=[DataRequired()])
    observations = TextAreaField('Observaciones')
    evidence = FileField('Cargar Evidencia (Imagen o PDF)', validators=[FileAllowed(['jpg', 'png', 'jpeg', 'pdf'], '¡Solo se permiten imágenes y PDF!')])
    submit = SubmitField('Registrar Visita')

# --- NUEVO: Formulario de Creación de Usuario ---

class UserCreationForm(FlaskForm):
    username = StringField('Nombre de Usuario (para login)', validators=[DataRequired()])
    full_name = StringField('Nombre Completo del Empleado', validators=[DataRequired()])
    email = StringField('Email', validators=[DataRequired(), Email()])
    
    # === NUEVOS CAMPOS ===
    categoria = SelectField('Categoría', choices=[
        ('Vantilisto', 'Vantilisto'),
        ('Seguros', 'Seguros'),
        ('VantiMax', 'VantiMax'),
        ('Comercial', 'Comercial'),
        ('Residencial', 'Residencial'),
        ('Nueva Edificacion', 'Nueva Edificación')
    ], validators=[DataRequired()])
    
    filial = SelectField('Filial', choices=[
        ('Vanti', 'Vanti'),
        ('GOR', 'GOR'),
        ('Nacer', 'Nacer'),
        ('Cundi', 'Cundi')
    ], validators=[DataRequired()])
    
    submit = SubmitField('Crear Usuario')

    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user is not None:
            raise ValidationError('Por favor, utiliza un nombre de usuario diferente.')

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user is not None:
            raise ValidationError('Por favor, utiliza una dirección de email diferente.')







class VisitForm(FlaskForm):
    ally_id = SelectField('Aliado Visitado', coerce=int, validators=[DataRequired()])
    category = SelectField('Categoría de la Visita', choices=[
        ('Mantenimiento', 'Mantenimiento'),
        ('Formación', 'Formación'),
        ('Plan de Ventas', 'Plan de Ventas'),
        ('Otro', 'Otro')
    ], validators=[DataRequired()])
    observations = TextAreaField('Observaciones')
    evidence = FileField('Cargar Evidencia (Imagen o PDF)', validators=[FileAllowed(['jpg', 'png', 'jpeg', 'pdf'], '¡Solo se permiten imágenes y PDF!')])
    submit = SubmitField('Registrar Visita')
