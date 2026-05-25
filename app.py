import os
import random
import pandas as pd
import numpy as np
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'demotron_seguridad_maxima_2026'

ruta_db = os.getenv('DATABASE_URL', 'sqlite:///demotron_master.db')
if ruta_db.startswith("postgres://"):
    ruta_db = ruta_db.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = ruta_db
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ==========================================
# MODELOS DE BASE DE DATOS
# ==========================================
class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True)
    password_hash = db.Column(db.String(250))
    rol = db.Column(db.String(50))

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

class Personal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(50)) 
    nombre = db.Column(db.String(100))
    cargo = db.Column(db.String(100), default="Operador de Maquinaria")
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
    lectura_actual = db.Column(db.Integer, default=0)
    proxima_pm = db.Column(db.Integer, default=0)
    vin = db.Column(db.String(100), default="")
    n_motor = db.Column(db.String(100), default="")
    patente = db.Column(db.String(50), default="")
    pauta_filtros = db.Column(db.Text, default="Registrar filtros principales y alternativos de la unidad...")
    planificacion_mantencion = db.Column(db.Text, default="Planificación detallada de los ciclos de mantenimiento...")

    @property
    def margen(self): return (self.proxima_pm or 0) - (self.lectura_actual or 0)

class OrdenTrabajo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime)
    codigo_equipo = db.Column(db.String(50))
    tipo_ot = db.Column(db.String(50), default="Preventiva")
    tipo_mantencion = db.Column(db.String(100))
    lectura = db.Column(db.Integer, default=0)
    es_pm = db.Column(db.String(20))
    folio = db.Column(db.String(50))
    lugar = db.Column(db.String(100))
    costo_mantencion_clp = db.Column(db.Float, default=0.0)
    estado = db.Column(db.String(50)) 

class HistorialLectura(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime)
    codigo_equipo = db.Column(db.String(50))
    horometro = db.Column(db.Integer, default=0)
    kilometraje = db.Column(db.Integer, default=0)
    obra_ubicacion = db.Column(db.String(100))
    responsable = db.Column(db.String(100))
    observacion = db.Column(db.String(250))

class CompraRepuesto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime)
    oc = db.Column(db.String(100))
    codigo_equipo = db.Column(db.String(50))
    descripcion = db.Column(db.String(250))
    proveedor = db.Column(db.String(100))
    costo_pm_clp = db.Column(db.Float, default=0.0)
    estado_oc = db.Column(db.String(100))

with app.app_context(): 
    db.create_all()
    if not Usuario.query.filter_by(username='admin').first():
        admin = Usuario(username='admin', password_hash=generate_password_hash('admin'), rol='Administrador')
        db.session.add(admin)
        db.session.commit()

# ==========================================
# FUNCIONES AUXILIARES
# ==========================================
def clean_string(val):
    s = str(val).strip()
    return "" if s.lower() in ['nan', 'none', ''] else s

def clean_int(val, default=0):
    try:
        s = clean_string(val)
        return int(float(s)) if s else default
    except: return default

def clean_float(val, default=0.0):
    try:
        if val is None: return default
        if isinstance(val, (int, float)): return float(val)
        s = clean_string(val).replace('$', '').replace(' ', '')
        return float(s.replace('.', '').replace(',', '.')) if s else default
    except: return default

def format_num(val):
    try: return f"{int(float(str(val))):,}".replace(",", ".")
    except: return "0"

def format_clp(val):
    try: return f"$ {int(float(str(val))):,}".replace(",", ".")
    except: return "$ 0"

def buscar_foto_por_tipo(tipo_equipo, marca=""):
    t = str(tipo_equipo).lower(); m = str(marca).lower()
    if "tolva" in t: return "/static/equipos_real/camion_man_tolva.png"
    if "tracto" in t: return "/static/equipos_real/tractocamion.png"
    if "camioneta" in t: return "/static/equipos_real/maxus_t60.png"
    if any(x in t for x in ["furgon", "furgón", "minibus", "bus"]): return "/static/equipos_real/minibus.png"
    if any(x in t for x in ["liviano", "pintura", "slurry", "plano"]): return "/static/equipos_real/camion_liviano.png"
    return "/static/equipos_real/tractocamion.png"

