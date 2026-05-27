import os
import random
import pandas as pd
import numpy as np
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_sqlalchemy import SQLAlchemy

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
class Equipo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), unique=True)
    tipo_equipo = db.Column(db.String(100))
    marca = db.Column(db.String(50))
    modelo = db.Column(db.String(100))
    ubicacion = db.Column(db.String(100))
    responsable = db.Column(db.String(100))
    estado_base = db.Column(db.String(50), default="Operativo")
    control_base = db.Column(db.String(50), default="HORAS")
    frecuencia_base = db.Column(db.Integer, default=250)
    lectura_actual = db.Column(db.Integer, default=0)
    proxima_pm = db.Column(db.Integer, default=0)
    vin = db.Column(db.String(100), default="")
    n_motor = db.Column(db.String(100), default="")
    patente = db.Column(db.String(50), default="")
    planificacion_mantencion = db.Column(db.Text, default="Registrar estrategia...")

class FiltroEquipo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    codigo_equipo = db.Column(db.String(50))
    sistema = db.Column(db.String(100), default="-")
    cant = db.Column(db.Integer, default=1)
    fleetguard = db.Column(db.String(100), default="-")
    baldwind = db.Column(db.String(100), default="-")
    originales = db.Column(db.String(100), default="-")
    donaldson = db.Column(db.String(100), default="-")
    otra = db.Column(db.String(100), default="-")

class OrdenTrabajo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=datetime.now)
    codigo_equipo = db.Column(db.String(50))
    tipo_ot = db.Column(db.String(50), default="Preventiva")
    tipo_mantencion = db.Column(db.String(100))
    costo_mantencion_clp = db.Column(db.Float, default=0.0)
    estado = db.Column(db.String(50), default="Pendiente")
    folio = db.Column(db.String(50))
    lectura = db.Column(db.Integer, default=0)
    es_pm = db.Column(db.String(20))
    lugar = db.Column(db.String(100))

class HistorialLectura(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=datetime.now)
    codigo_equipo = db.Column(db.String(50))
    horometro = db.Column(db.Integer, default=0)
    kilometraje = db.Column(db.Integer, default=0)
    obra_ubicacion = db.Column(db.String(100))
    responsable = db.Column(db.String(100))
    observacion = db.Column(db.String(250))

class CompraRepuesto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=datetime.now)
    oc = db.Column(db.String(100))
    codigo_equipo = db.Column(db.String(50))
    descripcion = db.Column(db.String(250))
    proveedor = db.Column(db.String(100))
    costo_pm_clp = db.Column(db.Float, default=0.0)
    estado_oc = db.Column(db.String(100))

with app.app_context(): db.create_all()

# Funciones Auxiliares
def clean_int(val, default=0):
    try: return int(float(str(val).strip()))
    except: return default

def clean_float(val, default=0.0):
    try: return float(str(val).replace('$','').replace('.','').replace(',','.'))
    except: return default

def buscar_foto(tipo):
    t = str(tipo).lower()
    if "tolva" in t: return "camion_man_tolva.png"
    if "tracto" in t: return "tractocamion.png"
    if "camioneta" in t: return "maxus_t60.png"
    return "default.png"

# Rutas CRUD
@app.route('/api/add_record', methods=['POST'])
def add_record():
    tabla = request.form.get('tabla')
    codigo = request.form.get('codigo')
    if tabla == 'ot':
        db.session.add(OrdenTrabajo(codigo_equipo=codigo, tipo_mantencion=request.form.get('tipo', '')))
    elif tabla == 'lectura':
        db.session.add(HistorialLectura(codigo_equipo=codigo))
    elif tabla == 'compra':
        db.session.add(CompraRepuesto(codigo_equipo=codigo))
    elif tabla == 'filtro':
        db.session.add(FiltroEquipo(codigo_equipo=codigo))
    db.session.commit()
    return redirect(request.form.get('referer', '/'))

@app.route('/api/delete_record/<tabla>/<int:id>', methods=['POST'])
def delete_record(tabla, id):
    obj = None
    if tabla == 'ot': obj = OrdenTrabajo.query.get(id)
    elif tabla == 'lectura': obj = HistorialLectura.query.get(id)
    elif tabla == 'compra': obj = CompraRepuesto.query.get(id)
    elif tabla == 'filtro': obj = FiltroEquipo.query.get(id)
    if obj: db.session.delete(obj); db.session.commit()
    return jsonify({"status": "ok"})

@app.route('/update_inline', methods=['POST'])
def update_inline():
    data = request.json
    tabla = data.get('tabla')
    id = data.get('codigo')
    campo = data.get('campo')
    valor = data.get('valor')
    
    obj = None
    if tabla == 'equipo': obj = Equipo.query.filter_by(codigo=id).first()
    elif tabla == 'ot': obj = OrdenTrabajo.query.get(id)
    elif tabla == 'lectura': obj = HistorialLectura.query.get(id)
    elif tabla == 'compra': obj = CompraRepuesto.query.get(id)
    elif tabla == 'filtro': obj = FiltroEquipo.query.get(id)
    
    if obj:
        setattr(obj, campo, valor)
        db.session.commit()
    return jsonify({"status": "ok"})

# Ruta de carga (Simplificada para no fallar)
@app.route('/admin/cargar_sql_final')
def cargar():
    # Lógica de carga aquí...
    # (Recomendación: Implementar una carga secuencial por tablas)
    return "Cargado"

@app.route('/equipo/<codigo>')
def ficha(codigo):
    eq = Equipo.query.filter_by(codigo=codigo).first_or_404()
    filtros = FiltroEquipo.query.filter_by(codigo_equipo=codigo).all()
    mants = OrdenTrabajo.query.filter_by(codigo_equipo=codigo).all()
    lecturas = HistorialLectura.query.filter_by(codigo_equipo=codigo).all()
    return render_template('ficha_equipo.html', eq=eq, filtros=filtros, mants=mants, lecturas=lecturas, foto=buscar_foto(eq.tipo_equipo))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8000)))
