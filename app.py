import os
import json
import random
import pandas as pd
import numpy as np
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'demotron_master_key_super_segura'

ruta_db = os.getenv('DATABASE_URL', 'sqlite:///demotron_master.db')
if ruta_db.startswith("postgres://"):
    ruta_db = ruta_db.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = ruta_db
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ==========================================
# 1. MODELOS DE BASE DE DATOS (NUEVO ERP)
# ==========================================
class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True)
    password_hash = db.Column(db.String(250))
    rol = db.Column(db.String(50)) # Admin, Mecanico, Supervisor

class LogActividad(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=datetime.now)
    usuario = db.Column(db.String(50))
    accion = db.Column(db.String(250))

class BodegaInsumo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), unique=True)
    descripcion = db.Column(db.String(150))
    cantidad = db.Column(db.Integer, default=0)
    ubicacion_estante = db.Column(db.String(50))

class Personal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(50)) # Mecanico o Conductor
    nombre = db.Column(db.String(100))
    rut = db.Column(db.String(20))
    especialidad_licencia = db.Column(db.String(100))
    estado = db.Column(db.String(50), default="Activo")

class Equipo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), unique=True)
    tipo_equipo = db.Column(db.String(100))
    marca = db.Column(db.String(50))
    modelo = db.Column(db.String(100))
    ano = db.Column(db.Integer)
    ubicacion = db.Column(db.String(100))
    responsable = db.Column(db.String(100))
    estado_base = db.Column(db.String(50))      
    control_base = db.Column(db.String(50))     
    frecuencia_base = db.Column(db.Integer)    
    promedio_diario = db.Column(db.Float)
    lectura_actual = db.Column(db.Integer, default=0)
    proxima_pm = db.Column(db.Integer, default=0)
    vin = db.Column(db.String(100), default="")
    n_motor = db.Column(db.String(100), default="")
    patente = db.Column(db.String(50), default="")

    @property
    def margen(self): return (self.proxima_pm or 0) - (self.lectura_actual or 0)

class OrdenTrabajo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime)
    codigo_equipo = db.Column(db.String(50))
    tipo_ot = db.Column(db.String(50), default="Preventiva") # Preventiva o Correctiva
    tipo_mantencion = db.Column(db.String(100))
    lectura = db.Column(db.Integer, default=0)
    folio = db.Column(db.String(50))
    lugar = db.Column(db.String(100))
    costo_mantencion_clp = db.Column(db.Float, default=0.0)
    estado = db.Column(db.String(50)) 

class HistorialLectura(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime); codigo_equipo = db.Column(db.String(50)); horometro = db.Column(db.Integer, default=0)
    kilometraje = db.Column(db.Integer, default=0); obra_ubicacion = db.Column(db.String(100)); responsable = db.Column(db.String(100)); observacion = db.Column(db.String(250))

class CompraRepuesto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime); oc = db.Column(db.String(100)); codigo_equipo = db.Column(db.String(50)); descripcion = db.Column(db.String(250)); proveedor = db.Column(db.String(100)); costo_pm_clp = db.Column(db.Float, default=0.0); estado_oc = db.Column(db.String(100))

# --- INICIALIZACIÓN Y USUARIO ADMIN ---
with app.app_context(): 
    db.create_all()
    if not Usuario.query.filter_by(username='admin').first():
        admin = Usuario(username='admin', password_hash=generate_password_hash('admin'), rol='Administrador')
        db.session.add(admin)
        db.session.commit()

def registrar_log(accion):
    user = session.get('username', 'Sistema')
    log = LogActividad(usuario=user, accion=accion)
    db.session.add(log)
    db.session.commit()

def format_num(val):
    try: return f"{int(float(str(val))):,}".replace(",", ".")
    except: return "0"

def format_clp(val):
    try: return f"$ {int(float(str(val))):,}".replace(",", ".")
    except: return "$ 0"

def buscar_foto_por_tipo(tipo_equipo):
    if not tipo_equipo: return None
    t = str(tipo_equipo).lower()
    if "man" in t and "tolva" in t: return "/static/equipos_real/camion_man_tolva.png"
    if "tracto" in t: return "/static/equipos_real/tractocamion.png"
    if "camioneta" in t: return "/static/equipos_real/maxus_t60.png"
    if "minibus" in t or "mini bus" in t: return "/static/equipos_real/minibus.png"
    if any(x in t for x in ["liviano", "pintura", "slurry", "plano"]): return "/static/equipos_real/camion_liviano.png"
    return None

