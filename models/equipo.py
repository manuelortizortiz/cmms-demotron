from extensions import db
from datetime import datetime

class Equipo(db.Model):
    __tablename__ = 'equipo'
    
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), unique=True, nullable=False)
    tipo_equipo = db.Column(db.String(100))
    marca = db.Column(db.String(100))
    modelo = db.Column(db.String(100))
    patente = db.Column(db.String(50))
    vin = db.Column(db.String(100))
    numero_motor = db.Column(db.String(100)) # CAMPO RECUPERADO
    ubicacion = db.Column(db.String(100), default="CASA MATRIZ")
    estado_base = db.Column(db.String(50), default="Operativo") 
    control_base = db.Column(db.String(20), default="HORAS") 
    frecuencia_base = db.Column(db.Float, default=250.0) 
    lectura_actual = db.Column(db.Float, default=0.0)
    proxima_pm = db.Column(db.Float, default=0.0)

    @property
    def margen(self):
        return (self.proxima_pm or 0.0) - (self.lectura_actual or 0.0)

    def __repr__(self):
        return f"<Equipo {self.codigo}>"

class FiltroEquipo(db.Model):
    __tablename__ = 'filtro_equipo'
    
    id = db.Column(db.Integer, primary_key=True)
    codigo_equipo = db.Column(db.String(50), nullable=False)
    sistema = db.Column(db.String(100))
    cant = db.Column(db.String(50))
    fleetguard = db.Column(db.String(100))
    baldwind = db.Column(db.String(100))
    originales = db.Column(db.String(100))
    donaldson = db.Column(db.String(100))
    otra_alternativa = db.Column(db.String(150))

    @property
    def filtro(self): return self.sistema
    @property
    def cantidad(self): return self.cant
    @property
    def codigo(self): return self.originales
    @property
    def codigo_parte(self): return self.originales
    @property
    def nombre_filtro(self): return self.sistema

    def __repr__(self):
        return f"<Filtro {self.sistema} - {self.codigo_equipo}>"

class DocumentoEquipo(db.Model):
    __tablename__ = 'documento_equipo'
    id = db.Column(db.Integer, primary_key=True)
    codigo_equipo = db.Column(db.String(50), nullable=False)
    tipo_documento = db.Column(db.String(100), nullable=False)
    fecha_vencimiento = db.Column(db.Date, nullable=True)
    archivo_url = db.Column(db.String(255), nullable=True)
    fecha_subida = db.Column(db.DateTime, default=datetime.now)

class HistorialUbicacion(db.Model):
    __tablename__ = 'historial_ubicacion'
    id = db.Column(db.Integer, primary_key=True)
    codigo_equipo = db.Column(db.String(50), nullable=False)
    ubicacion_anterior = db.Column(db.String(100))
    ubicacion_nueva = db.Column(db.String(100), nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.now)
