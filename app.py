import os
import json
import pandas as pd
import numpy as np
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.secret_key = 'demotron_master_key'

ruta_db = os.getenv('DATABASE_URL', 'sqlite:///demotron_master.db')
if ruta_db.startswith("postgres://"):
    ruta_db = ruta_db.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = ruta_db
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ==========================================
# FUNCIONES MATRICIALES DE FORMATO Y BLINDAJE
# ==========================================
def clean_int(val, default=0):
    if val is None or pd.isna(val):
        return default
    try:
        return int(str(val).strip().split('.')[0])
    except ValueError:
        return default

def clean_float(val, default=0.0):
    if val is None or pd.isna(val):
        return default
    try:
        return float(str(val).strip().replace('$', '').replace('.', '').replace(',', '.'))
    except ValueError:
        return default

def format_num(val):
    if val is None or pd.isna(val):
        return "0"
    try:
        num = int(float(str(val).strip()))
        return f"{num:,}".replace(",", ".")
    except:
        return "0"

def format_clp(val):
    if val is None or pd.isna(val):
        return "$ 0"
    try:
        num = int(float(str(val).strip()))
        return f"$ {num:,}".replace(",", ".")
    except:
        return "$ 0"

def buscar_foto_global(codigo):
    if not codigo:
        return None
    base_dir = os.path.join(app.root_path, 'static', 'equipos_real')
    if not os.path.exists(base_dir):
        base_dir = "static/equipos_real"
        if not os.path.exists(base_dir):
            return None
            
    codigo_limpio = str(codigo).strip().lower()
    for root, dirs, files in os.walk(base_dir):
        for f in files:
            nombre, ext = os.path.splitext(f)
            if nombre.lower().strip() == codigo_limpio and ext.lower() in ['.jpg', '.jpeg', '.png']:
                abs_path = os.path.join(root, f).replace("\\", "/")
                idx = abs_path.find('static/')
                if idx != -1:
                    return "/" + abs_path[idx:]
                return "/static/equipos_real/" + f
    return None

# ==========================================
# MODELOS DE BASE DE DATOS PROTEGIDOS
# ==========================================

class Equipo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), unique=True, nullable=False)
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

    # BLINDAJE ABSOLUTO: Evita quiebres por valores nulos en el cálculo
    @property
    def margen(self):
        prox = self.proxima_pm if self.proxima_pm is not None else 0
        lect = self.lectura_actual if self.lectura_actual is not None else 0
        return prox - lect

    @property
    def semaforo(self):
        if self.estado_base in ['Fuera de Servicio', 'No operativo']: return 'red'
        if self.margen < 0: return 'red'
        if self.margen < 50: return 'yellow'
        return 'green'

class HistorialLectura(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime)
    codigo_equipo = db.Column(db.String(50))
    horometro = db.Column(db.Integer, default=0)
    kilometraje = db.Column(db.Integer, default=0)
    obra_ubicacion = db.Column(db.String(100))
    responsable = db.Column(db.String(100))
    observacion = db.Column(db.String(250))

class OrdenTrabajo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime)
    codigo_equipo = db.Column(db.String(50))
    tipo_mantencion = db.Column(db.String(100))
    lectura = db.Column(db.Integer, default=0)
    es_pm = db.Column(db.String(20)) 
    folio = db.Column(db.String(50))
    lugar = db.Column(db.String(100))
    proveedor = db.Column(db.String(100))
    costo_mantencion_clp = db.Column(db.Float, default=0.0)
    estado = db.Column(db.String(50)) 

class CompraRepuesto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime)
    oc = db.Column(db.String(100))
    codigo_equipo = db.Column(db.String(50))
    descripcion = db.Column(db.String(250))
    proveedor = db.Column(db.String(100))
    costo_pm_clp = db.Column(db.Float, default=0.0)
    regla = db.Column(db.String(100))
    estado_oc = db.Column(db.String(100))

with app.app_context():
    db.create_all()

# ==========================================
# RUTA CORE: INTERFAZ DE GESTIÓN CENTRAL
# ==========================================

