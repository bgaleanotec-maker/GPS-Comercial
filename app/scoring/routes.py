# Ruta: SST/app/scoring/routes.py
from flask import render_template, flash, redirect, url_for, abort, request
from app.scoring import bp
from flask_login import login_required, current_user
from app.models import Rule, Infraction, Setting
from app.forms import RuleForm, SettingsForm
from app import db
from datetime import datetime, time
from app.reporting_logic import generate_and_send_daily_report

@bp.route('/rules', methods=['GET', 'POST'])
@login_required
def manage_rules():
    """
    Muestra la página para gestionar las reglas.
    Permite a los administradores ver las reglas existentes y crear nuevas.
    """
    if current_user.role != 'admin':
        abort(403)
    
    form = RuleForm()
    if form.validate_on_submit():
        rule = Rule(
            name=form.name.data,
            rule_type=form.rule_type.data,
            value=form.value.data,
            points=form.points.data
        )
        db.session.add(rule)
        db.session.commit()
        flash('La nueva regla ha sido creada con éxito.', 'success')
        return redirect(url_for('scoring.manage_rules'))
    
    rules = Rule.query.order_by(Rule.name).all()
    return render_template('scoring/manage_rules.html', title='Configurar Reglas', form=form, rules=rules)

@bp.route('/rule/<int:rule_id>/delete', methods=['POST'])
@login_required
def delete_rule(rule_id):
    """
    Procesa la eliminación de una regla.
    """
    if current_user.role != 'admin':
        abort(403)
    rule_to_delete = Rule.query.get_or_404(rule_id)
    
    # Primero borramos las infracciones asociadas para evitar errores de base de datos
    Infraction.query.filter_by(rule_id=rule_id).delete()
    
    db.session.delete(rule_to_delete)
    db.session.commit()
    flash('La regla ha sido eliminada.', 'info')
    return redirect(url_for('scoring.manage_rules'))

@bp.route('/settings', methods=['GET', 'POST'])
@login_required
def manage_settings():
    """
    Gestiona la configuración general de la aplicación.
    """
    if current_user.role != 'admin':
        abort(403)
    
    form = SettingsForm()
    
    if form.validate_on_submit():
        if 'send_report' in request.form:
            flash('Iniciando envío manual del reporte...', 'info')
            if generate_and_send_daily_report():
                flash('Reporte diario enviado exitosamente.', 'success')
            else:
                flash('Hubo un error al enviar el reporte. Revisa la configuración y los logs.', 'danger')
            return redirect(url_for('scoring.manage_settings'))

        elif 'submit' in request.form:  # <-- CAMBIO: Detecta el botón correcto
            # Convertir objetos time a strings
            start_time_str = form.start_time.data.strftime('%H:%M') if isinstance(form.start_time.data, time) else form.start_time.data
            end_time_str = form.end_time.data.strftime('%H:%M') if isinstance(form.end_time.data, time) else form.end_time.data
            report_time_str = form.report_time.data.strftime('%H:%M') if isinstance(form.report_time.data, time) else form.report_time.data
            
            settings_to_save = {
                'start_time': start_time_str,
                'end_time': end_time_str,
                'visit_interval': str(form.visit_interval.data),
                'report_time': report_time_str,
                'report_recipients': form.report_recipients.data,
                'active_days': ",".join(form.active_days.data),
                'sst_recipients': form.sst_recipients.data  # <-- NOMBRE CORRECTO
            }

            for key, value in settings_to_save.items():
                setting = Setting.query.filter_by(key=key).first()
                if setting:
                    setting.value = value
                else:
                    new_setting = Setting(key=key, value=value)
                    db.session.add(new_setting)
            
            db.session.commit()
            flash('La configuración ha sido guardada con éxito.', 'success')
            return redirect(url_for('scoring.manage_settings'))

    if request.method == 'GET':
        settings_query = Setting.query.all()
        settings = {s.key: s.value for s in settings_query}
        
        # Cargar valores al formulario con manejo de errores
        try:
            form.start_time.data = datetime.strptime(settings.get('start_time', '06:00'), '%H:%M').time()
        except:
            form.start_time.data = datetime.strptime('06:00', '%H:%M').time()
        
        try:
            form.end_time.data = datetime.strptime(settings.get('end_time', '20:00'), '%H:%M').time()
        except:
            form.end_time.data = datetime.strptime('20:00', '%H:%M').time()
        
        form.active_days.data = settings.get('active_days', '1,2,3,4,5').split(',')
        form.visit_interval.data = int(settings.get('visit_interval', '60'))
        
        try:
            form.report_time.data = datetime.strptime(settings.get('report_time', '08:00'), '%H:%M').time()
        except:
            form.report_time.data = datetime.strptime('08:00', '%H:%M').time()
        
        form.report_recipients.data = settings.get('report_recipients', '')
        form.sst_recipients.data = settings.get('sst_recipients', '')  # <-- NOMBRE CORRECTO

    return render_template('scoring/manage_settings.html', title='Configuración General', form=form)