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
# FUNCIONES DE BLINDAJE Y LIMPIEZA DE EXCEL
# ==========================================
def clean_int(val, default=0):
    if val is None or pd.isna(val):
        return default
    try:
        s = str(val).strip().split('.')[0]
        return int(s)
    except ValueError:
        return default

def clean_float(val, default=0.0):
    if val is None or pd.isna(val):
        return default
    try:
        s = str(val).strip().replace('$', '').replace('.', '').replace(',', '.')
        return float(s)
    except ValueError:
        return default

# ==========================================
# MODELOS DE BASE DE DATOS
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

    @property
    def margen(self):
        return self.proxima_pm - self.lectura_actual

    @property
    def semaforo(self):
        if self.estado_base == 'Fuera de Servicio': return 'red'
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
# VISTAS DASHBOARD
# ==========================================

@app.route('/')
@app.route('/erp')
def dashboard():
    equipos_db = Equipo.query.all()
    equipos, taller, criticos = [], [], []
    atrasados_count, proximos_count, operativos_count = 0, 0, 0
    conteo_estado = {'Operativo': 0, 'Fuera de Servicio': 0, 'En Taller': 0}
    conteo_ubicacion = {}

    for e in equipos_db:
        eq_data = {
            'codigo': e.codigo, 'tipo_equipo': e.tipo_equipo, 'marca': e.marca, 'modelo': e.modelo,
            'ubicacion': e.ubicacion or 'Sin Ubicación', 'responsable': e.responsable or 'No Asignado',
            'control_base': e.control_base, 'lectura_actual': e.lectura_actual, 'proxima_pm': e.proxima_pm,
            'margen': e.margen, 'estado_base': e.estado_base, 'semaforo': e.semaforo
        }
        equipos.append(eq_data)
        
        status = e.estado_base if e.estado_base in conteo_estado else 'Operativo'
        conteo_estado[status] += 1
        if e.ubicacion:
            conteo_ubicacion[e.ubicacion] = conteo_ubicacion.get(e.ubicacion, 0) + 1
        if e.estado_base in ['Fuera de Servicio', 'En Taller']:
            taller.append(eq_data)
        if e.semaforo == 'red':
            criticos.append(eq_data)
            atrasados_count += 1
        elif e.semaforo == 'yellow':
            proximos_count += 1
        if e.estado_base == 'Operativo':
            operativos_count += 1

    total_equipos = len(equipos_db)
    ot_abiertas = OrdenTrabajo.query.filter_by(estado='Abierta').count()
    costo_compras = db.session.query(db.func.sum(CompraRepuesto.costo_pm_clp)).scalar() or 0.0

    kpis = {
        'atrasados': atrasados_count, 'total': total_equipos, 'proximos': proximos_count,
        'ot_abiertas': ot_abiertas, 'controlados': operativos_count,
        'controlado_pct': round((operativos_count / total_equipos * 100)) if total_equipos > 0 else 0,
        'costo_mes': int(costo_compras)
    }
    charts = {
        'estado': conteo_estado, 'ubicacion': conteo_ubicacion,
        'gestion': {'Ene': [15, 8], 'Feb': [22, 14], 'Mar': [19, 25], 'Abr': [ot_abiertas, 12]}
    }
    return render_template('index.html', kpis=kpis, charts=json.dumps(charts), equipos=equipos, criticos=criticos, taller=taller)

@app.route('/equipo/<codigo>', methods=['GET', 'POST'])
def ficha_equipo(codigo):
    equipo = Equipo.query.filter_by(codigo=codigo).first_or_404()
    if request.method == 'POST':
        equipo.ubicacion = request.form.get('ubicacion')
        equipo.estado_base = request.form.get('estado_base')
        equipo.proxima_pm = clean_int(request.form.get('proxima_pm'), 0)
        db.session.commit()
        return redirect(url_for('ficha_equipo', codigo=codigo))

    mantenciones = OrdenTrabajo.query.filter_by(codigo_equipo=codigo).order_by(OrdenTrabajo.id.desc()).all()
    lecturas = HistorialLectura.query.filter_by(codigo_equipo=codigo).order_by(HistorialLectura.id.desc()).all()
    compras = CompraRepuesto.query.filter_by(codigo_equipo=codigo).order_by(CompraRepuesto.id.desc()).all()
    return render_template('ficha_equipo.html', equipo=equipo, mantenciones=mantenciones, lecturas=lecturas, compras=compras)

# ==========================================
# INYECTOR SEGURO ÍNDICE POR ÍNDICE
# ==========================================

