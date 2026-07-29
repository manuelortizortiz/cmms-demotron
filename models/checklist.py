from extensions import db
from datetime import datetime

class ChecklistPreUso(db.Model):
    __tablename__ = 'checklist_preuso'
    
    id = db.Column(db.Integer, primary_key=True)
    codigo_equipo = db.Column(db.String(50), nullable=False)
    operador = db.Column(db.String(100))
    fecha = db.Column(db.DateTime, default=datetime.now)
    
    # Batería de inspección rápida
    niveles_ok = db.Column(db.Boolean, default=True)
    fugas_ok = db.Column(db.Boolean, default=True)
    frenos_ok = db.Column(db.Boolean, default=True)
    neumaticos_ok = db.Column(db.Boolean, default=True)
    
    observaciones = db.Column(db.Text)
    foto_evidencia_url = db.Column(db.String(255))
    estado_equipo = db.Column(db.String(20), default='Operativo')
