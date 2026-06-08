from flask import Blueprint, request, jsonify, redirect
from datetime import datetime
import random
from flask_login import login_required
from extensions import db
from models.equipo import Equipo, FiltroEquipo
from models.orden_trabajo import OrdenTrabajo
from models.historial import HistorialLectura, CompraRepuesto
from models.personal import Personal, Mecanico, RegistroUsoEquipo
from utils.formatters import clean_int, clean_float

api_bp = Blueprint('api', __name__)

@api_bp.route('/update_kanban', methods=['POST'])
@login_required
def update_kanban():
    data = request.json
    ot = OrdenTrabajo.query.get(data.get('ot_id'))
    if ot:
        ot.estado = data.get('estado')
        db.session.commit()
    return jsonify({"status": "success"})

@api_bp.route('/api/add_record', methods=['POST'])
@login_required
def add_record():
    tabla = request.form.get('tabla')
    codigo = request.form.get('codigo')
    
    if tabla == 'lectura':
        val = clean_int(request.form.get('valor'))
        ctrl = request.form.get('control', 'HR')
        db.session.add(HistorialLectura(codigo_equipo=codigo, horometro=val if ctrl == 'HR' else 0, kilometraje=val if ctrl == 'KM' else 0, observacion=request.form.get('observacion', ''), fecha=datetime.now()))
        eq = Equipo.query.filter_by(codigo=codigo).first()
        if eq: eq.lectura_actual = val

    elif tabla == 'ot':
        eq = Equipo.query.filter_by(codigo=codigo).first()
        lectura_req = clean_int(request.form.get('lectura'))
        if lectura_req == 0 and eq: lectura_req = eq.lectura_actual
        
        folio_req = request.form.get('folio', '').strip()
        if not folio_req:
            ultima_ot_global = OrdenTrabajo.query.order_by(OrdenTrabajo.id.desc()).first()
            siguiente_id = (ultima_ot_global.id + 1) if ultima_ot_global else 1
            folio_req = f"OT-{siguiente_id:05d}"
            
        db.session.add(OrdenTrabajo(
            codigo_equipo=codigo, 
            folio=folio_req, 
            tipo_ot='Preventiva', 
            tipo_mantencion=request.form.get('tipo', 'PM1'), 
            lectura=lectura_req, 
            costo_mantencion_clp=clean_float(request.form.get('costo'), 0.0), 
            estado=request.form.get('estado', 'Pendiente'), 
            mecanico=request.form.get('mecanico', 'Sin Asignar'),
            sistema_falla=request.form.get('sistema_falla'),
            causa_raiz=request.form.get('causa_raiz'),
            fecha=datetime.now()
        ))

    elif tabla == 'ot_corr':
        eq = Equipo.query.filter_by(codigo=codigo).first()
        lectura_req = clean_int(request.form.get('lectura'))
        if lectura_req == 0 and eq: lectura_req = eq.lectura_actual
        
        folio_req = request.form.get('folio', '').strip()
        if not folio_req:
            ultima_ot_global = OrdenTrabajo.query.order_by(OrdenTrabajo.id.desc()).first()
            siguiente_id = (ultima_ot_global.id + 1) if ultima_ot_global else 1
            folio_req = f"CM-{siguiente_id:05d}"

        db.session.add(OrdenTrabajo(
            codigo_equipo=codigo, 
            folio=folio_req, 
            tipo_ot='Correctiva', 
            tipo_mantencion=request.form.get('falla', 'Avería'), 
            lectura=lectura_req, 
            costo_mantencion_clp=clean_float(request.form.get('costo'), 0.0), 
            estado=request.form.get('estado', 'Pendiente'), 
            mecanico=request.form.get('mecanico', 'Sin Asignar'),
            sistema_falla=request.form.get('sistema_falla'),
            causa_raiz=request.form.get('causa_raiz'),
            fecha=datetime.now()
        ))

    elif tabla == 'compra':
        db.session.add(CompraRepuesto(codigo_equipo=codigo, oc=request.form.get('oc', f"OC-{random.randint(100,999)}"), descripcion=request.form.get('descripcion', 'Insumos'), costo_pm_clp=clean_float(request.form.get('costo'), 0.0), fecha=datetime.now()))
    elif tabla == 'filtro':
        db.session.add(FiltroEquipo(codigo_equipo=codigo, sistema="NUEVO SISTEMA"))
    elif tabla == 'personal':
        db.session.add(Personal(nombre=request.form.get('nombre', ''), cargo='Operador', estado='Activo', equipo_asignado=request.form.get('equipo', 'Ninguno')))
    elif tabla == 'uso_equipo':
        try: fecha_uso = datetime.strptime(request.form.get('fecha'), '%Y-%m-%d')
        except: fecha_uso = datetime.now()
        db.session.add(RegistroUsoEquipo(fecha=fecha_uso, operador=request.form.get('operador', ''), codigo_equipo=codigo, observacion=request.form.get('observacion', '')))
        op = Personal.query.filter_by(nombre=request.form.get('operador')).first()
        if op: op.equipo_asignado = codigo
    elif tabla == 'mecanico':
        db.session.add(Mecanico(nombre=request.form.get('nombre', ''), especialidad=request.form.get('especialidad', 'General'), estado='Activo'))

    db.session.commit()
    return redirect(request.form.get('referer', '/'))

@api_bp.route('/api/delete_record/<tabla>/<int:id>', methods=['POST'])
@login_required
def delete_record(tabla, id):
    obj = None
    if tabla == 'lectura': obj = HistorialLectura.query.get(id)
    elif tabla == 'ot': obj = OrdenTrabajo.query.get(id)
    elif tabla == 'compra': obj = CompraRepuesto.query.get(id)
    elif tabla == 'filtro': obj = FiltroEquipo.query.get(id)
    elif tabla == 'personal': obj = Personal.query.get(id)
    elif tabla == 'mecanico': obj = Mecanico.query.get(id)
    elif tabla == 'uso_equipo': obj = RegistroUsoEquipo.query.get(id)
        
    if obj:
        db.session.delete(obj)
        db.session.commit()
        return jsonify({"status": "success"})
    return jsonify({"status": "error"}), 404

@api_bp.route('/update_inline', methods=['POST'])
@login_required
def update_inline():
    data = request.json
    tabla = data.get('tabla')
    cod = data.get('codigo')
    campo = data.get('campo')
    valor = data.get('valor')

    obj = None
    if tabla == 'equipo': obj = Equipo.query.filter_by(codigo=cod).first()
    elif tabla == 'lectura': obj = HistorialLectura.query.get(cod)
    elif tabla == 'ot': obj = OrdenTrabajo.query.get(cod)
    elif tabla == 'compra': obj = CompraRepuesto.query.get(cod)
    elif tabla == 'personal': obj = Personal.query.get(cod)
    elif tabla == 'mecanico': obj = Mecanico.query.get(cod)
    elif tabla == 'filtro': obj = FiltroEquipo.query.get(cod)
    elif tabla == 'uso_equipo': obj = RegistroUsoEquipo.query.get(cod)

    if obj:
        if campo in ['costo_mantencion_clp', 'costo_pm_clp', 'horometro', 'kilometraje', 'lectura', 'cant']:
            valor = clean_float(valor, 0.0) if 'costo' in campo else clean_int(valor)
        setattr(obj, campo, valor)
        db.session.commit()
        return jsonify({"status": "success"})
    return jsonify({"status": "error"}), 404