@app.route('/admin/cargar_sql_final')
def cargar_sql_final():
    archivo_excel = "CMMS DEMOTRON MANU ORTIZ.xlsx"
    if not os.path.exists(archivo_excel):
        return f"Error: No se encuentra el archivo maestro '{archivo_excel}' en la raíz del servidor."

    try:
        # Vaciado estructural directo de alta seguridad libre de bloqueos transaccionales
        with db.engine.connect() as conn:
            conn.execute(db.text("DROP TABLE IF EXISTS compra_repuesto CASCADE;"))
            conn.execute(db.text("DROP TABLE IF EXISTS orden_trabajo CASCADE;"))
            conn.execute(db.text("DROP TABLE IF EXISTS historial_lectura CASCADE;"))
            conn.execute(db.text("DROP TABLE IF EXISTS equipo CASCADE;"))
            conn.commit()
        
        db.create_all()

        # 1. CARGA SEGURA: EQUIPOS
        df_eq = pd.read_excel(archivo_excel, sheet_name="Equipos", skiprows=2).replace({np.nan: None})
        for _, row in df_eq.iterrows():
            if not row.iloc[0]: continue
            eq = Equipo(
                codigo=str(row.iloc[0]).strip(), tipo_equipo=row.iloc[1], marca=row.iloc[2], 
                modelo=str(row.iloc[3]).strip() if row.iloc[3] else None,
                ano=clean_int(row.iloc[4], None), ubicacion=row.iloc[5], responsable=row.iloc[6],
                estado_base=row.iloc[7] if row.iloc[7] else 'Operativo',
                control_base=str(row.iloc[8]).strip().upper() if row.iloc[8] else 'HORAS',
                frecuencia_base=clean_int(row.iloc[9], 250), promedio_diario=clean_float(row.iloc[10], 0.0)
            )
            db.session.add(eq)
            db.session.commit() # Inserción individual inmediata libre de descalces posicionales

        # 2. CARGA SEGURA: LECTURAS
        df_lec = pd.read_excel(archivo_excel, sheet_name="Lecturas", skiprows=2).replace({np.nan: None})
        for _, row in df_lec.iterrows():
            if not row.iloc[1]: continue
            f_val = str(row.iloc[0]).split()[0]
            try:
                fecha_dt = datetime.strptime(f_val, "%Y-%m-%d")
            except:
                fecha_dt = datetime.now()
            
            lec = HistorialLectura(
                fecha=fecha_dt, codigo_equipo=str(row.iloc[1]).strip(),
                horometro=clean_int(row.iloc[2], 0), kilometraje=clean_int(row.iloc[3], 0),
                obra_ubicacion=row.iloc[4], responsable=row.iloc[5], observacion=row.iloc[6]
            )
            db.session.add(lec)
            db.session.commit()

        # 3. CARGA SEGURA: MANTENCIONES
        df_man = pd.read_excel(archivo_excel, sheet_name="Mantenciones", skiprows=2).replace({np.nan: None})
        for _, row in df_man.iterrows():
            if not row.iloc[1]: continue
            f_val = str(row.iloc[0]).split()[0]
            try:
                fecha_dt = datetime.strptime(f_val, "%Y-%m-%d")
            except:
                fecha_dt = datetime.now()
            
            ot = OrdenTrabajo(
                fecha=fecha_dt, codigo_equipo=str(row.iloc[1]).strip(), tipo_mantencion=row.iloc[2],
                lectura=clean_int(row.iloc[3], 0), es_pm=row.iloc[4], folio=str(row.iloc[5]),
                lugar=row.iloc[6], proveedor=row.iloc[7], costo_mantencion_clp=clean_float(row.iloc[8], 0.0),
                estado=row.iloc[9] if row.iloc[9] else 'Finalizada'
            )
            db.session.add(ot)
            db.session.commit()

        # 4. CARGA SEGURA: COMPRAS PM
        df_com = pd.read_excel(archivo_excel, sheet_name="Compras PM", skiprows=2).replace({np.nan: None})
        for _, row in df_com.iterrows():
            if not row.iloc[2]: continue
            f_val = str(row.iloc[0]).split()[0]
            try:
                fecha_dt = datetime.strptime(f_val, "%Y-%m-%d")
            except:
                fecha_dt = datetime.now()
            
            comp = CompraRepuesto(
                fecha=fecha_dt, oc=str(row.iloc[1]), codigo_equipo=str(row.iloc[2]).strip(), descripcion=row.iloc[3],
                proveedor=row.iloc[4], costo_pm_clp=clean_float(row.iloc[5], 0.0), regla=row.iloc[6], estado_oc=row.iloc[7]
            )
            db.session.add(comp)
            db.session.commit()

        # CÁLCULO DE HISTORIALES EN VIVO
        for eq in Equipo.query.all():
            ultima_lectura = HistorialLectura.query.filter_by(codigo_equipo=eq.codigo).order_by(HistorialLectura.fecha.desc(), HistorialLectura.id.desc()).first()
            if ultima_lectura:
                eq.lectura_actual = ultima_lectura.horometro if eq.control_base == 'HORAS' else ultima_lectura.kilometraje
            else:
                eq.lectura_actual = 0
            
            ultima_pm = OrdenTrabajo.query.filter_by(codigo_equipo=eq.codigo, es_pm='Sí', estado='Finalizada').order_by(OrdenTrabajo.fecha.desc()).first()
            if ultima_pm:
                eq.proxima_pm = ultima_pm.lectura + eq.frecuencia_base
            else:
                eq.proxima_pm = eq.lectura_actual + eq.frecuencia_base
                
        db.session.commit()
        flash('¡Base de Datos de DEMOTRON inicializada con éxito total!', 'success')
        return redirect(url_for('dashboard'))

    except Exception as e:
        db.session.rollback()
        return f"Error leyendo las pestañas del Excel: {str(e)}"

if __name__ == '__main__':
    puerto = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=puerto, debug=True)
