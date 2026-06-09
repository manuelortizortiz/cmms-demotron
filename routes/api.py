from flask import Blueprint, request, jsonify, redirect
from datetime import datetime
import random
from flask_login import login_required
from flask_mail import Message
from extensions import db, mail
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
        if ot.estado == 'Finalizada' and not ot.fecha_cierre:
            ot.fecha_cierre = datetime.now()
        db.session.commit()
    return jsonify({"status": "success"})

@api_bp.route('/api/add_record', methods=['POST'])
@login_required
def add_record():
    tabla = request.form.get('tabla')
    codigo = request.form.get('codigo')
    
    if tabla == 'lectura':
        val = clean_int(request.form.get('valor'))
        eq = Equipo.query.filter_by(codigo=codigo).first()
        # Inteligencia: Detecta HR o KM automáticamente
        h_val = val if eq and eq.control_base == 'HORAS' else 0
        k_val = val if eq and eq.control_base == 'KM' else 0
        
        db.session.add(HistorialLectura(
            codigo_equipo=codigo, horometro=h_val, kilometraje=k_val, 
            observacion=request.form.get('observacion', ''), fecha=datetime.now(),
            responsable=request.form.get('responsable', 'Admin')
        ))
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
            codigo_equipo=codigo, folio=folio_req, tipo_ot='Preventiva', 
            tipo_mantencion=request.form.get('tipo', 'PM1'), lectura=lectura_req, 
            costo_mantencion_clp=clean_float(request.form.get('costo'), 0.0), 
            estado=request.form.get('estado', 'Pendiente'), 
            mecanico=request.form.get('mecanico', 'Sin Asignar'),
            fecha=datetime.now()
        ))

    elif tabla == 'ot_corr':
        eq = Equipo.query.filter_by(codigo=codigo).first()
        lectura_req = clean_int(request.form.get('lectura'))
        if lectura_req == 0 and eq: lectura_req = eq.lectura_actual
        
        folio_req = request.form.get('folio', '').strip() or f"CM-{datetime.now().strftime('%M%S%f')}"
        sistema_f = request.form.get('sistema_falla', 'No especificado')
        causa_r = request.form.get('causa_raiz', 'Sin diagnóstico inicial')

        nueva_ot = OrdenTrabajo(
            codigo_equipo=codigo, folio=folio_req, tipo_ot='Correctiva', 
            tipo_mantencion=request.form.get('falla', 'Avería'), lectura=lectura_req, 
            costo_mantencion_clp=clean_float(request.form.get('costo'), 0.0), 
            estado=request.form.get('estado', 'Pendiente'), 
            mecanico=request.form.get('mecanico', 'Sin Asignar'),
            sistema_falla=sistema_f, causa_raiz=causa_r, fecha=datetime.now()
        )
        db.session.add(nueva_ot)
        db.session.commit()

        try:
            msg = Message(
                subject=f"🚨 ALERTA CMMS: Nueva Avería en Equipo {codigo}",
                sender='no-reply@demotron.cl',
                recipients=['admin@demotron.cl']
            )
            msg.body = f"Se ha reportado una avería.\nEquipo: {codigo}\nFolio: {folio_req}\nSistema: {sistema_f}\nDiagnóstico: {causa_r}"
            mail.send(msg)
        except Exception as e:
            print(f"Error correo: {e}")

    elif tabla == 'compra':
        # Fix: OC Segura para evitar colisiones
        oc_segura = request.form.get('oc', '').strip() or f"OC-{datetime.now().strftime('%Y%m%d%H%M')}"
        db.session.add(CompraRepuesto(
            codigo_equipo=codigo, oc=oc_segura, 
            descripcion=request.form.get('descripcion', 'Insumos'), 
            costo_pm_clp=clean_float(request.form.get('costo'), 0.0), fecha=datetime.now()
        ))
        
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

