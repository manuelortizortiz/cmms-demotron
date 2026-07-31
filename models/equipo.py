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

# =========================================================
# 4. GENERACIÓN DE ORDEN DE TRABAJO (VISTA PDF)
# =========================================================
@dashboard_bp.route('/imprimir_ot/<int:ot_id>', strict_slashes=False)
@login_required
def imprimir_ot(ot_id):
    try:
        from models.equipo import FiltroEquipo  # Importamos los filtros por seguridad
        
        # 1. Buscamos la Orden de Trabajo
        ot = OrdenTrabajo.query.get(ot_id)
        if not ot:
            return "Orden de trabajo no encontrada.", 404
            
        # 2. Buscamos la máquina asociada
        equipo = Equipo.query.filter_by(codigo=ot.codigo_equipo).first()
        
        # 3. Extraemos todos los filtros, aceites y capacidades de esta máquina
        filtros = []
        if equipo:
            filtros = FiltroEquipo.query.filter_by(codigo_equipo=equipo.codigo).all()
            
        # 4. Enviamos toda la información a tu plantilla original de impresión
        return render_template('imprimir_ot.html', ot=ot, equipo=equipo, filtros=filtros, hoy=datetime.now())
        
    except Exception as e:
        return f"Error al generar la Orden de Trabajo: {str(e)}"
