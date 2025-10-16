# Ruta: SST/app/scoring/routes.py
from flask import render_template, flash, redirect, url_for, abort, request
from app.scoring import bp
from flask_login import login_required, current_user
from app.models import Rule, Infraction, Setting
from app.forms import RuleForm, SettingsForm
from app import db
from datetime import datetime
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

        elif 'submit' in request.form:
            # Función auxiliar para convertir tiempo de forma segura
            def safe_time_convert(time_data):
                if isinstance(time_data, str):
                    # Intentar con formato HH:MM:SS primero
                    try:
                        return datetime.strptime(time_data, '%H:%M:%S').time()
                    except ValueError:
                        # Si falla, intentar con HH:MM
                        try:
                            return datetime.strptime(time_data, '%H:%M').time()
                        except ValueError:
                            # Si todo falla, devolver None
                            return None
                return time_data
            
            start_time = safe_time_convert(form.start_time.data)
            end_time = safe_time_convert(form.end_time.data)
            report_time = safe_time_convert(form.report_time.data)
            
            if not all([start_time, end_time, report_time]):
                flash('Error en el formato de las horas. Por favor verifica los datos.', 'danger')
                return redirect(url_for('scoring.manage_settings'))
            
            settings_to_save = {
                'start_time': start_time.strftime('%H:%M'),
                'end_time': end_time.strftime('%H:%M'),
                'visit_interval': str(form.visit_interval.data),
                'report_time': report_time.strftime('%H:%M'),
                'report_recipients': form.report_recipients.data.strip() if form.report_recipients.data else '',
                'active_days': ",".join(form.active_days.data),
                'sst_recipients': form.sst_recipients.data.strip() if form.sst_recipients.data else ''
            }

            for key, value in settings_to_save.items():
                setting = Setting.query.filter_by(key=key).first()
                if setting:
                    setting.value = value
                    print(f"✅ Actualizado: {key} = {value}")
                else:
                    new_setting = Setting(key=key, value=value)
                    db.session.add(new_setting)
                    print(f"✅ Creado: {key} = {value}")
            
            db.session.commit()
            flash('La configuración ha sido guardada con éxito.', 'success')
            return redirect(url_for('scoring.manage_settings'))

    if request.method == 'GET':
        settings_query = Setting.query.all()
        settings = {s.key: s.value for s in settings_query}
        
        form.start_time.data = datetime.strptime(settings.get('start_time', '06:00'), '%H:%M').time()
        form.end_time.data = datetime.strptime(settings.get('end_time', '20:00'), '%H:%M').time()
        form.active_days.data = settings.get('active_days', '1,2,3,4,5').split(',')
        form.visit_interval.data = int(settings.get('visit_interval', '60'))
        form.report_time.data = datetime.strptime(settings.get('report_time', '08:00'), '%H:%M').time()
        form.report_recipients.data = settings.get('report_recipients', '')
        form.sst_recipients.data = settings.get('sst_recipients', '')

    return render_template('scoring/manage_settings.html', title='Configuración General', form=form)