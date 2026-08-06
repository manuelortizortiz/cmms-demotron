from extensions import db
from datetime import datetime

# --- TABLA ANTIGUA (Se mantiene temporalmente para no romper el sistema actual) ---
class InventarioBodega(db.Model):
    __tablename__ = 'inventario_bodega'
    id = db.Column(db.Integer, primary_key=True)
    codigo_item = db.Column(db.String(50), nullable=True)
    nombre = db.Column(db.String(100), nullable=False)
    categoria = db.Column(db.String(50), default='Filtro')
    cantidad = db.Column(db.Integer, default=0)
    ubicacion = db.Column(db.String(100), nullable=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'codigo_item': self.codigo_item,
            'nombre': self.nombre,
            'categoria': self.categoria,
            'cantidad': self.cantidad,
            'ubicacion': self.ubicacion
        }

# --- NUEVA ARQUITECTURA WMS (CLASE MUNDIAL) ---

class Repuesto(db.Model):
    __tablename__ = 'repuestos'
    id = db.Column(db.Integer, primary_key=True)
    codigo_oem = db.Column(db.String(100), unique=True, index=True)
    codigo_alt = db.Column(db.String(100), nullable=True)
    nombre = db.Column(db.String(150), nullable=False)
    descripcion = db.Column(db.Text)
    
    # Clasificación
    categoria = db.Column(db.String(50)) # Filtros, Rodamientos, Lubricantes, etc.
    familia = db.Column(db.String(50))
    marca = db.Column(db.String(50))
    unidad_medida = db.Column(db.String(20), default='UN')
    
    # KPIs de Inventario
    stock_actual = db.Column(db.Float, default=0.0)
    stock_minimo = db.Column(db.Float, default=0.0)
    stock_maximo = db.Column(db.Float, default=0.0)
    
    # Costos
    precio_promedio = db.Column(db.Float, default=0.0)
    ultimo_precio = db.Column(db.Float, default=0.0)
    
    # Logística Físca
    bodega = db.Column(db.String(50), default='BODEGA CENTRAL')
    pasillo = db.Column(db.String(20))
    estante = db.Column(db.String(20))
    nivel = db.Column(db.String(20))
    
    fecha_creacion = db.Column(db.DateTime, default=datetime.now)
    estado = db.Column(db.String(20), default='Activo')

class KitPM(db.Model):
    __tablename__ = 'kits_pm'
    id = db.Column(db.Integer, primary_key=True)
    codigo_kit = db.Column(db.String(50), unique=True)
    nombre = db.Column(db.String(150))
    tiempo_estimado_hr = db.Column(db.Float)
    estado = db.Column(db.String(20), default='Activo')

class ComponenteKit(db.Model):
    __tablename__ = 'componentes_kit'
    id = db.Column(db.Integer, primary_key=True)
    kit_id = db.Column(db.Integer, db.ForeignKey('kits_pm.id'))
    repuesto_id = db.Column(db.Integer, db.ForeignKey('repuestos.id'))
    cantidad = db.Column(db.Float, nullable=False)

class MovimientoBodega(db.Model):
    __tablename__ = 'movimientos_bodega'
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=datetime.now)
    tipo_movimiento = db.Column(db.String(20)) # INGRESO, SALIDA, AJUSTE, RESERVA
    motivo = db.Column(db.String(50)) # Compra, OT, Garantía, Pérdida
    
    repuesto_id = db.Column(db.Integer, db.ForeignKey('repuestos.id'))
    cantidad = db.Column(db.Float, nullable=False)
    costo_unitario = db.Column(db.Float, default=0.0)
    
    # Trazabilidad
    documento_ref = db.Column(db.String(100)) # OC, Factura, Guía
    ot_id = db.Column(db.Integer, nullable=True) # ID de la Orden de Trabajo
    codigo_equipo = db.Column(db.String(50), nullable=True)
    
    usuario = db.Column(db.String(100))
    observaciones = db.Column(db.Text)
