import os
import json
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.secret_key = 'clave_secreta_para_sesiones'

# Configuración de Base de Datos para Railway (PostgreSQL) o local (SQLite)
ruta_db = os.getenv('DATABASE_URL', 'sqlite:///mantyre.db')
if ruta_db.startswith("postgres://"):
    ruta_db = ruta_db.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = ruta_db
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ==========================================
# 1. MODELOS DE BASE DE DATOS
# ==========================================

class Equipo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), unique=True, nullable=False) # Ej: AB-CD-12
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

    @property
    def semaforo(self):
        if self.estado == 'Avería': return 'red'
        if self.estado == 'En Taller': return 'yellow'
        if self.margen < 500: return 'yellow'
        if self.margen < 0: return 'red'
        return 'green'

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

# Crea las tablas si no existen
with app.app_context():
    db.create_all()

# ==========================================
# 2. RUTAS DEL DASHBOARD
# ==========================================

@app.route('/')
@app.route('/erp')
def dashboard():
    equipos_db = Equipo.query.all()
    actividad_db = Actividad.query.order_by(Actividad.fecha.desc()).limit(5).all()
    ot_db = OrdenTrabajo.query.filter_by(estado='Abierta').count()

    # Variables para el Front-End
    equipos = []
    taller = []
    criticos = []
    
    # Contadores para KPIs
    atrasados_count = 0
    proximos_count = 0
    operativos_count = 0

    # Contadores para Gráficos
    conteo_estado = {'Operativo': 0, 'En Taller': 0, 'Avería': 0}
    conteo_ubicacion = {}

    for e in equipos_db:
        # Preparar diccionario del equipo
        eq_data = {
            'codigo': e.codigo,
            'marca': e.marca,
            'modelo': e.modelo,
            'descripcion': e.descripcion,
            'ubicacion': e.ubicacion,
            'lectura_actual': e.lectura_actual,
            'proxima_pm': e.proxima_pm,
            'margen': e.margen,
            'estado_calculado': e.estado,
            'semaforo': e.semaforo,
            'imagen_url': e.imagen_url
        }
        equipos.append(eq_data)

        # Lógica de Gráficos y Listas
        if e.estado in conteo_estado:
            conteo_estado[e.estado] += 1
        else:
            conteo_estado[e.estado] = 1

        if e.ubicacion:
            conteo_ubicacion[e.ubicacion] = conteo_ubicacion.get(e.ubicacion, 0) + 1

        if e.estado == 'En Taller':
            taller.append(eq_data)
        
        if e.estado == 'Avería' or e.margen < 0:
            criticos.append(eq_data)
            atrasados_count += 1
        elif e.margen < 500:
            proximos_count += 1
            
        if e.estado == 'Operativo':
            operativos_count += 1

    # Preparar KPIs
    total_equipos = len(equipos_db)
    kpis = {
        'atrasados': atrasados_count,
        'total': total_equipos,
        'proximos': proximos_count,
        'operativos': total_equipos,
        'controlados': operativos_count,
        'controlado_pct': round((operativos_count / total_equipos * 100)) if total_equipos > 0 else 0,
        'ot_abiertas': ot_db,
        'compras_proceso': 12, # Valor dinámico a programar a futuro
        'costo_mes': 4850000   # Valor dinámico a programar a futuro
    }

    # Empaquetar datos para Chart.js
    charts = {
        'estado': conteo_estado,
        'ubicacion': conteo_ubicacion,
        'gestion': { # Datos de ejemplo para el gráfico de barras doble
            'Ene': [45, 30], 'Feb': [52, 28], 'Mar': [48, 35], 'Abr': [ot_db, 12]
        }
    }

    actividad_formateada = [{
        'titulo': a.titulo, 
        'detalle': a.detalle, 
        'usuario': a.usuario, 
        'fecha': a.fecha.strftime("%d/%m/%Y %H:%M")
    } for a in actividad_db]

    # Renderizamos index.html (el archivo que modificamos)
    return render_template('index.html', 
                           kpis=kpis, 
                           charts=json.dumps(charts), 
                           equipos=equipos, 
                           criticos=criticos, 
                           taller=taller, 
                           actividad=actividad_formateada,
                           version="v4.0")


# ==========================================
# 3. RUTA DEL BUSCADOR / FICHA DE EQUIPO
# ==========================================

