from flask import Blueprint, request, jsonify, redirect, render_template_string
import os
from werkzeug.utils import secure_filename
from datetime import datetime
from flask_login import login_required, current_user
from sqlalchemy import text
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db
from models.equipo import Equipo, FiltroEquipo
from models.orden_trabajo import OrdenTrabajo
from models.historial import HistorialLectura, CompraRepuesto
from models.personal import Personal, Mecanico, RegistroUsoEquipo
from models.chatter import RegistroChatter
from models.bodega import InventarioBodega
from utils.formatters import clean_int, clean_float

api_bp = Blueprint('api', __name__)

# --- FUNCIÓN INTERNA DE AUDITORÍA ---
def registrar_auditoria(mensaje):
    try:
        UserClass = current_user.__class__
        columnas = list(UserClass.__table__.columns.keys())
        col_nombre = 'username' if 'username' in columnas else 'nombre'
        autor_name = getattr(current_user, col_nombre, getattr(current_user, 'nombre', 'Sistema')) if current_user.is_authenticated else 'Sistema'
        
        log = RegistroChatter(
            modelo_ref='sistema', registro_id='0', 
            autor=autor_name, 
            accion='auditoria', mensaje=mensaje
        )
        db.session.add(log)
    except Exception: pass


# =====================================================================
# MÓDULO DE SEGURIDAD: CAMBIO DE CONTRASEÑA CALIBRADO
# =====================================================================
@api_bp.route('/api/cambiar_password', methods=['POST'])
@login_required
def cambiar_password():
    try:
        data = request.json
        actual = data.get('actual', '').strip()
        nueva = data.get('nueva', '').strip()
        
        if not actual or not nueva:
            return jsonify({"status": "error", "message": "Faltan datos."})

        # Detección de la columna correcta (Sabemos que es password_hash)
        UserClass = current_user.__class__
        columnas = UserClass.__table__.columns.keys()
        col_pass = 'password_hash' if 'password_hash' in columnas else next((c for c in ['password', 'clave', 'pwd'] if c in columnas), None)

        if not col_pass:
            return jsonify({"status": "error", "message": "Fallo crítico: No se detecta columna de contraseña."})

        clave_db = getattr(current_user, col_pass, '')
        
        valido = False
        if clave_db == actual:
            valido = True
        else:
            try:
                if check_password_hash(clave_db, actual):
                    valido = True
            except: pass

        if not valido:
            return jsonify({"status": "error", "message": "La contraseña actual no es correcta."})
        
        # Auto-ampliar tamaño de columna por seguridad
        try:
            db.session.execute(text(f"ALTER TABLE {UserClass.__tablename__} ALTER COLUMN {col_pass} TYPE VARCHAR(255)"))
            db.session.commit()
        except:
            db.session.rollback()

        setattr(current_user, col_pass, generate_password_hash(nueva))
        registrar_auditoria("ACTUALIZÓ SUS CREDENCIALES DE ACCESO.")
        db.session.commit()
        return jsonify({"status": "success", "message": "Clave actualizada con éxito."})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Error interno: {str(e)}"})