@app.route('/')
@app.route('/erp')
def dashboard():
    equipos_db = Equipo.query.all()
    mantenciones_db = OrdenTrabajo.query.order_by(OrdenTrabajo.fecha.desc()).all()
    compras_db = CompraRepuesto.query.order_by(CompraRepuesto.fecha.desc()).all()
    lecturas_db = HistorialLectura.query.order_by(HistorialLectura.fecha.desc()).all()

    equipos, taller, criticos = [], [], []
    proximos_count, operativos_count = 0, 0
    conteo_estado = {'Operativo': 0, 'Fuera de Servicio': 0, 'Taller': 0}
    conteo_ubicacion = {}

    for e in equipos_db:
        foto_url = buscar_foto_global(e.codigo)
        eq_data = {
            'codigo': e.codigo, 'tipo_equipo': e.tipo_equipo, 'marca': e.marca, 'modelo': e.modelo,
            'ubicacion': e.ubicacion or 'Sin Ubicación', 'responsable': e.responsable or 'No Asignado',
            'control_base': e.control_base, 'lectura_actual': e.lectura_actual, 
            'lectura_actual_str': format_num(e.lectura_actual),
            'proxima_pm': e.proxima_pm, 'proxima_pm_str': format_num(e.proxima_pm),
            'margen': e.margen, 'margen_str': format_num(e.margen),
            'estado_base': e.estado_base, 'semaforo': e.semaforo, 'foto_url': foto_url
        }
        equipos.append(eq_data)
        
        status_limpio = 'Fuera de Servicio' if e.estado_base in ['Fuera de Servicio', 'No operativo'] else e.estado_base
        conteo_estado[status_limpio] = conteo_estado.get(status_limpio, 0) + 1
        
        if e.ubicacion:
            conteo_ubicacion[e.ubicacion] = conteo_ubicacion.get(e.ubicacion, 0) + 1
            
        # CD-103 vendido (Fuera de Servicio) queda automáticamente fuera de taller
        if e.estado_base == 'Taller' and e.estado_base not in ['Fuera de Servicio', 'No operativo']:
            taller.append(eq_data)
            
        if e.semaforo == 'red' or e.estado_base in ['Fuera de Servicio', 'No operativo']:
            criticos.append(eq_data)
        elif e.semaforo == 'yellow':
            proximos_count += 1
            
        if e.estado_base == 'Operativo':
            operativos_count += 1

    conteo_ubicacion_filtrado = {k: v for k, v in conteo_ubicacion.items() if v > 5}
    ot_abiertas = OrdenTrabajo.query.filter_by(estado='Abierta').count()
    costo_compras = db.session.query(db.func.sum(CompraRepuesto.costo_pm_clp)).scalar() or 0.0
    total_equipos = len(equipos_db)

    kpis = {
        'atrasados': len(criticos), 'total': total_equipos, 'proximos': proximos_count,
        'ot_abiertas': ot_abiertas, 'controlados': operativos_count, 'operativos': total_equipos,
        'controlado_pct': round((operativos_count / total_equipos * 100)) if total_equipos > 0 else 0,
        'costo_mes': int(costo_compras), 'costo_mes_str': format_clp(costo_compras)
    }
    
    charts = {
        'estado': conteo_estado, 'ubicacion': conteo_ubicacion_filtrado,
        'gestion': {'Ene': [25, 18], 'Feb': [32, 24], 'Mar': [41, 38], 'Abr': [ot_abiertas, 15]}
    }

    # Desglose formateado seguro contra celdas vacías de Excel
    todas_mantenciones = [{
        'fecha': m.fecha.strftime('%d/%m/%Y') if m.fecha else 'S/F', 'codigo': m.codigo_equipo,
        'tipo': m.tipo_mantencion, 'lectura_str': format_num(m.lectura), 'es_pm': m.es_pm, 'folio': m.folio,
        'lugar': m.lugar, 'proveedor': m.proveedor, 'costo_str': format_clp(m.costo_mantencion_clp), 'estado': m.estado
    } for m in mantenciones_db]

    todas_compras = [{
        'fecha': c.fecha.strftime('%d/%m/%Y') if c.fecha else 'S/F', 'oc': c.oc, 'codigo': c.codigo_equipo,
        'descripcion': c.descripcion, 'proveedor': c.proveedor, 'costo_str': format_clp(c.costo_pm_clp), 
        'estado': c.estado_oc if c.estado_oc else 'Aprobada'
    } for c in compras_db]

    todas_lecturas = [{
        'fecha': l.fecha.strftime('%d/%m/%Y %H:%M') if l.fecha else 'S/F', 'codigo': l.codigo_equipo,
        'valor_str': format_num(l.horometro if l.horometro > 0 else l.kilometraje),
        'tipo': 'HORAS' if l.horometro > 0 else 'KM', 'ubicacion': l.obra_ubicacion, 'responsable': l.responsable, 'obs': l.observacion
    } for l in lecturas_db]

    return render_template('index.html', kpis=kpis, charts=json.dumps(charts), equipos=equipos, 
                           criticos=criticos, taller=taller, mantenciones=todas_mantenciones, 
                           compras=todas_compras, lecturas=todas_lecturas, rol="Admin")

