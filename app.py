import os
import random
import pandas as pd
import numpy as np
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash

app = Flask(__name__)
app.secret_key = 'demotron_seguridad_maxima_2026'

# Configuración Base de Datos
ruta_db = os.getenv('DATABASE_URL', 'sqlite:///demotron_master.db')
if ruta_db.startswith("postgres://"):
    ruta_db = ruta_db.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = ruta_db
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- MODELOS ---
class Personal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100))
    cargo = db.Column(db.String(100), default="Operador")
    estado = db.Column(db.String(50), default="Activo")

class Equipo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), unique=True)
    tipo_equipo = db.Column(db.String(100))
    marca = db.Column(db.String(50))
    modelo = db.Column(db.String(100))
    ubicacion = db.Column(db.String(100))
    responsable = db.Column(db.String(100))
    estado_base = db.Column(db.String(50))
    vin = db.Column(db.String(100))
    n_motor = db.Column(db.String(100))
    patente = db.Column(db.String(50))
    pauta_filtros = db.Column(db.Text, default="Registrar filtros...")
    planificacion_mantencion = db.Column(db.Text, default="Describir pauta...")

class OrdenTrabajo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime)
    codigo_equipo = db.Column(db.String(50))
    tipo_mantencion = db.Column(db.String(100))
    costo_mantencion_clp = db.Column(db.Float, default=0.0)
    estado = db.Column(db.String(50))
    folio = db.Column(db.String(50))

with app.app_context():
    db.create_all()

# --- FUNCIONES ---
def format_clp(val):
    try: return f"$ {int(float(str(val))):,}".replace(",", ".")
    except: return "$ 0"

# --- RUTAS ---
@app.route('/', strict_slashes=False)
def dashboard():
    eqs = Equipo.query.all()
    ots = OrdenTrabajo.query.all()
    mes_actual = datetime.now().month
    
    # Calcular costos mensuales
    costos_mensuales = {2:0, 3:0, 4:0, 5:0}
    for ot in ots:
        if ot.fecha and ot.fecha.year == 2026 and ot.fecha.month in costos_mensuales:
            costos_mensuales[ot.fecha.month] += (ot.costo_mantencion_clp or 0)
    
    kpis = {
        'total': len(eqs),
        'operativos': len([e for e in eqs if e.estado_base == 'Operativo']),
        'costo_mes_str': format_clp(costos_mensuales.get(mes_actual, 0))
    }
    
    charts = {
        'costos': {'labels': ['Feb', 'Mar', 'Abr', 'May'], 'data': list(costos_mensuales.values())}
    }
    
    return render_template('index.html', kpis=kpis, charts=charts, equipos=eqs)

@app.route('/admin/cargar_sql_final', strict_slashes=False)
def cargar_sql_final():
    try:
        # Borrado seguro por tablas
        for tabla in [OrdenTrabajo, Equipo, Personal]:
            db.session.query(tabla).delete()
        db.session.commit()
        
        # Carga desde Excel (ajusta el nombre si es necesario)
        excel = "CMMS DEMOTRON MANU ORTIZ.xlsx"
        if not os.path.exists(excel): return "Error: No existe el archivo Excel."
        
        df = pd.read_excel(excel, sheet_name="Equipos", skiprows=2).replace({np.nan: None})
        for _, row in df.iterrows():
            if pd.isna(row.iloc[0]): continue
            eq = Equipo(codigo=str(row.iloc[0]).strip(), tipo_equipo=row.iloc[1], 
                        marca=row.iloc[2], ubicacion=row.iloc[5], responsable=row.iloc[6])
            db.session.add(eq)
        db.session.commit()
        
        return "Carga exitosa. <a href='/'>Volver al Dashboard</a>"
    except Exception as e:
        return f"Error: {str(e)}"

@app.route('/update_inline', methods=['POST'])
def update_inline():
    data = request.json
    if data['tabla'] == 'equipo':
        eq = Equipo.query.filter_by(codigo=data['codigo']).first()
        if eq: setattr(eq, data['campo'], data['valor'])
    db.session.commit()
    return jsonify({"status": "success"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
