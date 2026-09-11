from extensions import db
from datetime import datetime

class OrdenTrabajo(db.Model):
    __tablename__ = 'orden_trabajo'
    
    id = db.Column(db.Integer, primary_key=True)
    # ===== NUEVO CAMPO MULTI-EMPRESA =====
    empresa = db.Column(db.String(100), default='DEMOTRON') 
    
    folio = db.Column(db.String(50), unique=True)
    codigo_equipo = db.Column(db.String(50))
    
    # Clasificación
    tipo_ot = db.Column(db.String(50)) # Preventiva o Correctiva
    tipo_mantencion = db.Column(db.String(150)) # Ej: Pauta PM1, PM2
    sistema_falla = db.Column(db.String(150)) # Solo para Correctivas
    causa_raiz = db.Column(db.String(255)) # Solo para Correctivas
    observacion = db.Column(db.Text)
    
    mecanico = db.Column(db.String(150))
    
    # Tiempos
    fecha = db.Column(db.DateTime, default=datetime.now)
    fecha_cierre = db.Column(db.DateTime)
    
    # Kanban de Taller
    estado = db.Column(db.String(50), default='Pendiente') # Pendiente, En Progreso, En Revisión, Finalizada
    
    lectura_str = db.Column(db.String(50)) 
    costo_mantencion_clp = db.Column(db.Float, default=0.0)
    
    @property
    def costo_str(self):
        """ Formatea el valor flotante de la BD a texto de moneda chilena en vivo """
        try:
            if self.costo_mantencion_clp is not None:
                return f"$ {int(self.costo_mantencion_clp):,}".replace(",", ".")
        except:
            pass
        return "$ 0"
