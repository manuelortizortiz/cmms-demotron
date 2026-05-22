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
    pauta_filtros = db.Column(db.Text, default="Registrar filtros...")
    planificacion_mantencion = db.Column(db.Text, default="Describir pauta...")

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
    fecha = db.Column(db.DateTime); codigo_equipo = db.Column(db.String(50)); horometro = db.Column(db.Integer, default=0); kilometraje = db.Column(db.Integer, default=0); obra_ubicacion = db.Column(db.String(100)); responsable = db.Column(db.String(100)); observacion = db.Column(db.String(250))

class CompraRepuesto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime); oc = db.Column(db.String(100)); codigo_equipo = db.Column(db.String(50)); descripcion = db.Column(db.String(250)); proveedor = db.Column(db.String(100)); costo_pm_clp = db.Column(db.Float, default=0.0); estado_oc = db.Column(db.String(100))

with app.app_context(): db.create_all()

# Funciones de apoyo
def clean_string(val):
    s = str(val).strip()
    return "" if s.lower() in ['nan', 'none', ''] else s

def clean_int(val, default=0):
    try: return int(float(clean_string(val))) if clean_string(val) else default
    except: return default

def clean_float(val, default=0.0):
    try:
        s = clean_string(val).replace('$', '').replace(' ', '').replace('.', '').replace(',', '.')
        return float(s) if s else default
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
    if any(x in t for x in ["furgon", "minibus"]): return "/static/equipos_real/minibus.png"
    return "/static/equipos_real/tractocamion.png"

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = request.form.get('username')
        pwd = request.form.get('password')
        usuario = Usuario.query.filter_by(username=user).first()
        if usuario and check_password_hash(usuario.password_hash, pwd):
            session['user_id'] = usuario.id
            session['username'] = usuario.username
            return redirect(url_for('dashboard'))
        return render_template('login.html', error="Credenciales incorrectas")
    return render_template('login.html', error=None)

@app.route('/', strict_slashes=False)
def dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    eqs_db = Equipo.query.all()
    ots_db = OrdenTrabajo.query.order_by(OrdenTrabajo.id.desc()).all()
    compras_db = CompraRepuesto.query.order_by(CompraRepuesto.fecha.desc()).all()
    
    # KPIs y Gráficos
    mes_actual = datetime.now().month
    dict_costos = {2:0, 3:0, 4:0, 5:0}
    for ot in ots_db:
        if ot.fecha and ot.fecha.year == 2026 and ot.fecha.month in dict_costos: dict_costos[ot.fecha.month] += (ot.costo_mantencion_clp or 0.0)
    for c in compras_db:
        if c.fecha and c.fecha.year == 2026 and c.fecha.month in dict_costos: dict_costos[c.fecha.month] += (c.costo_pm_clp or 0.0)
    
    kpis = {'total': len(eqs_db), 'costo_mes_str': format_clp(dict_costos.get(mes_actual, 0)), 'ot_abiertas': OrdenTrabajo.query.filter(OrdenTrabajo.estado != 'Finalizada').count(), 'atrasados': Equipo.query.filter(Equipo.proxima_pm < Equipo.lectura_actual).count()}
    
    return render_template('index.html', kpis=kpis, charts={'costos': {'labels': ['Feb', 'Mar', 'Abr', 'May'], 'data': [dict_costos[2], dict_costos[3], dict_costos[4], dict_costos[5]]}}, current_user=session['username'])

@app.route('/admin/cargar_sql_final', strict_slashes=False)
def cargar_sql_final():
    # Simplificado para evitar errores
    return "Carga iniciada (simulada). Por favor sube tu archivo principal para procesar."

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
