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
    estado_base = db.Column(db.String(50), default="Operativo") 
    
    # Mantenimiento y Rendimiento
    control_base = db.Column(db.String(20), default="HORAS") 
    frecuencia_base = db.Column(db.Float, default=250.0) 
    lectura_actual = db.Column(db.Float, default=0.0)
    proxima_pm = db.Column(db.Float, default=0.0)

    @property
    def margen(self):
        return (self.proxima_pm or 0.0) - (self.lectura_actual or 0.0)

    def __repr__(self):
        return f"<Equipo {self.codigo}>"


# =========================================================
# TABLA DE FILTROS (ALINEADA 100% CON POSTGRESQL)
# =========================================================
class FiltroEquipo(db.Model):
    __tablename__ = 'filtro_equipo'
    
    id = db.Column(db.Integer, primary_key=True)
    codigo_equipo = db.Column(db.String(50), nullable=False)
    
    # ESTAS SON LAS COLUMNAS REALES QUE POSTGRESQL TIENE ADENTRO
    sistema = db.Column(db.String(100))
    cant = db.Column(db.String(50))
    fleetguard = db.Column(db.String(100))
    baldwind = db.Column(db.String(100))
    originales = db.Column(db.String(100))
    donaldson = db.Column(db.String(100))

    # ==================================================
    # ALIAS MÁGICOS (Para que el PDF lea bien sin chocar)
    # ==================================================
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


# =========================================================
# DOCUMENTOS Y TRAZABILIDAD
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


class HistorialUbicacion(db.Model):
    __tablename__ = 'historial_ubicacion'
    
    id = db.Column(db.Integer, primary_key=True)
    codigo_equipo = db.Column(db.String(50), nullable=False)
    ubicacion_anterior = db.Column(db.String(100))
    ubicacion_nueva = db.Column(db.String(100), nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.now)

    def __repr__(self):
        return f"<Movimiento {self.codigo_equipo}: {self.ubicacion_anterior} -> {self.ubicacion_nueva}>"
