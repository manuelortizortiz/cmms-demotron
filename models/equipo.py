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
# TABLA DE FILTROS BLINDADA CONTRA ERRORES DE EXCEL
# =========================================================
class FiltroEquipo(db.Model):
    __tablename__ = 'filtro_equipo'
    
    id = db.Column(db.Integer, primary_key=True)
    codigo_equipo = db.Column(db.String(50), nullable=False)
    
    # COLUMNAS CLÁSICAS (Las reales que espera tu Excel / SQL)
    filtro = db.Column(db.String(100))
    cantidad = db.Column(db.String(50))
    codigo = db.Column(db.String(100))

    # ==================================================
    # ALIAS MÁGICOS (Para que tu script no vuelva a chocar)
    # ==================================================
    @property
    def sistema(self): return self.filtro
    @sistema.setter
    def sistema(self, val): self.filtro = val

    @property
    def cant(self): return self.cantidad
    @cant.setter
    def cant(self, val): self.cantidad = val

    @property
    def originales(self): return self.codigo
    @originales.setter
    def originales(self, val): self.codigo = val

    @property
    def codigo_parte(self): return self.codigo
    @codigo_parte.setter
    def codigo_parte(self, val): self.codigo = val

    @property
    def nombre_filtro(self): return self.filtro
    @nombre_filtro.setter
    def nombre_filtro(self, val): self.filtro = val

    # Marcas alternativas (Simuladas para que el PDF se vea bien sin alterar la BD original)
    @property
    def fleetguard(self): return "-"
    @property
    def donaldson(self): return "-"
    @property
    def baldwind(self): return "-"

    def __repr__(self):
        return f"<Filtro {self.filtro} - {self.codigo_equipo}>"


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
