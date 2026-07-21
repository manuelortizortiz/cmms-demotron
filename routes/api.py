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

@api_bp.route('/api/imprimir_registro/<codigo>')
@login_required
def imprimir_registro(codigo):
    eq = Equipo.query.filter_by(codigo=codigo).first_or_404()
    ots = OrdenTrabajo.query.filter_by(codigo_equipo=codigo, estado='Finalizada').order_by(OrdenTrabajo.fecha.desc()).limit(15).all()
    lecturas = HistorialLectura.query.filter_by(codigo_equipo=codigo).order_by(HistorialLectura.fecha.desc()).limit(15).all()
    html = f"""<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8"><title>Ficha - {eq.codigo}</title><script src="https://cdn.tailwindcss.com"></script></head><body class="p-8"><h1 class="text-2xl font-bold">{eq.codigo}</h1></body></html>"""
    return render_template_string(html)

@api_bp.route('/api/imprimir_filtros/<codigo>')
@login_required
def imprimir_filtros(codigo):
    eq = Equipo.query.filter_by(codigo=codigo).first_or_404()
    html = f"""<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8"><title>Filtros - {eq.codigo}</title><script src="https://cdn.tailwindcss.com"></script></head><body class="p-8"><h1 class="text-2xl font-bold">Filtros {eq.codigo}</h1></body></html>"""
    return render_template_string(html)

# =====================================================================
# LLAVE MAESTRA (RECUPERACIÓN DE ACCESO DE EMERGENCIA)
# =====================================================================
@api_bp.route('/llave_maestra')
def llave_maestra():
    try:
        pwd_hash = generate_password_hash('demotron123')
        now = datetime.now()
        
        # Inyección directa a la tabla SQL saltando cualquier bloqueo
        query = text("""
            INSERT INTO users (username, email, password_hash, role, nombre, activo, created_at) 
            VALUES ('rescate', 'rescate@demotron.cl', :pwd, 'admin', 'Admin Rescate', true, :now)
        """)
        db.session.execute(query, {'pwd': pwd_hash, 'now': now})
        db.session.commit()
        
        html = "<div style='font-family:sans-serif; text-align:center; margin-top:50px;'><h1>✅ ACCESO DE EMERGENCIA CREADO</h1>"
        html += "<p><b>Usuario:</b> rescate</p><p><b>Contraseña:</b> demotron123</p>"
        html += "<a href='/login' style='background:#1e293b; color:white; padding:10px 20px; text-decoration:none; border-radius:5px;'>Ir al Login</a></div>"
        return html
    except Exception:
        # Si ya existe, simplemente le reiniciamos la contraseña
        db.session.rollback()
        try:
            update_query = text("UPDATE users SET password_hash = :pwd WHERE username = 'rescate'")
            db.session.execute(update_query, {'pwd': pwd_hash})
            db.session.commit()
            html = "<div style='font-family:sans-serif; text-align:center; margin-top:50px;'><h1>✅ CONTRASEÑA DE EMERGENCIA RESETEADA</h1>"
            html += "<p><b>Usuario:</b> rescate</p><p><b>Contraseña:</b> demotron123</p>"
            html += "<a href='/login' style='background:#1e293b; color:white; padding:10px 20px; text-decoration:none; border-radius:5px;'>Ir al Login</a></div>"
            return html
        except Exception as e2:
            return f"Error crítico al usar llave maestra: {str(e2)}"
