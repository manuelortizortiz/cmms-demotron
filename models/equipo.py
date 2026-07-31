from extensions import db
from datetime import datetime

class Equipo(db.Model):
    __tablename__ = 'equipo'
    
    # Datos Principales
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), unique=True, nullable=False)
    tipo_equipo = db.Column(db.String(100))
    marca = db.Column(db.String(100))
    modelo = db.Column(db.String(100))
    
    # Identificación Legal
    patente = db.Column(db.String(50))
    vin = db.Column(db.String(100))
    
    # Operación y Logística
    ubicacion = db.Column(db.String(100), default="CASA MATRIZ")
    estado_base = db.Column(db.String(50), default="Operativo") # Operativo, Taller, Fuera de Servicio
    
    # Mantenimiento y Rendimiento
    control_base = db.Column(db.String(20), default="HORAS") # HORAS o KM
    lectura_actual = db.Column(db.Float, default=0.0)
    proxima_pm = db.Column(db.Float, default=0.0)

    def __repr__(self):
        return f"<Equipo {self.codigo}>"


# =========================================================
# TABLA DE FILTROS ORIGINAL
# =========================================================
class FiltroEquipo(db.Model):
    __tablename__ = 'filtro_equipo'
    
    id = db.Column(db.Integer, primary_key=True)
    codigo_equipo = db.Column(db.String(50), nullable=False)
    sistema = db.Column(db.String(100))
    nombre_filtro = db.Column(db.String(100))
    codigo_parte = db.Column(db.String(100))

    def __repr__(self):
        return f"<Filtro {self.nombre_filtro} - {self.codigo_equipo}>"


# =========================================================
# NUEVA TABLA: Documentos Legales y Revisiones del Equipo
# =========================================================
class DocumentoEquipo(db.Model):
    __tablename__ = 'documento_equipo'
    
    id = db.Column(db.Integer, primary_key=True)
    codigo_equipo = db.Column(db.String(50), nullable=False)
    tipo_documento = db.Column(db.String(100), nullable=False)
    fecha_vencimiento = db.Column(db.Date, nullable=True)
    archivo_url = db.Column(db.String(255), nullable=True)
    fecha_subida = db.Column(db.DateTime, default=datetime.now)

    def __repr__(self):
        return f"<Documento {self.tipo_documento} - {self.codigo_equipo}>"
