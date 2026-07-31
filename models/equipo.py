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
# TABLA DE FILTROS (Mapeada desde Plantilla Maestro)
# =========================================================
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
    otra_alternativa = db.Column(db.String(100))

    # Propiedades dinámicas para compatibilidad con plantillas y vistas
    @property
    def filtro(self):
        return self.sistema

    @property
    def nombre_filtro(self):
        return self.sistema

    @property
    def cantidad(self):
        return self.cant

    @property
    def codigo_parte(self):
        for val in [self.originales, self.fleetguard, self.donaldson, self.baldwind, self.otra_alternativa]:
            if val and str(val).strip() and str(val).strip() != '-':
                return str(val).strip()
        return '-'

    @property
    def codigo(self):
        return self.codigo_parte

    def __repr__(self):
        return f"<Filtro {self.sistema} - {self.codigo_equipo}>"


# =========================================================
# TABLA DE DOCUMENTOS LEGALES (Revisión Técnica, SOAP, etc)
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