# ==========================================
# RUTA DE LA FICHA TÉCNICA
# ==========================================

@app.route('/equipo/<codigo>', methods=['GET', 'POST'])
def ficha_equipo(codigo):
    equipo = Equipo.query.filter_by(codigo=codigo).first_or_404()
    if request.method == 'POST':
        equipo.ubicacion = request.form.get('ubicacion')
        equipo.estado_base = request.form.get('estado_base')
        equipo.proxima_pm = clean_int(request.form.get('proxima_pm'), 0)
        db.session.commit()
        return redirect(url_for('ficha_equipo', codigo=codigo))

    mantenciones_db = OrdenTrabajo.query.filter_by(codigo_equipo=codigo).order_by(OrdenTrabajo.id.desc()).all()
    lecturas_db = HistorialLectura.query.filter_by(codigo_equipo=codigo).order_by(HistorialLectura.id.desc()).all()
    compras_db = CompraRepuesto.query.filter_by(codigo_equipo=codigo).order_by(CompraRepuesto.id.desc()).all()

    mantenciones = [{
        'fecha': m.fecha.strftime('%d/%m/%Y') if m.fecha else 'S/F', 'folio': m.folio or 'S/F',
        'tipo_mantencion': m.tipo_mantencion, 'lectura_str': format_num(m.lectura), 'lugar': m.lugar, 
        'costo_str': format_clp(m.costo_mantencion_clp), 'estado': m.estado
    } for m in mantenciones_db]

    lecturas = [{
        'fecha': l.fecha.strftime('%d/%m/%Y %H:%M') if l.fecha else 'S/F',
        'valor_str': format_num(l.horometro if equipo.control_base == 'HORAS' else l.kilometraje),
        'obra_ubicacion': l.obra_ubicacion, 'responsable': l.responsable
    } for l in lecturas_db]

    compras = [{
        'fecha': c.fecha.strftime('%d/%m/%Y') if c.fecha else 'S/F', 'oc': c.oc,
        'descripcion': c.descripcion, 'proveedor': c.proveedor, 'costo_str': format_clp(c.costo_pm_clp)
    } for c in compras_db]

    foto_url = buscar_foto_global(equipo.codigo)

    eq_master = {
        'codigo': equipo.codigo, 'tipo_equipo': equipo.tipo_equipo, 'marca': equipo.marca, 'modelo': equipo.modelo,
        'ubicacion': equipo.ubicacion, 'proxima_pm': equipo.proxima_pm, 'estado_base': equipo.estado_base,
        'control_base': equipo.control_base, 'lectura_actual_str': format_num(equipo.lectura_actual),
        'margen_str': format_num(equipo.margen), 'margen': equipo.margen
    }

    return render_template('ficha_equipo.html', equipo=eq_master, mantenciones=mantenciones, lecturas=lecturas, compras=compras, foto_url=foto_url)

# ==========================================
# INYECTOR COMPLETO SEGURO DESDE EL EXCEL
# ==========================================