# ==========================================
# RUTAS DE LOGIN Y AUTENTICACIÓN
# ==========================================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = request.form.get('username')
        pwd = request.form.get('password')
        usuario = Usuario.query.filter_by(username=user).first()
        if usuario and check_password_hash(usuario.password_hash, pwd):
            session['user_id'] = usuario.id
            session['username'] = usuario.username
            session['rol'] = usuario.rol
            registrar_log("Inicio de sesión exitoso")
            return redirect(url_for('dashboard'))
        return render_template('login.html', error="Usuario o contraseña incorrectos")
    return render_template('login.html', error=None)

@app.route('/logout')
def logout():
    registrar_log("Cierre de sesión")
    session.clear()
    return redirect(url_for('login'))

# ==========================================
# RUTAS DEL ERP
# ==========================================
@app.route('/', strict_slashes=False)
@app.route('/erp', strict_slashes=False)
def dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    try:
        eqs_db = Equipo.query.all(); ots_db = OrdenTrabajo.query.order_by(OrdenTrabajo.id.desc()).all()
        compras_db = CompraRepuesto.query.order_by(CompraRepuesto.fecha.desc()).all()
        lecturas_db = HistorialLectura.query.order_by(HistorialLectura.fecha.desc()).all()
        logs_db = LogActividad.query.order_by(LogActividad.id.desc()).limit(100).all()

        equipos, taller, criticos = [], [], []
        conteo_estado = {'Operativo': 0, 'Fuera de Servicio': 0, 'Taller': 0}
        
        for e in eqs_db:
            eq_data = {'codigo': e.codigo, 'tipo': e.tipo_equipo, 'ubicacion': e.ubicacion or '', 'responsable': e.responsable or '', 'ctrl': e.control_base, 'lectura': format_num(e.lectura_actual), 'proxima': format_num(e.proxima_pm), 'margen': e.margen, 'margen_str': format_num(e.margen), 'estado': e.estado_base, 'foto_url': buscar_foto_por_tipo(e.tipo_equipo), 'vin': e.vin, 'motor': e.n_motor, 'patente': e.patente}
            equipos.append(eq_data)
            status_limpio = 'Fuera de Servicio' if e.estado_base in ['Fuera de Servicio', 'No operativo'] else e.estado_base
            conteo_estado[status_limpio] = conteo_estado.get(status_limpio, 0) + 1
            if e.estado_base == 'Taller': taller.append(eq_data)
            if e.margen < 0 and e.estado_base != 'Fuera de Servicio': criticos.append(eq_data)

        # LÓGICA DE KANBAN PERSISTENTE
        kanban_tareas = {'Pendiente': [], 'En Progreso': [], 'En Revisión': [], 'Completado': []}
        ots_activas = [ot for ot in ots_db if ot.estado in kanban_tareas]
        equipos_con_ot = [ot.codigo_equipo for ot in ots_activas]

        for ot in ots_activas:
            kanban_tareas[ot.estado].append({'codigo': ot.codigo_equipo, 'tipo': ot.folio, 'margen': ot.fecha.strftime('%d/%m/%Y'), 'estado': ot.estado})

        # Atrasados que aún no tienen OT, van a Pendiente
        for c in criticos:
            if c['codigo'] not in equipos_con_ot:
                kanban_tareas['Pendiente'].append({'codigo': c['codigo'], 'tipo': c['tipo'], 'margen': c['margen_str'], 'estado': 'Pendiente'})

        todas_mantenciones = [{'fecha': m.fecha.strftime('%d/%m/%Y'), 'codigo': m.codigo_equipo, 'ot_generada': m.folio, 'lugar': m.lugar, 'costo_str': format_clp(m.costo_mantencion_clp), 'estado': m.estado, 'tipo_ot': m.tipo_ot} for m in ots_db]
        todas_compras = [{'fecha': c.fecha.strftime('%d/%m/%Y'), 'oc': c.oc, 'codigo': c.codigo_equipo, 'descripcion': c.descripcion, 'proveedor': c.proveedor, 'costo_str': format_clp(c.costo_pm_clp), 'estado': c.estado_oc} for c in compras_db]
        todas_lecturas = [{'fecha': l.fecha.strftime('%d/%m/%Y %H:%M'), 'codigo': l.codigo_equipo, 'valor_str': format_num(l.horometro if l.horometro>0 else l.kilometraje), 'tipo': 'HR' if l.horometro>0 else 'KM', 'ubicacion': l.obra_ubicacion, 'responsable': l.responsable, 'obs': l.observacion} for l in lecturas_db]
        logs_list = [{'fecha': l.fecha.strftime('%d/%m/%Y %H:%M:%S'), 'usuario': l.usuario, 'accion': l.accion} for l in logs_db]

        kpis = {'total': len(eqs_db), 'operativos': conteo_estado.get('Operativo',0), 'fuera': conteo_estado.get('Fuera de Servicio',0), 'atrasados': len(criticos), 'proximos': 0, 'ot_abiertas': len(ots_activas), 'costo_mes_str': format_clp(sum(c.costo_pm_clp or 0 for c in compras_db))}

        return render_template('index.html', kpis=kpis, eqs=equipos, criticos=criticos, taller=taller, mantenciones=todas_mantenciones, compras=todas_compras, lecturas=todas_lecturas, kanban=kanban_tareas, logs=logs_list, current_user=session['username'])
    except Exception as e: return f"Error crítico: {str(e)}"