# =====================================================================
# MÓDULOS DE GESTIÓN DE DATOS (CRUD)
# =====================================================================
@api_bp.route('/update_kanban', methods=['POST'])
@login_required
def update_kanban():
    data = request.json
    ot = OrdenTrabajo.query.get(data.get('ot_id'))
    if ot:
        ot.estado = data.get('estado')
        if ot.estado == 'Finalizada' and not ot.fecha_cierre:
            ot.fecha_cierre = datetime.now()
        registrar_auditoria(f"MOVIÓ LA OT {ot.folio} AL ESTADO '{ot.estado}'.")
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
        db.session.add(HistorialLectura(codigo_equipo=codigo, horometro=h_val, kilometraje=k_val, observacion='', fecha=datetime.now(), responsable=''))
        if eq: eq.lectura_actual = val
        registrar_auditoria(f"REGISTRÓ LECTURA PARA {codigo}: {val}")

    elif tabla == 'ot' or tabla == 'ot_corr':
        eq = Equipo.query.filter_by(codigo=codigo).first()
        lectura_req = clean_int(request.form.get('lectura'))
        if lectura_req == 0 and eq: lectura_req = eq.lectura_actual
        folio_req = request.form.get('folio', '').strip()
        tipo_ot = 'Preventiva' if tabla == 'ot' else 'Correctiva'
        if not folio_req:
            prefix = "OT-" if tipo_ot == 'Preventiva' else "OT-CR-"
            folio_req = f"{prefix}{datetime.now().strftime('%M%S%f')[:5]}"
        falla = request.form.get('falla', request.form.get('tipo', 'PM1'))
        db.session.add(OrdenTrabajo(
            codigo_equipo=codigo, folio=folio_req, tipo_ot=tipo_ot, tipo_mantencion=falla, lectura=lectura_req, 
            costo_mantencion_clp=clean_float(request.form.get('costo'), 0.0), estado=request.form.get('estado', 'Pendiente'), 
            mecanico=request.form.get('mecanico', 'Sin Asignar'), sistema_falla=request.form.get('sistema_falla', ''), 
            causa_raiz=request.form.get('causa_raiz', ''), fecha=datetime.now()
        ))
        registrar_auditoria(f"CREÓ ORDEN {tipo_ot} FOLIO {folio_req} PARA {codigo}")

    elif tabla == 'compra':
        oc_segura = request.form.get('oc', '').strip() or f"OC-{datetime.now().strftime('%Y%m%d%H%M')}"
        db.session.add(CompraRepuesto(
            codigo_equipo=codigo, oc=oc_segura, descripcion=request.form.get('descripcion', 'Insumos'), 
            costo_pm_clp=clean_float(request.form.get('costo'), 0.0), fecha=datetime.now()
        ))
        registrar_auditoria(f"REGISTRÓ COMPRA {oc_segura} PARA {codigo}")
        
    elif tabla == 'bodega':
        item = request.form.get('nombre', '').strip()
        db.session.add(InventarioBodega(
            codigo_item=request.form.get('codigo_item', '').strip(), nombre=item,
            categoria=request.form.get('categoria', 'Filtro'), cantidad=clean_int(request.form.get('cantidad'), 0),
            ubicacion=request.form.get('ubicacion', '').strip()
        ))
        registrar_auditoria(f"AGREGÓ AL INVENTARIO EL ÍTEM '{item}'")
        
    elif tabla == 'personal':
        nom = request.form.get('nombre', '')
        db.session.add(Personal(nombre=nom, cargo='Operador', estado='Activo', equipo_asignado=request.form.get('equipo', 'Ninguno')))
        registrar_auditoria(f"REGISTRÓ AL OPERADOR {nom}")
        
    elif tabla == 'mecanico':
        nom = request.form.get('nombre', '')
        db.session.add(Mecanico(rut=request.form.get('rut', ''), nombre=nom, especialidad=request.form.get('especialidad', 'General'), estado='Activo'))
        registrar_auditoria(f"REGISTRÓ AL MECÁNICO {nom}")

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
    elif tabla == 'personal': obj = Personal.query.get(id)
    elif tabla == 'mecanico': obj = Mecanico.query.get(id)
    
    if obj:
        db.session.delete(obj)
        registrar_auditoria(f"ELIMINÓ REGISTRO PERMANENTEMENTE EN LA TABLA '{tabla}' (ID: {id})")
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

    if obj:
        if campo in ['costo_mantencion_clp', 'costo_pm_clp', 'horometro', 'kilometraje', 'lectura', 'cant', 'cantidad']:
            valor = clean_float(valor, 0.0) if 'costo' in campo else clean_int(valor)
        setattr(obj, campo, valor)
        registrar_auditoria(f"MODIFICÓ ATRIBUTO '{campo}' A '{valor}' EN TABLA '{tabla}'")
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
            UserClass = current_user.__class__
            columnas = list(UserClass.__table__.columns.keys())
            col_nombre = 'username' if 'username' in columnas else 'nombre'
            autor_name = getattr(current_user, col_nombre, getattr(current_user, 'nombre', 'Sistema'))
            
            db.session.add(RegistroChatter(modelo_ref='ot', registro_id=str(ot.id), autor=autor_name, accion='cambio_estado', valor_anterior=estado_anterior, valor_nuevo=nuevo))
            registrar_auditoria(f"MODIFICÓ STATUS OT {ot.folio} HACIA {nuevo}")
            
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

    if not mensaje and not archivo_url: return jsonify({"status": "error"}), 400

    UserClass = current_user.__class__
    columnas = list(UserClass.__table__.columns.keys())
    col_nombre = 'username' if 'username' in columnas else 'nombre'
    autor_name = getattr(current_user, col_nombre, getattr(current_user, 'nombre', 'Sistema'))

    log = RegistroChatter(modelo_ref=modelo, registro_id=registro_id, autor=autor_name, accion=accion, mensaje=mensaje, archivo_url=archivo_url)
    db.session.add(log)
    db.session.commit()
    return jsonify({"status": "success", "log": log.to_dict()})


