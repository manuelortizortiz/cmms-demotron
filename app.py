import os
import json
import random
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
# PROCESADORES NUMÉRICOS INDUSTRIALES
# ==========================================
def clean_int(val, default=0):
    if val is None or pd.isna(val): return default
    if isinstance(val, (int, float, np.number)): return int(val)
    try: return int(str(val).strip().split('.')[0])
    except: return default

def clean_float(val, default=0.0):
    if val is None or pd.isna(val): return default
    if isinstance(val, (int, float, np.number)): return float(val)
    try:
        s = str(val).strip().replace('$', '').replace(' ', '')
        if s.count('.') == 1 and ',' not in s: return float(s)
        if '.' in s and ',' in s: s = s.replace('.', '').replace(',', '.')
        elif ',' in s: s = s.replace(',', '.')
        return float(s)
    except: return default

def format_num(val):
    if val is None or pd.isna(val): return "0"
    try: return f"{int(float(str(val).strip())):,}".replace(",", ".")
    except: return "0"

def format_clp(val):
    if val is None or pd.isna(val): return "$ 0"
    try: return f"$ {int(float(str(val).strip())):,}".replace(",", ".")
    except: return "$ 0"

# ==========================================
# MAPEO HOMOGÉNEO DE IMÁGENES POR TIPO
# ==========================================
def buscar_foto_por_tipo(tipo_equipo):
    if not tipo_equipo: return None
    base_dir = os.path.join(app.root_path, 'static', 'equipos_real')
    if not os.path.exists(base_dir): base_dir = "static/equipos_real"
            
    tipo_limpio = str(tipo_equipo).strip().lower()
    
    if "tracto" in tipo_limpio or "tractocamion" in tipo_limpio: target = "tracto"
    elif "camioneta" in tipo_limpio: target = "camioneta"
    elif "tolva" in tipo_limpio: target = "tolva"
    elif "aljibe" in tipo_limpio or "alguije" in tipo_limpio: target = "aljibe"
    elif "excavadora" in tipo_limpio: target = "excavadora"
    elif "barredora" in tipo_limpio: target = "barredora"
    else:
        remplazos = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ñ": "n", " ": "_", "-": "_"}
        target = "".join(remplazos.get(c, c) for c in tipo_limpio)

    if os.path.exists(base_dir):
        for root, dirs, files in os.walk(base_dir):
            for f in files:
                nombre, ext = os.path.splitext(f)
                nombre_limpio = nombre.lower().strip().replace(" ", "_").replace("-", "_")
                remplazos_v = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ñ": "n"}
                for k, v in remplazos_v.items(): nombre_limpio = nombre_limpio.replace(k, v)
                if ext.lower() in ['.jpg', '.jpeg', '.png']:
                    if target in nombre_limpio or nombre_limpio in target:
                        abs_path = os.path.join(root, f).replace("\\", "/")
                        idx = abs_path.find('static/')
                        if idx != -1: return "/" + abs_path[idx:]
    return None

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
# DESPLIEGUE CENTRALIZADO DEL ERP
# ==========================================