@app.route('/update_kanban', methods=['POST'])
def update_kanban():
    if 'user_id' not in session: return jsonify({"status": "error"}), 403
    data = request.json
    codigo = data.get('codigo'); columna_destino = data.get('estado')
    
    ot_activa = OrdenTrabajo.query.filter(OrdenTrabajo.codigo_equipo == codigo, OrdenTrabajo.estado.in_(['Pendiente', 'En Progreso', 'En Revisión'])).first()

    if ot_activa:
        ot_activa.estado = columna_destino
        registrar_log(f"Movió OT {ot_activa.folio} ({codigo}) a {columna_destino}")
    else:
        # Crea nueva OT si no existía
        ultimo_ot = OrdenTrabajo.query.order_by(OrdenTrabajo.id.desc()).first()
        siguiente = (ultimo_ot.id + 1) if ultimo_ot else 1
        folio_nuevo = f"OT-DMT-0{1820 + siguiente}"
        nueva_ot = OrdenTrabajo(fecha=datetime.now(), codigo_equipo=codigo, estado=columna_destino, folio=folio_nuevo, tipo_mantencion="Preventivo", tipo_ot="Preventiva")
        db.session.add(nueva_ot)
        registrar_log(f"Creó nueva OT {folio_nuevo} para {codigo} en {columna_destino}")
    
    db.session.commit()
    return jsonify({"status": "success"})

@app.route('/update_inline', methods=['POST'])
def update_inline():
    if 'user_id' not in session: return jsonify({"status": "error"}), 403
    try:
        data = request.json
        equipo = Equipo.query.filter_by(codigo=data.get('codigo')).first()
        if equipo:
            setattr(equipo, data.get('campo'), data.get('valor'))
            db.session.commit()
            registrar_log(f"Actualizó {data.get('campo')} del equipo {equipo.codigo}")
            return jsonify({"status": "success"})
        return jsonify({"status": "error"}), 404
    except: return jsonify({"status": "error"}), 500

@app.route('/admin/cargar_sql_final', strict_slashes=False)
def cargar_sql_final():
    if 'user_id' not in session: return redirect(url_for('login'))
    # Lógica de carga de Excel adaptada
    archivo_excel = "CMMS DEMOTRON MANU ORTIZ.xlsx"
    if not os.path.exists(archivo_excel): return "Error: Falta Excel principal."
    try:
        with db.engine.connect() as conn:
            conn.execute(db.text("DROP TABLE IF EXISTS compra_repuesto CASCADE; DROP TABLE IF EXISTS orden_trabajo CASCADE; DROP TABLE IF EXISTS historial_lectura CASCADE; DROP TABLE IF EXISTS equipo CASCADE;"))
            conn.commit()
        db.create_all()

        df_eq = pd.read_excel(archivo_excel, sheet_name="Equipos", skiprows=2).replace({np.nan: None})
        for _, row in df_eq.iterrows():
            if not row.iloc[0]: continue
            eq = Equipo(codigo=str(row.iloc[0]).strip(), tipo_equipo=row.iloc[1], marca=row.iloc[2], modelo=str(row.iloc[3]).strip() if row.iloc[3] else None, ano=clean_int(row.iloc[4], None), ubicacion=row.iloc[5], responsable=row.iloc[6], estado_base=str(row.iloc[7]).strip() if row.iloc[7] else 'Operativo', control_base=str(row.iloc[8]).strip().upper() if row.iloc[8] else 'HORAS', frecuencia_base=clean_int(row.iloc[9], 250))
            db.session.add(eq)
        db.session.commit()

        # ARCHIVO DETALLES EQUIPO (VIN, Motor, Patente)
        archivo_detalles = "detalles de equipo.xlsx"
        if os.path.exists(archivo_detalles):
            df_det = pd.read_excel(archivo_detalles)
            df_det.columns = [str(c).strip() for c in df_det.columns]
            for _, row in df_det.iterrows():
                cod = str(row.get('Código', row.get('Codigo', ''))).strip()
                eq = Equipo.query.filter_by(codigo=cod).first()
                if eq:
                    eq.patente = str(row.get('Placa', ''))
                    eq.vin = str(row.get('N° Chasis', ''))
                    eq.n_motor = str(row.get('N° Motor', ''))
            db.session.commit()

        registrar_log("Reinició la base de datos desde Excel")
        return redirect(url_for('dashboard'))
    except Exception as e: return f"Error técnico al inyectar: {str(e)}"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