# =====================================================================
# IMPRIMIBLES (REGISTRO Y FILTROS) - CERO ICONOS
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
    <head><meta charset="UTF-8"><title>Ficha Técnica - {eq.codigo}</title><script src="https://cdn.tailwindcss.com"></script><style>@media print {{ body {{ background: white; }} .print\\:hidden {{ display: none !important; }} .shadow-xl {{ box-shadow: none !important; border-color: transparent !important; }} @page {{ margin: 10mm; size: letter; }} }} table {{ page-break-inside: auto; }} tr {{ page-break-inside: avoid; page-break-after: auto; }}</style></head>
    <body class="bg-slate-50 p-6 font-sans text-slate-800 max-w-4xl mx-auto print:p-0 print:max-w-none">
        <div class="bg-white p-8 rounded-xl shadow-xl border border-slate-200 print:p-0 print:border-none print:shadow-none">
            <div class="flex justify-between items-center border-b-2 border-slate-800 pb-3 mb-5">
                <div><h1 class="text-xl font-black text-slate-900 leading-tight">FICHA TÉCNICA DEL EQUIPO</h1><p class="text-lg text-slate-700 font-bold tracking-widest">{eq.codigo}</p></div>
                <div class="text-right"><p class="text-xs font-bold text-slate-500 uppercase">Demotron S.A.</p><p class="text-[10px] text-slate-400 font-mono mt-1">Emisión: {datetime.now().strftime('%d/%m/%Y')}</p></div>
            </div>
            <div class="grid grid-cols-2 gap-4 mb-6">
                <div class="border border-slate-200 rounded p-4 bg-slate-50">
                    <h3 class="text-[10px] font-black text-slate-700 uppercase mb-2 tracking-wider">Identificación y Motor</h3>
                    <p class="text-xs mb-1"><span class="font-bold text-slate-500 w-24 inline-block">Tipo:</span> <span class="font-bold">{eq.tipo_equipo}</span></p>
                    <p class="text-xs mb-1"><span class="font-bold text-slate-500 w-24 inline-block">Marca/Mod:</span> {eq.marca} {eq.modelo}</p>
                    <p class="text-xs mb-1 mt-2"><span class="font-bold text-slate-500 w-24 inline-block">Patente:</span> <span class="font-mono bg-slate-200 px-2 py-0.5 rounded font-bold">{eq.patente or 'S/I'}</span></p>
                    <p class="text-xs mb-1"><span class="font-bold text-slate-500 w-24 inline-block">VIN:</span> <span class="font-mono">{eq.vin or 'S/I'}</span></p>
                    <p class="text-xs mb-1"><span class="font-bold text-slate-500 w-24 inline-block">N° Motor:</span> <span class="font-mono">{eq.n_motor or 'S/I'}</span></p>
                </div>
                <div class="border border-slate-200 rounded p-4 bg-slate-50">
                    <h3 class="text-[10px] font-black text-slate-700 uppercase mb-2 tracking-wider">Estado y Operatividad</h3>
                    <p class="text-xs mb-1"><span class="font-bold text-slate-500 w-24 inline-block">Ubicación:</span> {eq.ubicacion}</p>
                    <p class="text-xs mb-1"><span class="font-bold text-slate-500 w-24 inline-block">Operador:</span> {eq.responsable}</p>
                    <p class="text-xs mb-3"><span class="font-bold text-slate-500 w-24 inline-block">Estado:</span> <span class="bg-slate-200 px-2 py-0.5 rounded font-bold">{eq.estado_base}</span></p>
                    <div class="border-t border-slate-200 pt-2"></div>
                    <p class="text-xs mb-1"><span class="font-bold text-slate-500 w-24 inline-block">Lectura Act:</span> <span class="font-bold text-slate-800">{eq.lectura_actual or 0} {eq.control_base}</span></p>
                    <p class="text-xs"><span class="font-bold text-slate-500 w-24 inline-block">Mto. Restante:</span> <span class="font-bold text-slate-800">{eq.margen} {eq.control_base}</span></p>
                </div>
            </div>
            <h3 class="text-xs font-bold text-slate-800 uppercase mb-2 border-b border-slate-200 pb-1">Últimas Intervenciones</h3>
            <table class="w-full text-left text-[10px] mb-6 border border-slate-200">
                <thead><tr class="bg-slate-100 text-slate-600"><th class="p-1.5 border border-slate-200 uppercase tracking-wider">Fecha</th><th class="p-1.5 border border-slate-200 uppercase tracking-wider">Folio</th><th class="p-1.5 border border-slate-200 uppercase tracking-wider">Clase</th><th class="p-1.5 border border-slate-200 uppercase tracking-wider">Intervención</th><th class="p-1.5 border border-slate-200 uppercase tracking-wider">Mecánico</th><th class="p-1.5 border border-slate-200 uppercase tracking-wider">Odo/Hor.</th></tr></thead>
                <tbody>{"".join([f"<tr class='odd:bg-white even:bg-slate-50'><td class='p-1.5 border border-slate-200'>{o.fecha.strftime('%d/%m/%Y') if o.fecha else ''}</td><td class='p-1.5 border border-slate-200 font-bold text-slate-700'>{o.folio}</td><td class='p-1.5 border border-slate-200 font-bold text-slate-700 uppercase'>{o.tipo_ot}</td><td class='p-1.5 border border-slate-200 text-slate-800'>{o.tipo_mantencion}</td><td class='p-1.5 border border-slate-200 text-slate-600'>{o.mecanico}</td><td class='p-1.5 border border-slate-200 font-mono'>{o.lectura}</td></tr>" for o in ots])}</tbody>
            </table>
            <h3 class="text-xs font-bold text-slate-800 uppercase mb-2 border-b border-slate-200 pb-1">Historial de Lecturas</h3>
            <table class="w-full text-left text-[10px] mb-6 border border-slate-200">
                <thead><tr class="bg-slate-100 text-slate-600"><th class="p-1.5 border border-slate-200 uppercase tracking-wider">Fecha de Captura</th><th class="p-1.5 border border-slate-200 uppercase tracking-wider">Valor Registrado</th><th class="p-1.5 border border-slate-200 uppercase tracking-wider">Tipo de Medida</th></tr></thead>
                <tbody>{"".join([f"<tr class='odd:bg-white even:bg-slate-50'><td class='p-1.5 border border-slate-200'>{l.fecha.strftime('%d/%m/%Y') if l.fecha else ''}</td><td class='p-1.5 border border-slate-200 font-mono font-bold text-slate-800'>{'{:,.0f}'.format(l.horometro if l.horometro and l.horometro > 0 else l.kilometraje).replace(',','.')}</td><td class='p-1.5 border border-slate-200 font-bold text-slate-500'>{'HORAS' if l.horometro and l.horometro > 0 else 'KILÓMETROS'}</td></tr>" for l in lecturas])}</tbody>
            </table>
            <div class="text-center mt-8 pt-4 border-t border-slate-200 print:hidden flex justify-center gap-3">
                <button onclick="window.print()" class="bg-slate-800 text-white px-5 py-1.5 rounded text-xs font-bold shadow hover:bg-slate-700 transition uppercase tracking-wider">Imprimir</button>
                <button onclick="window.close()" class="bg-slate-200 text-slate-700 px-5 py-1.5 rounded text-xs font-bold shadow hover:bg-slate-300 transition uppercase tracking-wider">Cerrar</button>
            </div>
        </div>
    </body>
    </html>
    """
    return render_template_string(html)

@api_bp.route('/api/imprimir_filtros/<codigo>')
@login_required
def imprimir_filtros(codigo):
    eq = Equipo.query.filter_by(codigo=codigo).first_or_404()
    filtros = FiltroEquipo.query.filter_by(codigo_equipo=codigo).all()
    signature_actual = set()
    for f in filtros:
        row_data = (f.sistema, f.fleetguard, f.baldwind, f.originales, f.donaldson, f.otra)
        if any(val not in ['-', '', 'nan', None] for val in [f.fleetguard, f.baldwind, f.originales, f.donaldson, f.otra]): signature_actual.add(row_data)
    equipos_similares = []
    if signature_actual:
        todos_filtros = FiltroEquipo.query.filter(FiltroEquipo.codigo_equipo != codigo).all()
        from collections import defaultdict
        mapa_filtros = defaultdict(list)
        for f in todos_filtros: mapa_filtros[f.codigo_equipo].append(f)
        for cod_eq, lista_f in mapa_filtros.items():
            sig_eq = set()
            for f in lista_f:
                row_data = (f.sistema, f.fleetguard, f.baldwind, f.originales, f.donaldson, f.otra)
                if any(val not in ['-', '', 'nan', None] for val in [f.fleetguard, f.baldwind, f.originales, f.donaldson, f.otra]): sig_eq.add(row_data)
            if sig_eq and sig_eq == signature_actual: equipos_similares.append(cod_eq)
    equipos_similares = sorted(equipos_similares)
    
    html = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head><meta charset="UTF-8"><title>Pauta de Filtros - {eq.codigo}</title><script src="https://cdn.tailwindcss.com"></script><style>@media print {{ body {{ background: white; font-size: 11px; }} .print\\:hidden {{ display: none !important; }} .shadow-xl {{ box-shadow: none !important; border-color: transparent !important; }} @page {{ margin: 10mm; size: letter; }} }} table {{ page-break-inside: auto; }} tr {{ page-break-inside: avoid; page-break-after: auto; }}</style></head>
    <body class="bg-slate-50 p-4 font-sans text-slate-800 max-w-4xl mx-auto print:p-0 print:max-w-none">
        <div class="bg-white p-6 rounded-xl shadow-xl border border-slate-200 print:p-0 print:border-none print:shadow-none">
            <div class="flex justify-between items-start border-b-2 border-slate-800 pb-2 mb-4">
                <div><h1 class="text-2xl font-black text-slate-900 leading-tight uppercase tracking-tighter">PAUTA DE FILTROS</h1><p class="text-[11px] font-bold text-slate-500 mt-1 uppercase">Gestión de Flota - Demotron S.A.</p><p class="text-[10px] text-slate-400 mt-0.5 font-mono">Emisión: {datetime.now().strftime('%d/%m/%Y')}</p></div>
                <div class="text-right flex flex-col items-end"><span class="text-[9px] text-slate-500 font-bold uppercase tracking-widest mb-1">Código de Equipo</span><div class="bg-slate-900 text-white px-4 py-1.5 rounded-lg text-3xl font-black tracking-tighter print:border-2 print:border-slate-900 print:text-slate-900 print:bg-white">{eq.codigo}</div></div>
            </div>
            <div class="grid grid-cols-2 gap-4 mb-4">
                <div class="border border-slate-200 rounded-lg p-3 bg-slate-50">
                    <h3 class="text-[10px] font-black text-slate-800 uppercase mb-2 tracking-widest border-b border-slate-200 pb-1">Especificaciones Técnicas</h3>
                    <div class="grid grid-cols-2 gap-y-2">
                        <p><span class="font-bold text-slate-500 block text-[9px] uppercase">Marca</span> <span class="font-black text-slate-800 text-sm leading-none">{eq.marca or 'S/I'}</span></p>
                        <p><span class="font-bold text-slate-500 block text-[9px] uppercase">Modelo</span> <span class="font-black text-slate-800 text-sm leading-none">{eq.modelo or 'S/I'}</span></p>
                        <p class="col-span-2"><span class="font-bold text-slate-500 block text-[9px] uppercase">VIN / Número de Chasis</span> <span class="font-mono font-bold text-slate-700 text-xs">{eq.vin or 'S/I'}</span></p>
                        <p class="col-span-2"><span class="font-bold text-slate-500 block text-[9px] uppercase">Número de Motor</span> <span class="font-mono font-bold text-slate-700 text-xs">{eq.n_motor or 'S/I'}</span></p>
                    </div>
                </div>
                <div class="border border-slate-200 rounded-lg p-3 bg-slate-50 flex flex-col">
                    <h3 class="text-[10px] font-black text-slate-800 uppercase mb-2 tracking-widest border-b border-slate-200 pb-1">Compatibilidad de Flota</h3>
                    <p class="text-[9px] font-bold text-slate-500 uppercase mb-2">Equipos que ocupan los mismos filtros:</p>
                    <div class="flex flex-wrap gap-1.5 flex-1 content-start">
    """
    if equipos_similares:
        for sim in equipos_similares: html += f"<span class='bg-slate-200 text-slate-800 font-bold px-2 py-0.5 rounded text-[11px] border border-slate-300 print:bg-white print:border-slate-500'>{sim}</span>"
    else: html += "<span class='text-slate-400 text-[11px] italic font-semibold'>Este equipo tiene una pauta única en la flota.</span>"
    html += f"""
                    </div>
                </div>
            </div>
            <h3 class="text-xs font-bold text-slate-800 uppercase mb-2 border-b border-slate-200 pb-1">Tabla de Repuestos y Filtros</h3>
            <table class="w-full text-left text-[11px] mb-4 border border-slate-300">
                <thead><tr class="bg-slate-800 text-white print:bg-slate-100 print:text-slate-800"><th class="p-1.5 border border-slate-300 uppercase text-[9px] tracking-wider">Sistema</th><th class="p-1.5 border border-slate-300 text-center uppercase text-[9px] tracking-wider">Cant</th><th class="p-1.5 border border-slate-300 uppercase text-[9px] tracking-wider">Fleetguard</th><th class="p-1.5 border border-slate-300 uppercase text-[9px] tracking-wider">Baldwin</th><th class="p-1.5 border border-slate-300 uppercase text-[9px] tracking-wider">Originales</th><th class="p-1.5 border border-slate-300 uppercase text-[9px] tracking-wider">Donaldson</th><th class="p-1.5 border border-slate-300 uppercase text-[9px] tracking-wider">Alternativo</th></tr></thead>
                <tbody>
                    {"".join([f"<tr class='odd:bg-white even:bg-slate-50'><td class='p-1.5 border border-slate-300 font-bold text-slate-800'>{f.sistema}</td><td class='p-1.5 border border-slate-300 text-center font-bold text-sm'>{f.cant}</td><td class='p-1.5 border border-slate-300 font-mono text-[11px] font-semibold text-slate-700'>{f.fleetguard}</td><td class='p-1.5 border border-slate-300 font-mono text-[11px] font-semibold text-slate-700'>{f.baldwind}</td><td class='p-1.5 border border-slate-300 font-mono text-[11px] font-semibold text-slate-700'>{f.originales}</td><td class='p-1.5 border border-slate-300 font-mono text-[11px] font-semibold text-slate-700'>{f.donaldson}</td><td class='p-1.5 border border-slate-300 font-mono text-[11px] font-semibold text-slate-700'>{f.otra}</td></tr>" for f in filtros])}
                    <tr class='bg-white'><td class='p-1.5 border border-slate-300 h-6'></td><td class='p-1.5 border border-slate-300'></td><td class='p-1.5 border border-slate-300'></td><td class='p-1.5 border border-slate-300'></td><td class='p-1.5 border border-slate-300'></td><td class='p-1.5 border border-slate-300'></td><td class='p-1.5 border border-slate-300'></td></tr>
                    <tr class='bg-white'><td class='p-1.5 border border-slate-300 h-6'></td><td class='p-1.5 border border-slate-300'></td><td class='p-1.5 border border-slate-300'></td><td class='p-1.5 border border-slate-300'></td><td class='p-1.5 border border-slate-300'></td><td class='p-1.5 border border-slate-300'></td><td class='p-1.5 border border-slate-300'></td></tr>
                </tbody>
            </table>
            <div class="mt-4 border border-slate-300 p-3 rounded bg-slate-50">
                <p class="text-[9px] font-bold text-slate-700 uppercase mb-1 tracking-wider">Nota Técnica - Homologación y Sustitución de Componentes</p>
                <p class="text-[9px] text-slate-600 text-justify">Por motivos de disponibilidad de inventario o equivalencias de ingeniería, los elementos filtrantes detallados pueden ser sustituidos por alternativas OEM certificadas de igual o mayor estándar. Es mandato registrar en las líneas dispuestas superiormente cualquier divergencia técnica, actualización de código o faltante de repuesto detectado durante el proceso de intervención.</p>
            </div>
            <div class="text-center mt-6 pt-4 border-t border-slate-200 print:hidden flex justify-center gap-3">
                <button onclick="window.print()" class="bg-slate-800 text-white px-5 py-1.5 rounded text-xs font-bold shadow hover:bg-slate-700 transition uppercase tracking-wider">Imprimir</button>
                <button onclick="window.close()" class="bg-slate-200 text-slate-700 px-5 py-1.5 rounded text-xs font-bold shadow hover:bg-slate-300 transition uppercase tracking-wider">Cerrar</button>
            </div>
        </div>
    </body>
    </html>
    """
    return render_template_string(html)
