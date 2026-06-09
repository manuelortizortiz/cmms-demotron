from extensions import db
from datetime import datetime

class Personal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100))
    cargo = db.Column(db.String(50))
    estado = db.Column(db.String(20), default="Activo")
    equipo_asignado = db.Column(db.String(50), default="Ninguno")

class RegistroUsoEquipo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=datetime.now)
    operador = db.Column(db.String(100))
    codigo_equipo = db.Column(db.String(50))
    observacion = db.Column(db.Text)

class Mecanico(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    rut = db.Column(db.String(20), nullable=True)  # <-- NUEVO CAMPO RUT
    nombre = db.Column(db.String(100))
    especialidad = db.Column(db.String(50))
    estado = db.Column(db.String(20), default="Activo")
