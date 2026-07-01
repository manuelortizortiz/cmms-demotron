from flask import Blueprint, request, jsonify, redirect, render_template_string
import os
from werkzeug.utils import secure_filename
from datetime import datetime
import random
from flask_login import login_required, current_user
from flask_mail import Message
from extensions import db, mail
from models.equipo import Equipo, FiltroEquipo
from models.orden_trabajo import OrdenTrabajo
from models.historial import HistorialLectura, CompraRepuesto
from models.personal import Personal, Mecanico, RegistroUsoEquipo
from models.chatter import RegistroChatter
from models.bodega import InventarioBodega
from utils.formatters import clean_int, clean_float, format_num, format_clp

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
        h_val = val if eq and eq.control_base == 'HORAS' else 0
        k_val = val if eq and eq.control_base == 'KM' else 0
        db.session.add(HistorialLectura(
            codigo_equipo=codigo, horometro=h_val, kilometraje=k_val, 
            observacion='', fecha=datetime.now(), responsable=''
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
        
        folio_input = request.form.get('folio', '').strip()
        if folio_input:
            folio_req = folio_input if folio_input.startswith("OT-CR-") else f"OT-CR-{folio_input}"
        else:
            folio_req = f"OT-CR-{datetime.now().strftime('%M%S%f')[:5]}"
            
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

    elif tabla == 'compra':
        oc_segura = request.form.get('oc', '').strip() or f"OC-{datetime.now().strftime('%Y%m%d%H%M')}"
        db.session.add(CompraRepuesto(
            codigo_equipo=codigo, oc=oc_segura, descripcion=request.form.get('descripcion', 'Insumos'), 
            costo_pm_clp=clean_float(request.form.get('costo'), 0.0), fecha=datetime.now()
        ))
        
    elif tabla == 'bodega':
        db.session.add(InventarioBodega(
            codigo_item=request.form.get('codigo_item', '').strip(),
            nombre=request.form.get('nombre', '').strip(),
            categoria=request.form.get('categoria', 'Filtro'),
            cantidad=clean_int(request.form.get('cantidad'), 0),
            ubicacion=request.form.get('ubicacion', '').strip()
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
        db.session.add(Mecanico(
            rut=request.form.get('rut', ''),  
            nombre=request.form.get('nombre', ''), 
            especialidad=request.form.get('especialidad', 'General'), 
            estado='Activo'
        ))

    db.session.commit()
    return redirect(request.form.get('referer', '/'))

@api_bp.route('/api/delete_record/<tabla>/<int:id>', methods=['POST'])
@login_required
def delete_record(tabla, id):
    obj = None
    if tabla == 'lectura': obj = HistorialLectura.query.get(id)
    elif tabla == 'ot': obj = OrdenTrabajo.query.get(id)
    elif tabla == 'compra': obj = CompraRepuesto.query.get(id)
    elif tabla == 'bodega': obj = InventarioBodega.query.get(id)
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
    elif tabla == 'bodega': obj = InventarioBodega.query.get(cod)
    elif tabla == 'personal': obj = Personal.query.get(cod)
    elif tabla == 'mecanico': obj = Mecanico.query.get(cod)
    elif tabla == 'filtro': obj = FiltroEquipo.query.get(cod)
    elif tabla == 'uso_equipo': obj = RegistroUsoEquipo.query.get(cod)

    if obj:
        if campo in ['costo_mantencion_clp', 'costo_pm_clp', 'horometro', 'kilometraje', 'lectura', 'cant', 'cantidad']:
            valor = clean_float(valor, 0.0) if 'costo' in campo else clean_int(valor)
        setattr(obj, campo, valor)
        db.session.commit()
        return jsonify({"status": "success"})
    return jsonify({"status": "error"}), 404

@api_bp.route('/api/cambiar_estado_ot/<int:ot_id>', methods=['POST'])
@login_required
def cambiar_estado_ot(ot_id):
    ot = OrdenTrabajo.query.get_or_404(ot_id)
    nuevo = request.json.get('estado')
    estado_anterior = ot.estado
    
    if nuevo in ['Pendiente','En Progreso','En Revisión','Finalizada']:
        ot.estado = nuevo
        if nuevo == 'Finalizada' and not ot.fecha_cierre: ot.fecha_cierre = datetime.now()
        
        if estado_anterior != nuevo:
            log = RegistroChatter(
                modelo_ref='ot', registro_id=str(ot.id), autor=current_user.nombre,
                accion='cambio_estado', valor_anterior=estado_anterior, valor_nuevo=nuevo
            )
            db.session.add(log)
            
        db.session.commit()
        return jsonify({"status": "success", "estado": nuevo})
    return jsonify({"status": "error"}), 400

@api_bp.route('/api/chatter/<modelo>/<registro_id>', methods=['GET'])
@login_required
def get_chatter(modelo, registro_id):
    logs = RegistroChatter.query.filter_by(modelo_ref=modelo, registro_id=registro_id).order_by(RegistroChatter.fecha.desc()).all()
    return jsonify([log.to_dict() for log in logs])

@api_bp.route('/api/chatter/add', methods=['POST'])
@login_required
def add_chatter():
    modelo = request.form.get('modelo_ref')
    registro_id = request.form.get('registro_id')
    mensaje = request.form.get('mensaje', '').strip()
    accion = 'comentario'
    archivo_url = None

    if 'archivo' in request.files:
        file = request.files['archivo']
        if file.filename != '':
            filename = secure_filename(file.filename)
            upload_folder = os.path.join('static', 'uploads', 'chatter')
            os.makedirs(upload_folder, exist_ok=True)
            filepath = os.path.join(upload_folder, filename)
            file.save(filepath)
            archivo_url = f"/static/uploads/chatter/{filename}"
            accion = 'adjunto'

    if not mensaje and not archivo_url:
        return jsonify({"status": "error"}), 400

    log = RegistroChatter(modelo_ref=modelo, registro_id=registro_id, autor=current_user.nombre, accion=accion, mensaje=mensaje, archivo_url=archivo_url)
    db.session.add(log)
    db.session.commit()
    return jsonify({"status": "success", "log": log.to_dict()})

# --- NUEVA RUTA PARA VER Y ENVIAR A IMPRESIÓN LA OT ---
@api_bp.route('/ver_ot/<int:ot_id>')
@login_required
def ver_ot(ot_id):
    ot = OrdenTrabajo.query.get_or_404(ot_id)
    eq = Equipo.query.filter_by(codigo=ot.codigo_equipo).first()
    
    lectura_str = format_num(ot.lectura)
    costo_str = format_clp(ot.costo_mantencion_clp)
    fecha_str = ot.fecha.strftime('%d/%m/%Y') if ot.fecha else 'S/F'
    tipo_eq_str = eq.tipo_equipo if eq else 'S/E'
    ctrl_eq_str = eq.control_base if eq else ''
    
    html = """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <title>{{ ot.folio }} - {{ ot.codigo_equipo }}</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            @media print {
                body { background: white; padding: 0; margin: 0; }
                .print\\:hidden { display: none !important; }
                .shadow-2xl { box-shadow: none !important; }
                .border { border-color: #cbd5e1 !important; }
                @page { margin: 1cm; }
            }
        </style>
    </head>
    <body class="bg-slate-100 p-8 font-sans text-slate-800">
        <div class="max-w-4xl mx-auto bg-white p-12 rounded-2xl shadow-2xl border border-slate-200">
            <div class="flex justify-between items-start mb-8 border-b-2 border-slate-100 pb-8">
                <div class="flex items-center gap-6">
                    <div class="w-20 h-20 bg-blue-700 text-white flex items-center justify-center rounded-2xl text-3xl font-black tracking-tighter">DT</div>
                    <div>
                        <h1 class="text-3xl font-extrabold text-slate-800 mb-1">ORDEN DE TRABAJO</h1>
                        <p class="text-slate-500 font-mono text-xl font-bold bg-slate-100 inline-block px-3 py-1 rounded-md">{{ ot.folio }}</p>
                    </div>
                </div>
                <div class="text-right">
                    <button onclick="window.print()" class="bg-blue-600 text-white px-6 py-3 rounded-xl font-bold shadow-md print:hidden hover:bg-blue-700 transition duration-200">🖨️ Imprimir OT</button>
                    <p class="text-sm font-bold text-slate-400 mt-4 uppercase print:block hidden">Folio No.</p>
                    <p class="font-mono text-xl font-bold print:block hidden">{{ ot.folio }}</p>
                </div>
            </div>
            
            <div class="grid grid-cols-2 gap-8 mb-8">
                <div class="bg-slate-50 p-6 rounded-xl border border-slate-200">
                    <p class="text-[10px] text-blue-600 font-bold uppercase tracking-widest mb-3">Información del Equipo</p>
                    <p class="font-black text-2xl text-slate-800 mb-2">{{ ot.codigo_equipo }}</p>
                    <p class="text-sm text-slate-600 mb-1">Tipo de Equipo: <b class="text-slate-800">{{ tipo_eq_str }}</b></p>
                    <p class="text-sm text-slate-600">Lectura Actual: <b class="text-slate-800">{{ lectura_str }} {{ ctrl_eq_str }}</b></p>
                </div>
                <div class="bg-slate-50 p-6 rounded-xl border border-slate-200">
                    <p class="text-[10px] text-blue-600 font-bold uppercase tracking-widest mb-3">Detalles de Intervención</p>
                    <p class="font-black text-xl text-slate-800 mb-2">{{ ot.tipo_ot }}</p>
                    <p class="text-sm text-slate-600 mb-1">Fecha Emisión: <b class="text-slate-800">{{ fecha_str }}</b></p>
                    <p class="text-sm text-slate-600 mb-1">Responsable: <b class="text-slate-800">{{ ot.mecanico }}</b></p>
                    <p class="text-sm text-slate-600">Estado: <span class="bg-slate-200 px-2 py-0.5 rounded font-bold text-slate-700 border border-slate-300">{{ ot.estado }}</span></p>
                </div>
            </div>

            <div class="mb-12">
                <h3 class="text-[10px] font-bold text-blue-600 uppercase tracking-widest mb-3 border-b-2 border-slate-100 pb-2">Diagnóstico y Tareas Ejecutadas</h3>
                {% if ot.tipo_ot == 'Correctiva' %}
                    <div class="mb-4">
                        <p class="text-sm text-slate-500 mb-1">Sistema Afectado</p>
                        <p class="text-base font-bold text-slate-800">{{ ot.sistema_falla }}</p>
                    </div>
                    <div class="bg-red-50 p-5 rounded-xl border border-red-100">
                        <p class="text-sm text-red-500 font-bold mb-1 uppercase text-[10px] tracking-wider">Avería Detectada / Causa Raíz</p>
                        <p class="text-base text-red-900 font-semibold">{{ ot.causa_raiz }}</p>
                    </div>
                {% else %}
                    <div class="bg-green-50 p-5 rounded-xl border border-green-100">
                        <p class="text-sm text-green-600 font-bold mb-1 uppercase text-[10px] tracking-wider">Pauta Aplicada</p>
                        <p class="text-base text-green-900 font-semibold">{{ ot.tipo_mantencion }}</p>
                    </div>
                {% endif %}
            </div>
            
            <div class="grid grid-cols-2 gap-12 mt-16 pt-8 print:mt-32">
                <div class="text-center">
                    <div class="border-b-2 border-slate-300 w-3/4 mx-auto mb-2"></div>
                    <p class="text-xs font-bold text-slate-600 uppercase">{{ ot.mecanico }}</p>
                    <p class="text-[10px] text-slate-400">Firma Mecánico Responsable</p>
                </div>
                <div class="text-center">
                    <div class="border-b-2 border-slate-300 w-3/4 mx-auto mb-2"></div>
                    <p class="text-xs font-bold text-slate-600 uppercase">Jefatura de Taller</p>
                    <p class="text-[10px] text-slate-400">V°B° Supervisor</p>
                </div>
            </div>

            <div class="border-t-2 border-slate-100 mt-16 pt-6 flex justify-between items-center bg-slate-50 p-4 rounded-lg">
                <p class="text-slate-400 text-xs font-bold">Generado por CMMS Demotron S.A.</p>
                <p class="text-sm font-bold text-slate-500 uppercase tracking-widest">Costo Total: <span class="text-blue-600 font-black text-xl ml-2">{{ costo_str }}</span></p>
            </div>
        </div>
    </body>
    </html>
    """
    return render_template_string(html, ot=ot, eq=eq, lectura_str=lectura_str, costo_str=costo_str, fecha_str=fecha_str, tipo_eq_str=tipo_eq_str, ctrl_eq_str=ctrl_eq_str)

@api_bp.route('/api/edit_ot/<int:ot_id>', methods=['POST'])
@login_required
def edit_ot(ot_id):
    pass 
@api_bp.route('/api/edit_lectura/<int:lid>', methods=['POST'])
@login_required
def edit_lectura(lid):
    pass 
@api_bp.route('/api/edit_equipo/<codigo>', methods=['POST'])
@login_required
def edit_equipo(codigo):
    pass
