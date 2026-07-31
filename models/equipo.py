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
    ubicacion = db.Column(db.String(100), default="CASA MATRIZ")
    estado_base = db.Column(db.String(50), default="Operativo") 
    control_base = db.Column(db.String(20), default="HORAS") 
    lectura_actual = db.Column(db.Float, default=0.0)
    proxima_pm = db.Column(db.Float, default=0.0)

    def __repr__(self):
        return f"<Equipo {self.codigo}>"


# =========================================================
# FILTROS - Modo Seguro para no botar el servidor
# =========================================================
class FiltroEquipo(db.Model):
    __tablename__ = 'filtro_equipo'
    
    id = db.Column(db.Integer, primary_key=True)
    codigo_equipo = db.Column(db.String(50), nullable=False)
    
    # Probablemente se llaman así. Las dejo activas, si alguna de estas no existe, 
    # la aplicación te volverá a mostrar una pantalla de error blanca.
    filtro = db.Column(db.String(100))
    codigo = db.Column(db.String(100))
    sistema = db.Column(db.String(100))

    def __repr__(self):
        return f"<Filtro {self.codigo_equipo}>"


# =========================================================
# DOCUMENTOS
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
