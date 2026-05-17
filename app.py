import os
import json
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.secret_key = 'demotron_secure_key'

# Configuración de Base de Datos para Railway (PostgreSQL) o local (SQLite)
ruta_db = os.getenv('DATABASE_URL', 'sqlite:///demotron_cmms.db')
if ruta_db.startswith("postgres://"):
    ruta_db = ruta_db.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = ruta_db
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ==========================================
# 1. MODELOS DE BASE DE DATOS (Estructura base para Excel)
# ==========================================

class Equipo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), unique=True, nullable=False)
    marca = db.Column(db.String(50))
    modelo = db.Column(db.String(50))
    descripcion = db.Column(db.String(150))
    ubicacion = db.Column(db.String(100))
    lectura_actual = db.Column(db.Integer, default=0)
    proxima_pm = db.Column(db.Integer, default=0)
    estado = db.Column(db.String(50), default='Operativo') # Operativo, En Taller, Avería
    imagen_url = db.Column(db.String(250), nullable=True)

    @property
    def margen(self):
        return self.proxima_pm - self.lectura_actual

class Actividad(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=datetime.now)
    titulo = db.Column(db.String(100))
    detalle = db.Column(db.String(250))
    usuario = db.Column(db.String(50))

class OrdenTrabajo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    codigo_equipo = db.Column(db.String(50))
    tipo = db.Column(db.String(50))
    prioridad = db.Column(db.String(50))
    descripcion = db.Column(db.String(250))
    estado = db.Column(db.String(50), default='Abierta')

with app.app_context():
    db.create_all()

# ==========================================
# 2. RUTA PRINCIPAL - DEMOTRON DASHBOARD
# ==========================================

@app.route('/')
@app.route('/erp')
def dashboard():
    equipos_db = Equipo.query.all()
    actividad_db = Actividad.query.order_by(Actividad.id.desc()).limit(5).all()
    ot_db = OrdenTrabajo.query.filter_by(estado='Abierta').count()

    equipos = []
    taller = []
    criticos = []
    
    averias_count = 0
    proximos_count = 0
    operativos_count = 0
    en_taller_count = 0

    conteo_estado = {'Operativo': 0, 'En Taller': 0, 'Avería': 0}
    conteo_ubicacion = {}

    for e in equipos_db:
        eq_data = {
            'codigo': e.codigo,
            'marca': e.marca,
            'modelo': e.modelo,
            'descripcion': e.descripcion,
            'ubicacion': e.ubicacion or 'Sin Ubicación',
            'lectura_actual': e.lectura_actual,
            'proxima_pm': e.proxima_pm,
            'margen': e.margen,
            'estado': e.estado
        }
        equipos.append(eq_data)

        # Contadores de Estado para Gráfico Donut
        if e.estado in conteo_estado:
            conteo_estado[e.estado] += 1
        else:
            conteo_estado[e.estado] = 1

        # Contadores de Ubicación para Gráfico de Barras
        if e.ubicacion:
            conteo_ubicacion[e.ubicacion] = conteo_ubicacion.get(e.ubicacion, 0) + 1

        # Clasificación de listas para los bucles del HTML
        if e.estado == 'En Taller':
            taller.append(eq_data)
            en_taller_count += 1
        
        if e.estado == 'Avería':
            criticos.append(eq_data)
            averias_count += 1
        elif e.margen < 500:
            proximos_count += 1
            
        if e.estado == 'Operativo':
            operativos_count += 1

    total_equipos = len(equipos_db)
    
    # Sincronización exacta con las llaves {{ kpis.xxx }} de tu index.html
    kpis = {
        'atrasados': averias_count,     # Muestra las averías críticas
        'total': total_equipos,         # Cantidad total del parque
        'proximos': proximos_count,     # Alertas de PM vencidos/por vencer
        'ot_abiertas': ot_db,           # Órdenes abiertas en taller
        'controlados': operativos_count, # Equipos en marcha
        'operativos': total_equipos,    # Base del divisor
        'controlado_pct': round((operativos_count / total_equipos * 100)) if total_equipos > 0 else 0,
        'costo_mes': 4850000            # Costo de mantención
    }

    charts = {
        'estado': conteo_estado,
        'ubicacion': conteo_ubicacion,
        'gestion': {
            'Ene': [12, 5], 'Feb': [18, 8], 'Mar': [14, 11], 'Abr': [ot_db, 4]
        }
    }

    # Solución definitiva al error strftime: Valida el tipo de dato de la fecha
    actividad_formateada = []
    for a in actividad_db:
        if isinstance(a.fecha, datetime):
            fecha_str = a.fecha.strftime("%d/%m/%Y %H:%M")
        else:
            fecha_str = str(a.fecha)
        
        actividad_formateada.append({
            'titulo': a.titulo, 
            'detalle': a.detalle, 
            'usuario': a.usuario, 
            'fecha': fecha_str
        })

    return render_template('index.html', 
                           kpis=kpis, 
                           charts=json.dumps(charts), 
                           equipos=equipos, 
                           criticos=criticos, 
                           taller=taller, 
                           actividad=actividad_formateada,
                           rol="Admin")

# ==========================================
# 3. ACCIONES Y CONTROL DE UNIDADES
# ==========================================

@app.route('/equipo/<codigo>')
def ficha_equipo(codigo):
    flash(f'Cargando ficha técnica de la unidad {codigo}', 'success')
    return redirect(url_for('dashboard'))

@app.route('/admin/cargar_sql_final')
def cargar_sql_final():
    db.drop_all()
    db.create_all()

    # Inyección de maquinaría base de prueba limpia
    unidades_iniciales = [
        Equipo(codigo="VD-109", marca="SsangYong", modelo="Musso Grand", descripcion="Camioneta Supervisión", ubicacion="Talca", lectura_actual=45000, proxima_pm=50000, estado="Operativo"),
        Equipo(codigo="SC-201", marca="Scania", modelo="DC13", descripcion="Tractocamión Principal", ubicacion="Ruta 5 Sur", lectura_actual=345000, proxima_pm=346000, estado="Operativo"),
        Equipo(codigo="SC-188", marca="Scania", modelo="G380", descripcion="Camión Tolva", ubicacion="Linares", lectura_actual=612000, proxima_pm=610000, estado="En Taller"),
        Equipo(codigo="MB-405", marca="Mercedes-Benz", modelo="Actros", descripcion="Tractocamión", ubicacion="San Rafael", lectura_actual=128000, proxima_pm=125000, estado="Avería")
    ]
    db.session.add_all(unidades_iniciales)
    db.session.commit()
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    puerto = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=puerto, debug=True)
