# Ruta: SST/app/commercial/routes.py
from flask import render_template, flash, redirect, url_for, abort, request
from app.commercial import bp
from flask_login import login_required, current_user
from app.models import Ally, Visit
from app.forms import AllyForm
from app import db

@bp.route('/allies', methods=['GET', 'POST'])
@login_required
def manage_allies():
    """
    Muestra la página para gestionar los aliados comerciales.
    Permite a los administradores ver, crear y eliminar aliados.
    """
    # Solo los administradores pueden acceder a esta página
    if current_user.role != 'admin':
        abort(403)
    
    form = AllyForm()
    if form.validate_on_submit():
        # Lógica para crear un nuevo aliado, ahora incluyendo el radio
        ally = Ally(
            name=form.name.data,
            address=form.address.data,
            latitude=form.latitude.data,
            longitude=form.longitude.data,
            category=form.category.data,
            filial=form.filial.data,
            radius=form.radius.data,
        )
        db.session.add(ally)
        db.session.commit()
        flash('El nuevo aliado ha sido creado con éxito.', 'success')
        return redirect(url_for('commercial.manage_allies'))
    
    # Obtenemos todos los aliados para mostrarlos en la tabla
    allies = Ally.query.order_by(Ally.name).all()
    return render_template('commercial/manage_allies.html', title='Gestionar Aliados', form=form, allies=allies)

@bp.route('/ally/<int:ally_id>/edit', methods=['POST'])
@login_required
def edit_ally(ally_id):
    """Edita un aliado/contratista existente (solo admin)."""
    if current_user.role != 'admin':
        abort(403)

    ally = Ally.query.get_or_404(ally_id)

    name = (request.form.get('name') or '').strip()
    if not name:
        flash('El nombre del aliado es obligatorio.', 'danger')
        return redirect(url_for('commercial.manage_allies'))

    ally.name = name
    ally.address = (request.form.get('address') or '').strip()
    ally.category = request.form.get('category') or ally.category
    ally.filial = request.form.get('filial') or ally.filial

    # Lat/Lng y radio: solo se actualizan si vienen valores validos
    try:
        if request.form.get('latitude'):
            ally.latitude = float(request.form.get('latitude'))
        if request.form.get('longitude'):
            ally.longitude = float(request.form.get('longitude'))
        if request.form.get('radius'):
            ally.radius = int(request.form.get('radius'))
    except (ValueError, TypeError):
        flash('Latitud, longitud y radio deben ser numericos.', 'danger')
        return redirect(url_for('commercial.manage_allies'))

    db.session.commit()
    flash(f'Aliado "{ally.name}" actualizado con exito.', 'success')
    return redirect(url_for('commercial.manage_allies'))


@bp.route('/ally/<int:ally_id>/delete', methods=['POST'])
@login_required
def delete_ally(ally_id):
    """
    Procesa la eliminación de un aliado comercial.
    """
    if current_user.role != 'admin':
        abort(403)
    
    ally_to_delete = Ally.query.get_or_404(ally_id)
    
    # Para mantener la integridad de la base de datos, primero borramos las visitas asociadas
    Visit.query.filter_by(ally_id=ally_id).delete()
    
    db.session.delete(ally_to_delete)
    db.session.commit()
    flash('El aliado y todas sus visitas asociadas han sido eliminados.', 'info')
    return redirect(url_for('commercial.manage_allies'))

