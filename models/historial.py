from extensions import db
from sqlalchemy.orm import validates
from sqlalchemy import event, text
from datetime import datetime

class HistorialLectura(db.Model):
    __tablename__ = 'historial_lectura'
    
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=datetime.now)
    codigo_equipo = db.Column(db.String(50), nullable=False)
    horometro = db.Column(db.Integer, default=0)
    kilometraje = db.Column(db.Integer, default=0)
    observacion = db.Column(db.String(255))
    responsable = db.Column(db.String(100))

    @validates('horometro', 'kilometraje')
    def validate_lecturas(self, key, value):
        if not value: return value
        value = int(value)
        ultimo = HistorialLectura.query.filter_by(codigo_equipo=self.codigo_equipo)\
            .order_by(HistorialLectura.fecha.desc(), HistorialLectura.id.desc()).first()
        if ultimo:
            if key == 'horometro' and ultimo.horometro and value < ultimo.horometro:
                raise ValueError(f"El horómetro ({value}) no puede ser menor al último ({ultimo.horometro}).")
            if key == 'kilometraje' and ultimo.kilometraje and value < ultimo.kilometraje:
                raise ValueError(f"El kilometraje ({value}) no puede ser menor al último ({ultimo.kilometraje}).")
        return value

class CompraRepuesto(db.Model):
    __tablename__ = 'compra_repuesto'
    
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=datetime.now)
    oc = db.Column(db.String(50))
    codigo_equipo = db.Column(db.String(50), nullable=False)
    descripcion = db.Column(db.String(255))
    costo_pm_clp = db.Column(db.Float, default=0.0)
    estado_recepcion = db.Column(db.String(50), default='Pendiente') 
    
    # NUEVO: Lógica de Aprobaciones
    estado_aprobacion = db.Column(db.String(50), default='Aprobada')

    @validates('costo_pm_clp')
    def check_approval_limit(self, key, value):
        # Si la compra supera aprox 50 UF (~1.850.000 CLP), requiere aprobación gerencial
        if value and float(value) > 1850000:
            self.estado_aprobacion = 'Por Aprobar'
        return value

# =========================================================================
# GATILLO (TRIGGER) AUTOMÁTICO: GENERACIÓN DE OT POR KILOMETRAJE
# =========================================================================
@event.listens_for(HistorialLectura, 'after_insert')
def check_triggers_mantenimiento(mapper, connection, target):
    # Consultamos directo en SQL para no interferir con la sesión de SQLAlchemy actual
    equipo = connection.execute(
        text("SELECT control_base, proxima_pm FROM equipo WHERE codigo = :cod"),
        {"cod": target.codigo_equipo}
    ).fetchone()
    
    if not equipo: return

    lectura_actual = target.horometro if equipo[0] == 'HORAS' else target.kilometraje
    proxima_pm = equipo[1] or 0
    
    # Si la lectura supera o iguala la pauta de mantenimiento
    if lectura_actual >= proxima_pm and proxima_pm > 0:
        folio_auto = f"PM-AUTO-{datetime.now().strftime('%d%H%M')}"
        connection.execute(
            text("""INSERT INTO orden_trabajo (codigo_equipo, folio, tipo_ot, estado, lectura, fecha, mecanico) 
                    VALUES (:cod, :folio, 'Preventiva', 'Pendiente', :lec, :fec, 'Sin Asignar')"""),
            {"cod": target.codigo_equipo, "folio": folio_auto, "lec": lectura_actual, "fec": datetime.now()}
        )
