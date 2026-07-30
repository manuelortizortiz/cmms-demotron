from extensions import db
from datetime import datetime

# MODO MIGRACIÓN: Validaciones y Triggers desactivados temporalmente 
# para permitir la carga masiva del historial SQL sin bloqueos.

class HistorialLectura(db.Model):
    __tablename__ = 'historial_lectura'
    
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=datetime.now)
    codigo_equipo = db.Column(db.String(50), nullable=False)
    horometro = db.Column(db.Integer, default=0)
    kilometraje = db.Column(db.Integer, default=0)
    observacion = db.Column(db.String(255))
    responsable = db.Column(db.String(100))

class CompraRepuesto(db.Model):
    __tablename__ = 'compra_repuesto'
    
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=datetime.now)
    oc = db.Column(db.String(50))
    codigo_equipo = db.Column(db.String(50), nullable=False)
    descripcion = db.Column(db.String(255))
    costo_pm_clp = db.Column(db.Float, default=0.0)
    estado_recepcion = db.Column(db.String(50), default='Pendiente') 
    estado_aprobacion = db.Column(db.String(50), default='Aprobada')
