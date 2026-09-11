from extensions import db
from datetime import datetime

class Equipo(db.Model):
    __tablename__ = 'equipo'
    
    codigo = db.Column(db.String(50), primary_key=True)
    # ===== NUEVO CAMPO MULTI-EMPRESA =====
    empresa = db.Column(db.String(100), default='DEMOTRON') 
    
    marca = db.Column(db.String(100))
    modelo = db.Column(db.String(100))
    tipo_equipo = db.Column(db.String(100))
    patente = db.Column(db.String(50))
    vin = db.Column(db.String(100))
    
    estado_base = db.Column(db.String(50), default='Operativo') # Operativo, Taller, Fuera de Servicio
    control_base = db.Column(db.String(50), default='HORAS') # HORAS o KILOMETROS
    
    lectura_actual = db.Column(db.Float, default=0.0)
    proxima_pm = db.Column(db.Float, default=0.0)
    ubicacion = db.Column(db.String(150), default='SIN ASIGNAR')


class FiltroEquipo(db.Model):
    __tablename__ = 'filtro_equipo'
    id = db.Column(db.Integer, primary_key=True)
    codigo_equipo = db.Column(db.String(50), db.ForeignKey('equipo.codigo'))
    sistema = db.Column(db.String(100))
    cant = db.Column(db.String(20), default='1')
    originales = db.Column(db.String(100))
    fleetguard = db.Column(db.String(100))
    donaldson = db.Column(db.String(100))
    baldwind = db.Column(db.String(100))
    otra_alternativa = db.Column(db.String(100))


class DocumentoEquipo(db.Model):
    __tablename__ = 'documento_equipo'
    id = db.Column(db.Integer, primary_key=True)
    codigo_equipo = db.Column(db.String(50), db.ForeignKey('equipo.codigo'))
    tipo_documento = db.Column(db.String(100))
    fecha_vencimiento = db.Column(db.Date)
    archivo_url = db.Column(db.String(255))
    fecha_subida = db.Column(db.DateTime, default=datetime.now)


class HistorialUbicacion(db.Model):
    __tablename__ = 'historial_ubicacion'
    id = db.Column(db.Integer, primary_key=True)
    codigo_equipo = db.Column(db.String(50), db.ForeignKey('equipo.codigo'))
    ubicacion_anterior = db.Column(db.String(150))
    ubicacion_nueva = db.Column(db.String(150))
    fecha = db.Column(db.DateTime, default=datetime.now)
