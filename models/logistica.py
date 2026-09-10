from extensions import db
from datetime import datetime

# ==========================================
# MÓDULO LOGÍSTICA, TRANSPORTE Y TMS
# ==========================================

class Empresa(db.Model):
    __tablename__ = 'empresas'
    id = db.Column(db.Integer, primary_key=True)
    nombre_legal = db.Column(db.String(150), nullable=False) # Demotron o Mimbral
    rut = db.Column(db.String(20))
    estado = db.Column(db.String(50), default='ACTIVA')

class Conductor(db.Model):
    __tablename__ = 'conductores'
    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey('empresas.id'))
    rut = db.Column(db.String(20), unique=True, nullable=False)
    nombre_completo = db.Column(db.String(150), nullable=False)
    clase_licencia = db.Column(db.String(20))
    vencimiento_licencia = db.Column(db.Date)
    estado = db.Column(db.String(50), default='DISPONIBLE') # DISPONIBLE, EN VIAJE, DESVINCULADO

class Rampla(db.Model):
    __tablename__ = 'ramplas'
    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey('empresas.id'))
    codigo_interno = db.Column(db.String(50), unique=True)
    patente = db.Column(db.String(20))
    tipo_rampla = db.Column(db.String(100)) # Cama baja, Plana, Furgón
    capacidad_kg = db.Column(db.Float)
    estado = db.Column(db.String(50), default='DISPONIBLE') # DISPONIBLE, EN MANTENIMIENTO, EN VIAJE

class RutaMaestra(db.Model):
    __tablename__ = 'rutas_maestras'
    id = db.Column(db.Integer, primary_key=True)
    nombre_ruta = db.Column(db.String(150))
    origen = db.Column(db.String(150))
    destino = db.Column(db.String(150))
    puerto_asociado = db.Column(db.String(100))
    kilometros = db.Column(db.Float)
    tiempo_estandar_hrs = db.Column(db.Float)
    costo_peajes_est = db.Column(db.Float)

class SolicitudTransporte(db.Model):
    __tablename__ = 'solicitudes_transporte'
    id = db.Column(db.Integer, primary_key=True)
    cliente = db.Column(db.String(150))
    fecha_solicitud = db.Column(db.DateTime, default=datetime.now)
    fecha_requerida = db.Column(db.Date)
    origen = db.Column(db.String(150))
    destino = db.Column(db.String(150))
    tipo_carga = db.Column(db.String(100))
    peso_kg = db.Column(db.Float)
    estado = db.Column(db.String(50), default='SOLICITADA') # APROBADA, PLANIFICADA

class Viaje(db.Model):
    __tablename__ = 'viajes_transporte'
    id = db.Column(db.Integer, primary_key=True)
    folio_viaje = db.Column(db.String(50), unique=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey('empresas.id'))
    solicitud_id = db.Column(db.Integer, db.ForeignKey('solicitudes_transporte.id'), nullable=True)
    ruta_id = db.Column(db.Integer, db.ForeignKey('rutas_maestras.id'))
    
    # Relaciones Operativas
    conductor_id = db.Column(db.Integer, db.ForeignKey('conductores.id'))
    rampla_id = db.Column(db.Integer, db.ForeignKey('ramplas.id'))
    # Conexión vital con el CMMS (El tractocamión)
    codigo_equipo = db.Column(db.String(50), db.ForeignKey('equipo.codigo')) 
    
    fecha_programada = db.Column(db.DateTime)
    fecha_salida_real = db.Column(db.DateTime)
    fecha_llegada_real = db.Column(db.DateTime)
    
    estado = db.Column(db.String(50), default='PROGRAMADO') # EN RUTA, EN PUERTO, ENTREGADO, CERRADO
    
    # Costos consolidados
    costo_combustible = db.Column(db.Float, default=0.0)
    costo_peajes = db.Column(db.Float, default=0.0)
    costo_viaticos = db.Column(db.Float, default=0.0)
    costo_total = db.Column(db.Float, default=0.0)

class CargaViaje(db.Model):
    __tablename__ = 'cargas_viaje'
    id = db.Column(db.Integer, primary_key=True)
    viaje_id = db.Column(db.Integer, db.ForeignKey('viajes_transporte.id'))
    descripcion = db.Column(db.String(255))
    peso_kg = db.Column(db.Float)
    codigo_equipo_cargado = db.Column(db.String(50), nullable=True) # Si la carga es una maquinaria propia de Demotron

class OperacionPortuaria(db.Model):
    __tablename__ = 'operaciones_portuarias'
    id = db.Column(db.Integer, primary_key=True)
    viaje_id = db.Column(db.Integer, db.ForeignKey('viajes_transporte.id'))
    puerto = db.Column(db.String(100))
    booking_bl = db.Column(db.String(100))
    contenedor = db.Column(db.String(50))
    ventana_inicio = db.Column(db.DateTime)
    ventana_fin = db.Column(db.DateTime)
    hora_ingreso_gate = db.Column(db.DateTime)
    hora_salida_gate = db.Column(db.DateTime)
    estado = db.Column(db.String(50), default='ESPERANDO INGRESO')

class IncidenciaTransporte(db.Model):
    __tablename__ = 'incidencias_transporte'
    id = db.Column(db.Integer, primary_key=True)
    viaje_id = db.Column(db.Integer, db.ForeignKey('viajes_transporte.id'))
    fecha_hora = db.Column(db.DateTime, default=datetime.now)
    tipo = db.Column(db.String(100)) # Panne, Atraso, Accidente, Documentación
    severidad = db.Column(db.String(50))
    descripcion = db.Column(db.Text)
    estado = db.Column(db.String(50), default='ABIERTA')
