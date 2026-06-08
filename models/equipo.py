# models/equipo.py
from extensions import db

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
    planificacion_mantencion = db.Column(db.Text, default="Registrar estrategia de mantenimiento...")

    @property
    def margen(self): return (self.proxima_pm or 0) - (self.lectura_actual or 0)

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