@app.route('/equipo/<codigo>', methods=['GET', 'POST'])
def ficha_equipo(codigo):
    equipo = Equipo.query.filter_by(codigo=codigo).first_or_404()

    if request.method == 'POST':
        try:
            equipo.marca = request.form['marca']
            equipo.modelo = request.form['modelo']
            equipo.ubicacion = request.form['ubicacion']
            equipo.lectura_actual = int(request.form['lectura_actual'])
            equipo.estado = request.form['estado'] # Operativo, En Taller, Avería
            
            # Registrar la actividad
            nueva_act = Actividad(
                titulo=f"Equipo Actualizado: {equipo.codigo}",
                detalle=f"Lectura: {equipo.lectura_actual} | Estado: {equipo.estado}",
                usuario="Administrador"
            )
            db.session.add(nueva_act)
            db.session.commit()
            
            flash('Datos actualizados correctamente.', 'success')
            return redirect(url_for('dashboard'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error al actualizar: {str(e)}', 'error')

    # Si es GET, deberás crear un archivo ficha_equipo.html en tus templates,
    # o si no lo tienes, devolvemos al dashboard con un mensaje por ahora.
    flash(f'Mostrando ficha del equipo {codigo} (Interfaz en desarrollo)', 'success')
    return redirect(url_for('dashboard'))


# ==========================================
# 4. RUTAS DE FORMULARIOS (ACCIONES)
# ==========================================

@app.route('/crear_ot', methods=['POST'])
def crear_ot():
    codigo = request.form.get('codigo')
    tipo = request.form.get('tipo')
    prioridad = request.form.get('prioridad')
    descripcion = request.form.get('descripcion')

    nueva_ot = OrdenTrabajo(codigo_equipo=codigo, tipo=tipo, prioridad=prioridad, descripcion=descripcion)
    nueva_act = Actividad(titulo="Nueva OT Creada", detalle=f"OT para {codigo} - Prioridad {prioridad}", usuario="Administrador")
    
    db.session.add(nueva_ot)
    db.session.add(nueva_act)
    
    # Si la OT es de avería o correctiva grave, actualizamos el estado del equipo
    equipo = Equipo.query.filter_by(codigo=codigo).first()
    if equipo and prioridad == 'Alta':
        equipo.estado = 'Avería'

    db.session.commit()
    flash(f'Orden de Trabajo creada para {codigo}.', 'success')
    return redirect(url_for('dashboard'))


@app.route('/lecturas', methods=['POST'])
def registrar_lectura():
    codigo = request.form.get('codigo')
    valor = request.form.get('valor')
    
    equipo = Equipo.query.filter_by(codigo=codigo).first()
    if equipo and valor.isdigit():
        equipo.lectura_actual = int(valor)
        act = Actividad(titulo="Lectura Actualizada", detalle=f"{codigo} -> {valor} km/hrs", usuario="Operador")
        db.session.add(act)
        db.session.commit()
        flash('Lectura registrada.', 'success')
    else:
        flash('Error: Código no encontrado o valor inválido.', 'error')
        
    return redirect(url_for('dashboard'))


@app.route('/importar_excel', methods=['POST'])
def importar_excel():
    # Lógica para leer Pandas/Excel a implementar
    flash('Módulo de Excel en configuración.', 'success')
    return redirect(url_for('dashboard'))


# ==========================================
# 5. RUTA DE CARGA DE DATOS DE PRUEBA
# ==========================================

@app.route('/admin/cargar_sql_final')
def cargar_sql_final():
    db.drop_all()
    db.create_all()

    equipos_prueba = [
        Equipo(codigo="VD-109", marca="SsangYong", modelo="Musso Grand", descripcion="Camioneta Supervisión", ubicacion="Talca", lectura_actual=45000, proxima_pm=50000, estado="Operativo"),
        Equipo(codigo="SC-201", marca="Scania", modelo="DC13", descripcion="Tractocamión Principal", ubicacion="Ruta 5 Sur", lectura_actual=345000, proxima_pm=346000, estado="Operativo"),
        Equipo(codigo="SC-188", marca="Scania", modelo="G380", descripcion="Camión Tolva", ubicacion="Linares", lectura_actual=612000, proxima_pm=610000, estado="En Taller"),
        Equipo(codigo="MB-405", marca="Mercedes-Benz", modelo="Actros", descripcion="Tractocamión", ubicacion="San Rafael", lectura_actual=128000, proxima_pm=125000, estado="Avería"),
        Equipo(codigo="MB-406", marca="Mercedes-Benz", modelo="Actros", descripcion="Tractocamión", ubicacion="Colbún", lectura_actual=95000, proxima_pm=110000, estado="Operativo")
    ]
    
    db.session.add_all(equipos_prueba)
    
    act_inicial = Actividad(titulo="Sistema Inicializado", detalle="Datos reales cargados en DB", usuario="Administrador")
    db.session.add(act_inicial)
    
    db.session.commit()
    flash('Base de datos reiniciada con equipos reales.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/admin/vaciar_datos')
def vaciar_datos():
    db.drop_all()
    db.create_all()
    flash('Datos vaciados correctamente.', 'success')
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    # Railway inyecta el puerto dinámicamente
    puerto = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=puerto, debug=True)