@app.route('/admin/cargar_sql_final')
def cargar_sql_final():
    archivo_excel = "CMMS DEMOTRON MANU ORTIZ.xlsx"
    if not os.path.exists(archivo_excel):
        return f"Error: No se encuentra el archivo maestro '{archivo_excel}' en la raíz."
    try:
        with db.engine.connect() as conn:
            conn.execute(db.text("DROP TABLE IF EXISTS compra_repuesto CASCADE;"))
            conn.execute(db.text("DROP TABLE IF EXISTS orden_trabajo CASCADE;"))
            conn.execute(db.text("DROP TABLE IF EXISTS historial_lectura CASCADE;"))
            conn.execute(db.text("DROP TABLE IF EXISTS equipo CASCADE;"))
            conn.commit()
        db.create_all()

        # 1. EQUIPOS
        df_eq = pd.read_excel(archivo_excel, sheet_name="Equipos", skiprows=2).replace({np.nan: None})
        for _, row in df_eq.iterrows():
            if not row.iloc[0]: continue
            eq = Equipo(
                codigo=str(row.iloc[0]).strip(), tipo_equipo=row.iloc[1], marca=row.iloc[2], modelo=str(row.iloc[3]).strip() if row.iloc[3] else None,
                ano=clean_int(row.iloc[4], None), ubicacion=row.iloc[5], responsable=row.iloc[6], estado_base=str(row.iloc[7]).strip() if row.iloc[7] else 'Operativo',
                control_base=str(row.iloc[8]).strip().upper() if row.iloc[8] else 'HORAS', frecuencia_base=clean_int(row.iloc[9], 250), promedio_diario=clean_float(row.iloc[10], 0.0)
            )
            db.session.add(eq)
            db.session.commit()

        # 2. LECTURAS
        df_lec = pd.read_excel(archivo_excel, sheet_name="Lecturas", skiprows=2).replace({np.nan: None})
        for _, row in df_lec.iterrows():
            if not row.iloc[1]: continue
            f_val = str(row.iloc[0]).split()[0]
            try: fecha_dt = datetime.strptime(f_val, "%Y-%m-%d")
            except: fecha_dt = datetime.now()
            lec = HistorialLectura(
                fecha=fecha_dt, codigo_equipo=str(row.iloc[1]).strip(), horometro=clean_int(row.iloc[2], 0), kilometraje=clean_int(row.iloc[3], 0),
                obra_ubicacion=row.iloc[4], responsable=row.iloc[5], observacion=row.iloc[6]
            )
            db.session.add(lec)
            db.session.commit()

        # 3. MANTENCIONES
        df_man = pd.read_excel(archivo_excel, sheet_name="Mantenciones", skiprows=2).replace({np.nan: None})
        for _, row in df_man.iterrows():
            if not row.iloc[1]: continue
            f_val = str(row.iloc[0]).split()[0]
            try: fecha_dt = datetime.strptime(f_val, "%Y-%m-%d")
            except: fecha_dt = datetime.now()
            ot = OrdenTrabajo(
                fecha=fecha_dt, codigo_equipo=str(row.iloc[1]).strip(), tipo_mantencion=row.iloc[2], lectura=clean_int(row.iloc[3], 0),
                es_pm=row.iloc[4], folio=str(row.iloc[5]), lugar=row.iloc[6], proveedor=row.iloc[7], costo_mantencion_clp=clean_float(row.iloc[8], 0.0), estado=row.iloc[9] if row.iloc[9] else 'Finalizada'
            )
            db.session.add(ot)
            db.session.commit()

        # 4. COMPRAS PM
        df_com = pd.read_excel(archivo_excel, sheet_name="Compras PM", skiprows=2).replace({np.nan: None})
        for _, row in df_com.iterrows():
            if not row.iloc[2]: continue
            f_val = str(row.iloc[0]).split()[0]
            try: fecha_dt = datetime.strptime(f_val, "%Y-%m-%d")
            except: fecha_dt = datetime.now()
            comp = CompraRepuesto(
                fecha=fecha_dt, oc=str(row.iloc[1]), codigo_equipo=str(row.iloc[2]).strip(), descripcion=row.iloc[3],
                proveedor=row.iloc[4], costo_pm_clp=clean_float(row.iloc[5], 0.0), regla=row.iloc[6], estado_oc=row.iloc[7]
            )
            db.session.add(comp)
            db.session.commit()

        # CONSOLIDACIÓN TÉCNICA PROTEGIDA
        for eq in Equipo.query.all():
            ultima_lectura = HistorialLectura.query.filter_by(codigo_equipo=eq.codigo).order_by(HistorialLectura.fecha.desc(), HistorialLectura.id.desc()).first()
            if ultima_lectura: eq.lectura_actual = ultima_lectura.horometro if eq.control_base == 'HORAS' else ultima_lectura.kilometraje
            else: eq.lectura_actual = 0
            
            ultima_pm = OrdenTrabajo.query.filter_by(codigo_equipo=eq.codigo, es_pm='Sí', estado='Finalizada').order_by(OrdenTrabajo.fecha.desc()).first()
            if ultima_pm: eq.proxima_pm = ultima_pm.lectura + eq.frecuencia_base
            else: eq.proxima_pm = eq.lectura_actual + eq.frecuencia_base
        db.session.commit()
        return redirect(url_for('dashboard'))
    except Exception as e:
        db.session.rollback()
        return f"Error leyendo las pestañas del Excel: {str(e)}"

if __name__ == '__main__':
    puerto = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=puerto, debug=True)
