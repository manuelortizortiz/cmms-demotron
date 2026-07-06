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

# =====================================================================
# 1. MÓDULO: REGISTRO HISTÓRICO COMPLETO (HOJA DE VIDA) - DISEÑO PULCRO
# =====================================================================
@api_bp.route('/api/imprimir_registro/<codigo>')
@login_required
def imprimir_registro(codigo):
    eq = Equipo.query.filter_by(codigo=codigo).first_or_404()
    ots = OrdenTrabajo.query.filter_by(codigo_equipo=codigo, estado='Finalizada').order_by(OrdenTrabajo.fecha.desc()).limit(15).all()
    lecturas = HistorialLectura.query.filter_by(codigo_equipo=codigo).order_by(HistorialLectura.fecha.desc()).limit(15).all()
    
    html = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <title>Registro Histórico - {eq.codigo}</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            @media print {{ 
                body {{ background: white; }} 
                .print\\:hidden {{ display: none !important; }} 
                .shadow-xl {{ box-shadow: none !important; border-color: transparent !important; }}
                @page {{ margin: 1cm; size: letter; }}
            }}
            table {{ page-break-inside: auto; }}
            tr {{ page-break-inside: avoid; page-break-after: auto; }}
        </style>
    </head>
    <body class="bg-slate-50 p-8 font-sans text-slate-800 max-w-4xl mx-auto">
        <div class="bg-white p-10 rounded-2xl shadow-xl border border-slate-200 print:p-0 print:border-none">
            
            <div class="flex justify-between items-center border-b-2 border-slate-800 pb-4 mb-6">
                <div class="flex items-center gap-4">
                    <div class="w-16 h-16 border-2 border-slate-900 text-slate-900 flex items-center justify-center rounded-xl text-2xl font-black">DT</div>
                    <div>
                        <h1 class="text-2xl font-black text-slate-900 leading-tight">REGISTRO TÉCNICO COMPLETO</h1>
                        <p class="text-xl text-slate-700 font-bold tracking-widest">{eq.codigo}</p>
                    </div>
                </div>
                <div class="text-right">
                    <p class="text-sm font-bold text-slate-500">Demotron S.A.</p>
                    <p class="text-xs text-slate-400">Emisión: {datetime.now().strftime('%d/%m/%Y')}</p>
                </div>
            </div>

            <!-- TARJETAS DE DATOS DUROS -->
            <div class="grid grid-cols-2 gap-6 mb-8">
                <div class="border border-slate-300 rounded-lg p-5 bg-white">
                    <h3 class="text-xs font-black text-slate-800 uppercase mb-3 tracking-wider border-b border-slate-200 pb-1">Identificación y Motor</h3>
                    <p class="text-sm mb-1"><span class="font-bold text-slate-500 w-24 inline-block">Tipo:</span> <span class="font-bold">{eq.tipo_equipo}</span></p>
                    <p class="text-sm mb-1"><span class="font-bold text-slate-500 w-24 inline-block">Marca/Mod:</span> {eq.marca} {eq.modelo}</p>
                    <p class="text-sm mb-1 mt-2"><span class="font-bold text-slate-500 w-24 inline-block">Patente:</span> <span class="font-mono bg-slate-100 border border-slate-300 px-2 py-0.5 rounded font-bold">{eq.patente or 'S/I'}</span></p>
                    <p class="text-sm mb-1"><span class="font-bold text-slate-500 w-24 inline-block">VIN:</span> <span class="font-mono text-xs">{eq.vin or 'S/I'}</span></p>
                    <p class="text-sm mb-1"><span class="font-bold text-slate-500 w-24 inline-block">N° Motor:</span> <span class="font-mono text-xs">{eq.n_motor or 'S/I'}</span></p>
                </div>
                <div class="border border-slate-300 rounded-lg p-5 bg-white">
                    <h3 class="text-xs font-black text-slate-800 uppercase mb-3 tracking-wider border-b border-slate-200 pb-1">Estado y Operatividad</h3>
                    <p class="text-sm mb-1"><span class="font-bold text-slate-500 w-28 inline-block">Ubicación:</span> {eq.ubicacion}</p>
                    <p class="text-sm mb-1"><span class="font-bold text-slate-500 w-28 inline-block">Operador:</span> {eq.responsable}</p>
                    <p class="text-sm mb-3"><span class="font-bold text-slate-500 w-28 inline-block">Estado:</span> <span class="border border-slate-400 text-slate-800 px-2 py-0.5 rounded font-bold text-xs">{eq.estado_base}</span></p>
                    <div class="border-t border-slate-200 pt-3"></div>
                    <p class="text-sm mb-1"><span class="font-bold text-slate-500 w-28 inline-block">Lectura Act:</span> <span class="font-bold text-slate-800 text-lg">{eq.lectura_actual or 0} {eq.control_base}</span></p>
                    <p class="text-sm"><span class="font-bold text-slate-500 w-28 inline-block">Mto. Restante:</span> <span class="font-bold text-slate-600">{eq.margen} {eq.control_base}</span></p>
                </div>
            </div>

            <h3 class="text-sm font-bold text-slate-800 uppercase mb-3 border-b-2 border-slate-200 pb-1">Últimas Intervenciones</h3>
            <table class="w-full text-left text-[11px] mb-8 border border-slate-300">
                <thead>
                    <tr class="bg-slate-100 text-slate-700 border-b border-slate-300">
                        <th class="p-2 border-r border-slate-300 uppercase tracking-wider">Fecha</th>
                        <th class="p-2 border-r border-slate-300 uppercase tracking-wider">Folio</th>
                        <th class="p-2 border-r border-slate-300 uppercase tracking-wider">Clase</th>
                        <th class="p-2 border-r border-slate-300 uppercase tracking-wider">Intervención</th>
                        <th class="p-2 border-r border-slate-300 uppercase tracking-wider">Mecánico</th>
                        <th class="p-2 uppercase tracking-wider">Odo/Hor.</th>
                    </tr>
                </thead>
                <tbody>
                    {"".join([f"<tr class='border-b border-slate-200'><td class='p-2 border-r border-slate-300'>{o.fecha.strftime('%d/%m/%Y') if o.fecha else ''}</td><td class='p-2 border-r border-slate-300 font-bold'>{o.folio}</td><td class='p-2 border-r border-slate-300 font-bold uppercase'>{o.tipo_ot}</td><td class='p-2 border-r border-slate-300'>{o.tipo_mantencion}</td><td class='p-2 border-r border-slate-300'>{o.mecanico}</td><td class='p-2 font-mono'>{o.lectura}</td></tr>" for o in ots])}
                </tbody>
            </table>

            <h3 class="text-sm font-bold text-slate-800 uppercase mb-3 border-b-2 border-slate-200 pb-1">Historial de Lecturas Terreno</h3>
            <table class="w-full text-left text-[11px] mb-8 border border-slate-300">
                <thead>
                    <tr class="bg-slate-100 text-slate-700 border-b border-slate-300">
                        <th class="p-2 border-r border-slate-300 uppercase tracking-wider">Fecha de Captura</th>
                        <th class="p-2 border-r border-slate-300 uppercase tracking-wider">Valor Registrado</th>
                        <th class="p-2 uppercase tracking-wider">Tipo de Medida</th>
                    </tr>
                </thead>
                <tbody>
                    {"".join([f"<tr class='border-b border-slate-200'><td class='p-2 border-r border-slate-300'>{l.fecha.strftime('%d/%m/%Y') if l.fecha else ''}</td><td class='p-2 border-r border-slate-300 font-mono font-bold text-slate-800'>{'{:,.0f}'.format(l.horometro if l.horometro and l.horometro > 0 else l.kilometraje).replace(',','.')}</td><td class='p-2 font-bold text-slate-600 uppercase'>{'HORAS' if l.horometro and l.horometro > 0 else 'KILÓMETROS'}</td></tr>" for l in lecturas])}
                </tbody>
            </table>
            
            <div class="text-center mt-12 pt-6 border-t border-slate-200 print:hidden flex justify-center gap-4">
                <button onclick="window.print()" class="bg-slate-800 text-white px-8 py-3 rounded font-bold shadow hover:bg-slate-700 transition">Imprimir Registro Completo</button>
                <button onclick="window.close()" class="bg-slate-200 text-slate-700 px-8 py-3 rounded font-bold shadow hover:bg-slate-300 transition">Cerrar</button>
            </div>
        </div>
    </body>
    </html>
    """
    return render_template_string(html)


# =====================================================================
# 2. MÓDULO: PAUTA DE MANTENCIÓN Y FILTROS (TAMAÑO CARTA Y LIMPIO)
# =====================================================================
@api_bp.route('/api/imprimir_filtros/<codigo>')
@login_required
def imprimir_filtros(codigo):
    eq = Equipo.query.filter_by(codigo=codigo).first_or_404()
    filtros = FiltroEquipo.query.filter_by(codigo_equipo=codigo).all()
    
    signature_actual = set()
    for f in filtros:
        row_data = (f.sistema, f.fleetguard, f.baldwind, f.originales, f.donaldson, f.otra)
        if any(val not in ['-', '', 'nan', None] for val in [f.fleetguard, f.baldwind, f.originales, f.donaldson, f.otra]):
            signature_actual.add(row_data)
    
    equipos_similares = []
    if signature_actual:
        todos_filtros = FiltroEquipo.query.filter(FiltroEquipo.codigo_equipo != codigo).all()
        from collections import defaultdict
        mapa_filtros = defaultdict(list)
        for f in todos_filtros:
            mapa_filtros[f.codigo_equipo].append(f)
        
        for cod_eq, lista_f in mapa_filtros.items():
            sig_eq = set()
            for f in lista_f:
                row_data = (f.sistema, f.fleetguard, f.baldwind, f.originales, f.donaldson, f.otra)
                if any(val not in ['-', '', 'nan', None] for val in [f.fleetguard, f.baldwind, f.originales, f.donaldson, f.otra]):
                    sig_eq.add(row_data)
            
            if sig_eq and sig_eq == signature_actual:
                equipos_similares.append(cod_eq)
                
    equipos_similares = sorted(equipos_similares)
    
    html = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <title>Pauta de Filtros - {eq.codigo}</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            @media print {{ 
                body {{ background: white; }} 
                .print\\:hidden {{ display: none !important; }} 
                .shadow-xl {{ box-shadow: none !important; border-color: transparent !important; }}
                @page {{ margin: 1cm; size: letter; }}
            }}
            table {{ page-break-inside: auto; font-size: 11px; }}
            tr {{ page-break-inside: avoid; page-break-after: auto; }}
            th, td {{ padding: 6px 8px !important; }}
        </style>
    </head>
    <body class="bg-slate-50 p-4 font-sans text-slate-800 max-w-4xl mx-auto">
        <div class="bg-white p-6 rounded-xl shadow-xl border border-slate-200 print:p-0 print:border-none">
            
            <div class="flex justify-between items-start border-b-2 border-slate-800 pb-2 mb-4">
                <div>
                    <h1 class="text-xl font-black text-slate-900 uppercase">PAUTA DE MANTENCIÓN Y FILTROS</h1>
                    <p class="text-xs font-bold text-slate-500">Gestión de Flota - Demotron S.A.</p>
                    <p class="text-[10px] text-slate-400">Emisión: {datetime.now().strftime('%d/%m/%Y')}</p>
                </div>
                <div class="text-right flex flex-col items-end">
                    <span class="text-[9px] text-slate-500 font-bold uppercase tracking-widest mb-1">Código de Equipo</span>
                    <div class="border-2 border-slate-900 text-slate-900 px-4 py-1 rounded-lg text-3xl font-black tracking-tighter print:bg-white">
                        {eq.codigo}
                    </div>
                </div>
            </div>

            <div class="grid grid-cols-2 gap-4 mb-4">
                <div class="border border-slate-300 rounded p-3 bg-white">
                    <h3 class="text-[10px] font-black text-slate-800 uppercase mb-2 border-b border-slate-200 pb-1">Especificaciones Técnicas</h3>
                    <div class="grid grid-cols-2 gap-1 text-xs">
                        <p><span class="font-bold text-slate-500 uppercase text-[9px]">Marca:</span> <br><span class="font-bold">{eq.marca or 'S/I'}</span></p>
                        <p><span class="font-bold text-slate-500 uppercase text-[9px]">Modelo:</span> <br><span class="font-bold">{eq.modelo or 'S/I'}</span></p>
                        <p><span class="font-bold text-slate-500 uppercase text-[9px]">VIN / Chasis:</span> <br><span class="font-mono">{eq.vin or 'S/I'}</span></p>
                        <p><span class="font-bold text-slate-500 uppercase text-[9px]">Motor:</span> <br><span class="font-mono">{eq.n_motor or 'S/I'}</span></p>
                    </div>
                </div>
                
                <div class="border border-slate-300 rounded p-3 bg-white flex flex-col">
                    <h3 class="text-[10px] font-black text-slate-800 uppercase mb-2 border-b border-slate-200 pb-1">Compatibilidad de Flota</h3>
                    <p class="text-[9px] text-slate-500 mb-1 uppercase">Equipos con los mismos filtros:</p>
                    <div class="flex flex-wrap gap-1">
"""
    if equipos_similares:
        for sim in equipos_similares:
            html += f"<span class='border border-slate-400 text-slate-800 font-bold px-2 py-0.5 rounded text-[10px] bg-slate-50'>{sim}</span>"
    else:
        html += "<span class='text-slate-400 text-[10px] italic'>Pauta única en la flota.</span>"
        
    html += f"""
                    </div>
                </div>
            </div>

            <table class="w-full text-left border border-slate-400 mb-4">
                <thead>
                    <tr class="bg-slate-100 text-slate-800 border-b border-slate-400">
                        <th class="uppercase text-[10px] tracking-wider border-r border-slate-300">Sistema</th>
                        <th class="text-center uppercase text-[10px] tracking-wider border-r border-slate-300">Cant</th>
                        <th class="uppercase text-[10px] tracking-wider border-r border-slate-300">Fleetguard</th>
                        <th class="uppercase text-[10px] tracking-wider border-r border-slate-300">Baldwin</th>
                        <th class="uppercase text-[10px] tracking-wider border-r border-slate-300">Originales</th>
                        <th class="uppercase text-[10px] tracking-wider border-r border-slate-300">Donaldson</th>
                        <th class="uppercase text-[10px] tracking-wider">Alternativo</th>
                    </tr>
                </thead>
                <tbody>
"""
    for f in filtros:
        html += f"""
                    <tr class="border-b border-slate-300">
                        <td class="font-bold text-slate-800 border-r border-slate-300">{f.sistema}</td>
                        <td class="text-center font-bold border-r border-slate-300">{f.cant}</td>
                        <td class="font-mono border-r border-slate-300">{f.fleetguard}</td>
                        <td class="font-mono border-r border-slate-300">{f.baldwind}</td>
                        <td class="font-mono border-r border-slate-300">{f.originales}</td>
                        <td class="font-mono border-r border-slate-300">{f.donaldson}</td>
                        <td class="font-mono">{f.otra}</td>
                    </tr>
        """
    
    # Añadir 2 filas en blanco para anotaciones
    for _ in range(2):
        html += """
                    <tr class="border-b border-slate-300">
                        <td class="h-6 border-r border-slate-300"></td>
                        <td class="border-r border-slate-300"></td>
                        <td class="border-r border-slate-300"></td>
                        <td class="border-r border-slate-300"></td>
                        <td class="border-r border-slate-300"></td>
                        <td class="border-r border-slate-300"></td>
                        <td></td>
                    </tr>
        """
        
    html += f"""
                </tbody>
            </table>
            
            <div class="text-center mt-6 pt-4 border-t border-slate-200 print:hidden flex justify-center gap-4">
                <button onclick="window.print()" class="bg-slate-800 text-white px-6 py-2 rounded font-bold shadow hover:bg-slate-700 transition">Imprimir Pauta</button>
                <button onclick="window.close()" class="bg-slate-200 text-slate-700 px-6 py-2 rounded font-bold hover:bg-slate-300 transition">Cerrar</button>
            </div>
        </div>
    </body>
    </html>
    """
    return render_template_string(html)
