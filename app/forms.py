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
    sst_recipients = TextAreaField('Correos para Alertas SST (separados por coma)')  # ← CRÍTICO: debe ser sst_recipients
    submit = SubmitField('Guardar Configuración')
    send_report = SubmitField('Enviar Reporte de Hoy Ahora')
    
# --- Formularios Comerciales y de Visitas ---
class AllyForm(FlaskForm):
    name = StringField('Nombre del Aliado', validators=[DataRequired()])
    address = StringField('Direccion')
    latitude = FloatField('Latitud', validators=[DataRequired()])
    longitude = FloatField('Longitud', validators=[DataRequired()])
    category = SelectField('Categoria', choices=[
        ('Contratista', 'Contratista'),
        ('Cliente', 'Cliente'),
        ('Oficina', 'Oficina'),
        ('Punto de Venta', 'Punto de Venta'),
        ('Otro', 'Otro'),
    ])
    filial = SelectField('Filial', choices=[
        ('Vanti', 'Vanti'), ('Cundi', 'Cundi'), ('GOR', 'GOR'), ('Nacer', 'Nacer'),
    ])
    radius = IntegerField('Radio de Geozona (metros)', default=50, validators=[DataRequired()])
    submit = SubmitField('Guardar Aliado')

ACTIVITY_TYPES = [
    ('Visita Cliente', 'Visita Cliente'),
    ('Visita Prolongue', 'Visita Prolongue'),
    ('Visita Contratista', 'Visita Contratista'),
    ('Zonas de Avance', 'Zonas de Avance'),
    ('Imposibilidades', 'Imposibilidades'),
    ('Reunion citada Vanti', 'Reunion citada Vanti'),
    ('Evento especial', 'Evento especial'),
    ('Trabajo administrativo', 'Trabajo administrativo'),
    ('Vacaciones - Permiso especial', 'Vacaciones - Permiso especial'),
    ('Incapacidad', 'Incapacidad'),
]

class VisitForm(FlaskForm):
    ally_id = SelectField('Aliado Visitado', coerce=int, validators=[DataRequired()])
    category = SelectField('Tipo de Actividad', choices=ACTIVITY_TYPES, validators=[DataRequired()])
    observations = TextAreaField('Observaciones')
    evidence = FileField('Cargar Evidencia (Imagen o PDF)', validators=[FileAllowed(['jpg', 'png', 'jpeg', 'pdf'], 'Solo se permiten imagenes y PDF!')])
    submit = SubmitField('Registrar Visita')

# --- Formulario de Edicion de Usuario ---

class UserEditForm(FlaskForm):
    """Formulario para editar usuario con direcciones y estado."""
    full_name = StringField('Nombre Completo', validators=[DataRequired()])
    email = StringField('Email', validators=[DataRequired(), Email()])
    phone_number = StringField('Telefono WhatsApp')
    home_address = StringField('Direccion Residencia')
    work_address = StringField('Direccion Trabajo')
    categoria = SelectField('Categoria', choices=[
        ('Todas', 'Todas (Todas las gerencias)'),
        ('Vantilisto', 'Vantilisto'), ('Seguros', 'Seguros'), ('VantiMax', 'VantiMax'),
        ('Comercial', 'Comercial'), ('Residencial', 'Residencial'), ('Nueva Edificacion', 'Nueva Edificacion'),
        ('Saturacion', 'Saturacion'),
    ])
    filial = SelectField('Filial', choices=[
        ('Todas', 'Todas (Todas las filiales)'),
        ('Vanti', 'Vanti'), ('GOR', 'GOR'), ('Nacer', 'Nacer'), ('Cundi', 'Cundi')
    ])
    employee_status = SelectField('Estado', choices=[
        ('activo', 'Activo'), ('vacaciones', 'Vacaciones'), ('incapacidad', 'Incapacidad'),
        ('licencia', 'Licencia'), ('retirado', 'Retirado')
    ])
    role = SelectField('Rol', choices=[
        ('empleado', 'Empleado'), ('lider', 'Lider de Negocio'), ('admin', 'Administrador')
    ])
    submit = SubmitField('Guardar')

# --- NUEVO: Formulario de Creación de Usuario ---

class UserCreationForm(FlaskForm):
    username = StringField('Nombre de Usuario (para login)', validators=[DataRequired()])
    full_name = StringField('Nombre Completo del Empleado', validators=[DataRequired()])
    email = StringField('Email', validators=[DataRequired(), Email()])
    
    # === NUEVOS CAMPOS ===
    categoria = SelectField('Categoría', choices=[
        ('Todas', 'Todas (Todas las gerencias)'),
        ('Vantilisto', 'Vantilisto'),
        ('Seguros', 'Seguros'),
        ('VantiMax', 'VantiMax'),
        ('Comercial', 'Comercial'),
        ('Residencial', 'Residencial'),
        ('Nueva Edificacion', 'Nueva Edificación'),
        ('Saturacion', 'Saturación'),
    ], validators=[DataRequired()])

    filial = SelectField('Filial', choices=[
        ('Todas', 'Todas (Todas las filiales)'),
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





class VisitFormDuplicate(FlaskForm):
    """Formulario de visita duplicado (legacy, usar VisitForm principal)."""
    ally_id = SelectField('Aliado Visitado', coerce=int, validators=[DataRequired()])
    category = SelectField('Tipo de Actividad', choices=ACTIVITY_TYPES, validators=[DataRequired()])
    observations = TextAreaField('Observaciones')
    evidence = FileField('Cargar Evidencia (Imagen o PDF)', validators=[FileAllowed(['jpg', 'png', 'jpeg', 'pdf'], '¡Solo se permiten imágenes y PDF!')])
    submit = SubmitField('Registrar Visita')