# ==========================================
# RUTAS DE AUTENTICACIÓN Y FILTROS
# ==========================================
@app.before_request
def require_login():
    rutas_permitidas = ['login', 'static']
    if request.endpoint not in rutas_permitidas and 'user_id' not in session:
        return redirect(url_for('login'))

def registrar_log(accion):
    user = session.get('username', 'Sistema')
    log = LogActividad(usuario=user, accion=accion)
    db.session.add(log)
    db.session.commit()

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
        return render_template('login.html', error="Credenciales incorrectas")
    return render_template('login.html', error=None)

@app.route('/logout')
def logout():
    registrar_log("Cierre de sesión")
    session.clear()
    return redirect(url_for('login'))

# ==========================================
# RUTAS CORE ERP
# ==========================================
@app.route('/', strict_slashes=False)
@app.route('/erp', strict_slashes=False)
def dashboard():
    try:
        eqs_db = Equipo.query.all()
        ots_db = OrdenTrabajo.query.order_by(OrdenTrabajo.id.desc()).all()
        compras_db = CompraRepuesto.query.order_by(CompraRepuesto.fecha.desc()).all()
        lecturas_db = HistorialLectura.query.order_by(HistorialLectura.fecha.desc()).all()
        logs_db = LogActividad.query.order_by(LogActividad.id.desc()).limit(100).all()

        equipos, taller, criticos = [], [], []
        conteo_estado = {'Operativo': 0, 'Fuera de Servicio': 0, 'Taller': 0}
        conteo_ubicacion = {}

        for e in eqs_db:
            eq_data = {
                'codigo': e.codigo, 'tipo': e.tipo_equipo, 'ubicacion': e.ubicacion or 'Sin Ubicación',
                'responsable': e.responsable or 'Sin Asignar', 'ctrl': e.control_base,
                'lectura': format_num(e.lectura_actual), 'proxima': format_num(e.proxima_pm),
                'margen': e.margen, 'margen_str': format_num(e.margen), 'estado': e.estado_base,
                'foto_url': buscar_foto_por_tipo(e.tipo_equipo, e.marca), 'vin': e.vin, 'motor': e.n_motor, 'patente': e.patente
            }
            equipos.append(eq_data)
            status_limpio = 'Fuera de Servicio' if e.estado_base in ['Fuera de Servicio', 'No operativo'] else e.estado_base
            conteo_estado[status_limpio] = conteo_estado.get(status_limpio, 0) + 1
            
            if e.ubicacion:
                conteo_ubicacion[e.ubicacion] = conteo_ubicacion.get(e.ubicacion, 0) + 1
            if e.estado_base == 'Taller': taller.append(eq_data)
            if e.margen < 0 and e.estado_base != 'Fuera de Servicio': criticos.append(eq_data)

        equipos_aleatorios = list(equipos)
        random.shuffle(equipos_aleatorios)

        kanban_tareas = {'Pendiente': [], 'En Progreso': [], 'En Revisión': [], 'Completado': []}
        ots_activas = [ot for ot in ots_db if ot.estado in kanban_tareas]
        equipos_con_ot = [ot.codigo_equipo for ot in ots_activas]

        for ot in ots_activas:
            kanban_tareas[ot.estado].append({'codigo': ot.codigo_equipo, 'tipo': ot.folio, 'margen': ot.fecha.strftime('%d/%m/%Y'), 'estado': ot.estado})

        for c in criticos:
            if c['codigo'] not in equipos_con_ot:
                kanban_tareas['Pendiente'].append({'codigo': c['codigo'], 'tipo': c['tipo'], 'margen': c['margen_str'], 'estado': 'Pendiente'})

        todas_mantenciones = [{'fecha': m.fecha.strftime('%d/%m/%Y') if m.fecha else 'S/F', 'fecha_iso': m.fecha.strftime('%Y-%m-%d') if m.fecha else '', 'codigo': m.codigo_equipo, 'ot_generada': m.folio, 'lugar': m.lugar, 'costo_str': format_clp(m.costo_mantencion_clp), 'estado': m.estado, 'tipo_ot': m.tipo_ot, 'tipo_mantencion': m.tipo_mantencion, 'lectura_str': format_num(m.lectura)} for m in ots_db]
        todas_compras = [{'fecha': c.fecha.strftime('%d/%m/%Y'), 'oc': c.oc, 'codigo': c.codigo_equipo, 'descripcion': c.descripcion, 'proveedor': c.proveedor, 'costo_str': format_clp(c.costo_pm_clp), 'estado': c.estado_oc} for c in compras_db]
        todas_lecturas = [{'fecha': l.fecha.strftime('%d/%m/%Y %H:%M'), 'codigo': l.codigo_equipo, 'valor_str': format_num(l.horometro if l.horometro>0 else l.kilometraje), 'tipo': 'HR' if l.horometro>0 else 'KM', 'ubicacion': l.obra_ubicacion, 'responsable': l.responsable, 'obs': l.observacion} for l in lecturas_db]
        logs_list = [{'fecha': l.fecha.strftime('%d/%m/%Y %H:%M:%S'), 'usuario': l.usuario, 'accion': l.accion} for l in logs_db]

        lista_operadores = []
        for p in Personal.query.filter_by(tipo='Conductor').all():
            eq_asignado = Equipo.query.filter_by(responsable=p.nombre).first()
            lista_operadores.append({'id': p.id, 'nombre': p.nombre, 'cargo': p.cargo, 'estado': p.estado, 'equipo_asignado': eq_asignado.codigo if eq_asignado else 'Sin Asignar', 'ubicacion': eq_asignado.ubicacion if eq_asignado else 'Desconocida'})

        # LOGICA GRAFICO DE COSTOS HISTORICOS DESDE FEBRERO
        mes_actual = datetime.now().month
        nombres_meses = {2: "Feb", 3: "Mar", 4: "Abr", 5: "May", 6: "Jun", 7: "Jul", 8: "Ago", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic"}
        dict_costos = {2:0, 3:0, 4:0, 5:0}
        if mes_actual not in dict_costos: dict_costos[mes_actual] = 0

        for ot in ots_db:
            if ot.fecha and ot.fecha.year == 2026 and ot.fecha.month in dict_costos:
                dict_costos[ot.fecha.month] += (ot.costo_mantencion_clp or 0.0)
        for c in compras_db:
            if c.fecha and c.fecha.year == 2026 and c.fecha.month in dict_costos:
                dict_costos[c.fecha.month] += (c.costo_pm_clp or 0.0)

        grafico_nombres = [nombres_meses.get(m, str(m)) for m in sorted(dict_costos.keys())]
        grafico_valores = [dict_costos[m] for m in sorted(dict_costos.keys())]

        kpis = {'total': len(eqs_db), 'operativos': conteo_estado.get('Operativo',0), 'fuera': conteo_estado.get('Fuera de Servicio',0), 'atrasados': len(criticos), 'ot_abiertas': len(ots_activas), 'costo_mes_str': format_clp(dict_costos.get(mes_actual, 0))}
        
        charts = {
            'estado': conteo_estado,
            'ubicaciones': {k: v for k, v in conteo_ubicacion.items() if v > 0},
            'costos_mensuales': {'labels': grafico_nombres, 'data': grafico_valores}
        }

        return render_template('index.html', kpis=kpis, charts=charts, eqs=equipos, criticos=criticos, taller=taller, mantenciones=todas_mantenciones, compras=todas_compras, lecturas=todas_lecturas, kanban=kanban_tareas, logs=logs_list, equipos_aleatorios=equipos_aleatorios, operadores=lista_operadores, current_user=session['username'])
    except Exception as e: return f"Error crítico de carga del Dashboard: {str(e)}"

@app.route('/update_kanban', methods=['POST'])
def update_kanban():
    data = request.json
    codigo = data.get('codigo'); columna_destino = data.get('estado')
    ot_activa = OrdenTrabajo.query.filter(OrdenTrabajo.codigo_equipo == codigo, OrdenTrabajo.estado.in_(['Pendiente', 'En Progreso', 'En Revisión'])).first()

    if ot_activa: 
        ot_activa.estado = columna_destino
        registrar_log(f"Movió OT {ot_activa.folio} ({codigo}) a {columna_destino}")
    else:
        ultimo_ot = OrdenTrabajo.query.order_by(OrdenTrabajo.id.desc()).first()
        siguiente = (ultimo_ot.id + 1) if ultimo_ot else 1
        folio_nuevo = f"OT-DMT-0{1820 + siguiente}"
        nueva_ot = OrdenTrabajo(fecha=datetime.now(), codigo_equipo=codigo, estado=columna_destino, folio=folio_nuevo, tipo_mantencion="Pauta 250 Hrs", tipo_ot="Preventiva")
        db.session.add(nueva_ot)
        registrar_log(f"Creó nueva OT {folio_nuevo} para {codigo} en {columna_destino}")
    db.session.commit()
    return jsonify({"status": "success"})

@app.route('/update_inline', methods=['POST'])
def update_inline():
    try:
        data = request.json
        tabla = data.get('tabla', 'equipo')
        if tabla == 'personal':
            p = Personal.query.get(data.get('codigo'))
            if p: 
                setattr(p, data.get('campo'), data.get('valor'))
                registrar_log(f"Modificó campo {data.get('campo')} de operador {p.nombre}")
        else:
            equipo = Equipo.query.filter_by(codigo=data.get('codigo')).first()
            if equipo: 
                setattr(equipo, data.get('campo'), data.get('valor'))
                registrar_log(f"Modificó campo {data.get('campo')} de equipo {equipo.codigo}")
        db.session.commit()
        return jsonify({"status": "success"})
    except: return jsonify({"status": "error"}), 500

@app.route('/equipo/<codigo>', strict_slashes=False)
def ficha_equipo(codigo):
    equipo = Equipo.query.filter_by(codigo=codigo).first_or_404()
    
    vin_texto = equipo.vin if equipo.vin and str(equipo.vin).lower() not in ["none", "nan", ""] else "S/I"
    motor_texto = equipo.n_motor if equipo.n_motor and str(equipo.n_motor).lower() not in ["none", "nan", ""] else "S/I"
    patente_texto = equipo.patente if equipo.patente and str(equipo.patente).lower() not in ["none", "nan", ""] else "S/P"
    
    desc_tecnica = f"Unidad {equipo.tipo_equipo} marca {equipo.marca} {equipo.modelo}. Identificación de chasis (VIN): {vin_texto}. Número de Motor: {motor_texto}."
    
    mants_db = OrdenTrabajo.query.filter_by(codigo_equipo=codigo).order_by(OrdenTrabajo.id.desc()).all()
    compras_db = CompraRepuesto.query.filter_by(codigo_equipo=codigo).order_by(CompraRepuesto.fecha.desc()).all()
    lecturas_db = HistorialLectura.query.filter_by(codigo_equipo=codigo).order_by(HistorialLectura.fecha.desc()).limit(5).all()

    mants = [{'fecha': m.fecha.strftime('%d/%m/%Y') if m.fecha else 'S/F', 'tipo': m.tipo_mantencion, 'costo_str': format_clp(m.costo_mantencion_clp), 'estado': m.estado, 'folio': m.folio} for m in mants_db]
    compras = [{'fecha': c.fecha.strftime('%d/%m/%Y'), 'oc': c.oc, 'descripcion': c.descripcion, 'costo_str': format_clp(c.costo_pm_clp), 'proveedor': c.proveedor} for c in compras_db]
    lecturas = [{'fecha': l.fecha.strftime('%d/%m/%Y %H:%M'), 'valor': format_num(l.horometro if l.horometro > 0 else l.kilometraje), 'tipo': 'HR' if l.horometro > 0 else 'KM', 'obs': l.observacion} for l in lecturas_db]

    return render_template('ficha_equipo.html', eq=equipo, desc_tecnica=desc_tecnica, foto_url=buscar_foto_por_tipo(equipo.tipo_equipo, equipo.marca), mants=mants, compras=compras, lecturas=lecturas)

@app.route('/imprimir_ot/<codigo>', strict_slashes=False)
def imprimir_ot(codigo):
    equipo = Equipo.query.filter_by(codigo=codigo).first_or_404()
    ot = OrdenTrabajo.query.filter_by(codigo_equipo=codigo).order_by(OrdenTrabajo.id.desc()).first()
    ot_data = {'folio': ot.folio if (ot and ot.folio and str(ot.folio).lower() != 'none') else f"OT-DMT-0{random.randint(2000, 9000)}", 'tipo_mantencion': ot.tipo_mantencion if (ot and ot.tipo_mantencion) else "MANTENIMIENTO PREVENTIVO 250 HRS"}
    return render_template('ot_print.html', equipo=equipo, ot=ot_data, fecha_actual=datetime.now().strftime("%d/%m/%Y"))

@app.route('/admin/cargar_sql_final', strict_slashes=False)
def cargar_sql_final():
    archivo_excel = "CMMS DEMOTRON MANU ORTIZ.xlsx"
    if not os.path.exists(archivo_excel): return "Error: Falta Excel principal."
    try:
        with db.engine.connect() as conn:
            conn.execute(db.text("DROP TABLE IF EXISTS compra_repuesto"))
            conn.execute(db.text("DROP TABLE IF EXISTS orden_trabajo"))
            conn.execute(db.text("DROP TABLE IF EXISTS historial_lectura"))
            conn.execute(db.text("DROP TABLE IF EXISTS equipo"))
            conn.commit()
            
        db.create_all()
        df_eq = pd.read_excel(archivo_excel, sheet_name="Equipos", skiprows=2).replace({np.nan: None})
        
        operadores_excel = df_eq.iloc[:, 6].dropna().unique()
        for op in operadores_excel:
            op_str = str(op).strip()
            if op_str and str(op_str).lower() != 'none':
                if not Personal.query.filter_by(nombre=op_str).first():
                    db.session.add(Personal(tipo="Conductor", nombre=op_str, cargo="Operador de Maquinaria", estado="Activo"))

        for _, row in df_eq.iterrows():
            if not row.iloc[0]: continue
            eq = Equipo(codigo=str(row.iloc[0]).strip(), tipo_equipo=row.iloc[1], marca=row.iloc[2], modelo=str(row.iloc[3]).strip() if row.iloc[3] else None, ano=clean_int(row.iloc[4], None), ubicacion=row.iloc[5], responsable=row.iloc[6], estado_base=str(row.iloc[7]).strip() if row.iloc[7] else 'Operativo', control_base=str(row.iloc[8]).strip().upper() if row.iloc[8] else 'HORAS', frecuencia_base=clean_int(row.iloc[9], 250))
            db.session.add(eq)
        db.session.commit()

        # === CÓDIGO CORREGIDO PARA LEER EL EXCEL DIRECTAMENTE ===
        archivo_detalles = "detalles de equipo.xlsx"
        if os.path.exists(archivo_detalles):
            df_det = pd.read_excel(archivo_detalles).replace({np.nan: None})
            df_det.columns = [str(c).strip() for c in df_det.columns]
            for _, row in df_det.iterrows():
                cod = str(row.get('Código', row.get('Codigo', ''))).strip()
                eq = Equipo.query.filter_by(codigo=cod).first()
                if eq:
                    eq.patente = clean_string(row.get('Placa', ''))
                    eq.vin = clean_string(row.get('N° Chasis', ''))
                    eq.n_motor = clean_string(row.get('N° Motor', ''))
            db.session.commit()
        # ========================================================

        df_lec = pd.read_excel(archivo_excel, sheet_name="Lecturas", skiprows=2).replace({np.nan: None})
        for _, row in df_lec.iterrows():
            if not row.iloc[1]: continue
            f_val = str(row.iloc[0]).split()[0]
            try: fecha_dt = datetime.strptime(f_val, "%Y-%m-%d")
            except: fecha_dt = datetime.now()
            db.session.add(HistorialLectura(fecha=fecha_dt, codigo_equipo=str(row.iloc[1]).strip(), horometro=clean_int(row.iloc[2], 0), kilometraje=clean_int(row.iloc[3], 0), obra_ubicacion=row.iloc[4], responsable=row.iloc[5], observacion=row.iloc[6]))

        df_man = pd.read_excel(archivo_excel, sheet_name="Mantenciones", skiprows=2).replace({np.nan: None})
        for _, row in df_man.iterrows():
            if not row.iloc[1]: continue
            f_val = str(row.iloc[0]).split()[0]
            try: fecha_dt = datetime.strptime(f_val, "%Y-%m-%d")
            except: fecha_dt = datetime.now()
            db.session.add(OrdenTrabajo(fecha=fecha_dt, codigo_equipo=str(row.iloc[1]).strip(), tipo_mantencion=str(row.iloc[2]).strip(), lectura=clean_int(row.iloc[3], 0), es_pm=row.iloc[4], folio=str(row.iloc[5]), lugar=row.iloc[6], costo_mantencion_clp=clean_float(row.iloc[8], 0.0), estado=row.iloc[9] if row.iloc[9] else 'Finalizada'))

        df_com = pd.read_excel(archivo_excel, sheet_name="Compras PM", skiprows=2).replace({np.nan: None})
        for _, row in df_com.iterrows():
            if not row.iloc[2]: continue
            f_val = str(row.iloc[0]).split()[0]
            try: fecha_dt = datetime.strptime(f_val, "%Y-%m-%d")
            except: fecha_dt = datetime.now()
            db.session.add(CompraRepuesto(fecha=fecha_dt, oc=str(row.iloc[1]), codigo_equipo=str(row.iloc[2]).strip(), descripcion=row.iloc[3], proveedor=row.iloc[4], costo_pm_clp=clean_float(row.iloc[5], 0.0), estado_oc=row.iloc[7]))
        db.session.commit()

        for eq in Equipo.query.all():
            u_lec = HistorialLectura.query.filter_by(codigo_equipo=eq.codigo).order_by(HistorialLectura.fecha.desc(), HistorialLectura.id.desc()).first()
            if u_lec: eq.lectura_actual = u_lec.horometro if eq.control_base == 'HORAS' else u_lec.kilometraje
            u_pm = OrdenTrabajo.query.filter_by(codigo_equipo=eq.codigo, es_pm='Sí', estado='Finalizada').order_by(OrdenTrabajo.fecha.desc()).first()
            if u_pm: eq.proxima_pm = u_pm.lectura + eq.frecuencia_base
            else: eq.proxima_pm = eq.lectura_actual + eq.frecuencia_base
        db.session.commit()
        registrar_log("Reestructuración y sincronización total de datos desde Excel")
        return redirect(url_for('dashboard'))
    except Exception as e: return f"<h1 style='color:red;'>Error técnico crítico en la inyección de datos:</h1><p>{str(e)}</p>"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