# --- NUEVAS RUTAS DE EDICIÓN ---
@api_bp.route('/api/edit_ot/<int:ot_id>', methods=['POST'])
@login_required
def edit_ot(ot_id):
    ot = OrdenTrabajo.query.get_or_404(ot_id)
    data = request.form
    if data.get('fecha'):
        try: ot.fecha = datetime.strptime(data.get('fecha'), '%Y-%m-%d')
        except ValueError: pass
    if data.get('tipo_mantencion'): ot.tipo_mantencion = data.get('tipo_mantencion').strip()
    if data.get('tipo_ot') in ['Preventiva','Correctiva']: ot.tipo_ot = data.get('tipo_ot')
    if data.get('estado'): ot.estado = data.get('estado')
    if data.get('mecanico'): ot.mecanico = data.get('mecanico').strip()
    if data.get('folio'): ot.folio = data.get('folio').strip()
    if data.get('lugar'): ot.lugar = data.get('lugar').strip()
    if data.get('lectura'): ot.lectura = clean_int(data.get('lectura'))
    if data.get('costo'): ot.costo_mantencion_clp = clean_float(data.get('costo'), 0.0)
    if data.get('sistema_falla'): ot.sistema_falla = data.get('sistema_falla')
    if data.get('causa_raiz'): ot.causa_raiz = data.get('causa_raiz').strip()
    if ot.estado == 'Finalizada' and not ot.fecha_cierre:
        ot.fecha_cierre = datetime.now()
    db.session.commit()
    return jsonify({"status": "success"})

@api_bp.route('/api/edit_lectura/<int:lid>', methods=['POST'])
@login_required
def edit_lectura(lid):
    lec = HistorialLectura.query.get_or_404(lid)
    data = request.form
    if data.get('fecha'):
        try: lec.fecha = datetime.strptime(data.get('fecha'), '%Y-%m-%d')
        except ValueError: pass
    if data.get('horometro') is not None: lec.horometro = clean_int(data.get('horometro'), 0)
    if data.get('kilometraje') is not None: lec.kilometraje = clean_int(data.get('kilometraje'), 0)
    if data.get('observacion') is not None: lec.observacion = data.get('observacion').strip()
    
    eq = Equipo.query.filter_by(codigo=lec.codigo_equipo).first()
    if eq:
        ultima = HistorialLectura.query.filter_by(codigo_equipo=lec.codigo_equipo).order_by(HistorialLectura.fecha.desc(), HistorialLectura.id.desc()).first()
        if ultima: eq.lectura_actual = ultima.horometro if eq.control_base == 'HORAS' else ultima.kilometraje
        db.session.commit()
    return jsonify({"status": "success"})

@api_bp.route('/api/edit_equipo/<codigo>', methods=['POST'])
@login_required
def edit_equipo(codigo):
    eq = Equipo.query.filter_by(codigo=codigo).first_or_404()
    data = request.form
    campos = ['tipo_equipo','marca','modelo','ubicacion','responsable','estado_base','control_base','vin','n_motor','patente']
    for campo in campos:
        val = data.get(campo)
        if val is not None: setattr(eq, campo, val.strip())
    if data.get('frecuencia_base'):
        eq.frecuencia_base = clean_int(data.get('frecuencia_base'), eq.frecuencia_base)
    eq.proxima_pm = (eq.lectura_actual or 0) + eq.frecuencia_base
    db.session.commit()
    return jsonify({"status": "success"})

@api_bp.route('/api/cambiar_estado_ot/<int:ot_id>', methods=['POST'])
@login_required
def cambiar_estado_ot(ot_id):
    ot = OrdenTrabajo.query.get_or_404(ot_id)
    nuevo = request.json.get('estado')
    if nuevo in ['Pendiente','En Progreso','En Espera Repuestos','En Revisión','Finalizada']:
        ot.estado = nuevo
        if nuevo == 'Finalizada' and not ot.fecha_cierre: ot.fecha_cierre = datetime.now()
        db.session.commit()
        return jsonify({"status": "success", "estado": nuevo})
    return jsonify({"status": "error"}), 400