@app.route('/')
@app.route('/erp')
def dashboard():
    equipos_db = Equipo.query.all()
    mantenciones_db = OrdenTrabajo.query.order_by(OrdenTrabajo.fecha.desc()).all()
    compras_db = CompraRepuesto.query.order_by(CompraRepuesto.fecha.desc()).all()
    lecturas_db = HistorialLectura.query.order_by(HistorialLectura.fecha.desc()).all()

    equipos, taller, criticos = [], [], []
    conteo_estado = {'Operativo': 0, 'Fuera de Servicio': 0, 'Taller': 0}
    conteo_ubicacion = {}

    compras_mensuales = {"Feb": 0.0, "Mar": 0.0, "Abr": 0.0, "May": 0.0}
    for c in compras_db:
        if c.fecha and c.fecha.year == 2026:
            if c.fecha.month == 2: compras_mensuales["Feb"] += c.costo_pm_clp
            elif c.fecha.month == 3: compras_mensuales["Mar"] += c.costo_pm_clp
            elif c.fecha.month == 4: compras_mensuales["Abr"] += c.costo_pm_clp
            elif c.fecha.month == 5: compras_mensuales["May"] += c.costo_pm_clp

    for e in equipos_db:
        foto_url = buscar_foto_por_tipo(e.tipo_equipo)
        eq_data = {
            'codigo': e.codigo, 'tipo_equipo': e.tipo_equipo, 'marca': e.marca, 'modelo': e.modelo,
            'ubicacion': e.ubicacion or 'Sin Ubicación', 'responsable': e.responsable or 'No Asignado',
            'control_base': e.control_base, 'lectura_actual_str': format_num(e.lectura_actual),
            'proxima_pm_str': format_num(e.proxima_pm), 'margen_str': format_num(e.margen),
            'estado_base': e.estado_base, 'semaforo': e.semaforo, 'foto_url': foto_url
        }
        equipos.append(eq_data)
        
        status_limpio = 'Fuera de Servicio' if e.estado_base in ['Fuera de Servicio', 'No operativo'] else e.estado_base
        conteo_estado[status_limpio] = conteo_estado.get(status_limpio, 0) + 1
        if e.ubicacion: conteo_ubicacion[e.ubicacion] = conteo_ubicacion.get(e.ubicacion, 0) + 1
        if e.estado_base == 'Taller' and e.estado_base not in ['Fuera de Servicio', 'No operativo']: taller.append(eq_data)
        if e.semaforo == 'red' or e.estado_base in ['Fuera de Servicio', 'No operativo']: criticos.append(eq_data)

    conteo_ubicacion_filtrado = {k: v for k, v in conteo_ubicacion.items() if v == 5}
    ot_abiertas = OrdenTrabajo.query.filter_by(estado='Abierta').count()
    costo_compras = db.session.query(db.func.sum(CompraRepuesto.costo_pm_clp)).scalar() or 0.0

    kpis = {
        'atrasados': len(criticos), 'total': len(equipos_db), 'proximos': len(criticos),
        'ot_abiertas': ot_abiertas, 'controlados': len(equipos_db) - len(criticos),
        'controlado_pct': round(((len(equipos_db) - len(criticos)) / len(equipos_db) * 100)) if len(equipos_db) > 0 else 0,
        'costo_mes_str': format_clp(costo_compras)
    }
    
    charts = { 'estado': conteo_estado, 'ubicacion': conteo_ubicacion_filtrado, 'compras_mensuales': compras_mensuales }

    todas_mantenciones = [{
        'fecha': m.fecha.strftime('%d/%m/%Y') if m.fecha else 'S/F', 'codigo': m.codigo_equipo,
        'tipo': m.tipo_mantencion, 'lectura_str': format_num(m.lectura), 'es_pm': m.es_pm, 'folio': m.folio,
        'lugar': m.lugar, 'costo_str': format_clp(m.costo_mantencion_clp), 'estado': m.estado
    } for m in mantenciones_db]

    todas_compras = [{
        'fecha': c.fecha.strftime('%d/%m/%Y') if c.fecha else 'S/F', 'oc': c.oc, 'codigo': c.codigo_equipo,
        'descripcion': c.descripcion, 'proveedor': c.proveedor, 'costo_str': format_clp(c.costo_pm_clp), 'estado': c.estado_oc or 'Aprobada'
    } for c in compras_db]

    todas_lecturas = [{
        'fecha': l.fecha.strftime('%d/%m/%Y %H:%M') if l.fecha else 'S/F', 'codigo': l.codigo_equipo,
        'valor_str': format_num(l.horometro if l.horometro > 0 else l.kilometraje),
        'tipo': 'HORAS' if l.horometro > 0 else 'KM', 'ubicacion': l.obra_ubicacion, 'responsable': l.responsable, 'obs': l.observacion
    } for l in lecturas_db]

    equipos_aleatorios = list(equipos)
    random.shuffle(equipos_aleatorios)

    return render_template('index.html', kpis=kpis, charts=json.dumps(charts), equipos=equipos, 
                           criticos=criticos, taller=taller, mantenciones=todas_mantenciones, 
                           compras=todas_compras, lecturas=todas_lecturas, equipos_aleatorios=equipos_aleatorios, rol="Admin")

if __name__ == '__main__':
    puerto = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=puerto, debug=True)
