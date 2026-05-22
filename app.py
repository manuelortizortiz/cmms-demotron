import os
import random
import pandas as pd
import numpy as np
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash

app = Flask(__name__)
app.secret_key = 'demotron_seguridad_maxima_2026'

# Configuración de base de datos para Render (Postgres) o Local (SQLite)
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

class OrdenTrabajo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime)
    codigo_equipo = db.Column(db.String(50))
    tipo_mantencion = db.Column(db.String(100))
    costo_mantencion_clp = db.Column(db.Float, default=0.0)
    estado = db.Column(db.String(50))

# Inicialización
with app.app_context():
    db.create_all()

# Funciones de limpieza
def clean_string(val):
    s = str(val).strip()
    return "" if s.lower() in ['nan', 'none', ''] else s

# ==========================================
# RUTAS
# ==========================================
@app.route('/')
def dashboard():
    return "Sistema de Gestión DEMOTRON Activo. Panel principal en desarrollo."

@app.route('/admin/cargar_sql_final', strict_slashes=False)
def cargar_sql_final():
    try:
        # Buscar archivos automáticamente en la raíz
        archivos = os.listdir('.')
        excel_principal = next((f for f in archivos if "CMMS" in f), None)
        archivo_detalles = next((f for f in archivos if "detalles" in f.lower()), None)

        if not excel_principal:
            return "Error: No se encontró el archivo CMMS principal."

        # Cargar Equipos del Excel
        df_eq = pd.read_excel(excel_principal, sheet_name="Equipos", skiprows=2)
        for _, row in df_eq.iterrows():
            if pd.isna(row.iloc[0]): continue
            cod = str(row.iloc[0]).strip()
            eq = Equipo.query.filter_by(codigo=cod).first()
            if not eq:
                eq = Equipo(codigo=cod, tipo_equipo=row.iloc[1], marca=row.iloc[2], 
                            modelo=str(row.iloc[3]), ubicacion=row.iloc[5])
                db.session.add(eq)
        db.session.commit()

        # Cargar Detalles (Patentes/VIN) desde el archivo de detalles
        if archivo_detalles:
            df_det = pd.read_csv(archivo_detalles) if archivo_detalles.endswith('.csv') else pd.read_excel(archivo_detalles)
            for _, row in df_det.iterrows():
                cod = str(row.get('Código', row.get('Codigo', ''))).strip()
                eq = Equipo.query.filter_by(codigo=cod).first()
                if eq:
                    eq.patente = clean_string(row.get('Placa', ''))
                    eq.vin = clean_string(row.get('N° Chasis', ''))
                    eq.n_motor = clean_string(row.get('N° Motor', ''))
            db.session.commit()

        return "<h1>Carga exitosa</h1><p>Equipos y detalles técnicos procesados correctamente.</p>"
    except Exception as e:
        return f"<h1>Error en la carga:</h1><pre>{str(e)}</pre>"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
