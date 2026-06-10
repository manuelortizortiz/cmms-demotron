from extensions import db
from datetime import datetime

class RegistroChatter(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    modelo_ref = db.Column(db.String(50), nullable=False) # Ej: 'ot', 'equipo', 'compra'
    registro_id = db.Column(db.String(50), nullable=False) # El ID o Código
    
    autor = db.Column(db.String(100), default='Sistema')
    accion = db.Column(db.String(50), default='comentario') # Tipos: comentario, cambio_estado, adjunto
    mensaje = db.Column(db.Text, nullable=True)
    
    # Auditoría (El "Qué cambió")
    valor_anterior = db.Column(db.String(255), nullable=True)
    valor_nuevo = db.Column(db.String(255), nullable=True)
    
    archivo_url = db.Column(db.String(255), nullable=True)
    fecha = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        return {
            'id': self.id,
            'autor': self.autor,
            'accion': self.accion,
            'mensaje': self.mensaje,
            'valor_anterior': self.valor_anterior,
            'valor_nuevo': self.valor_nuevo,
            'archivo_url': self.archivo_url,
            'fecha': self.fecha.strftime('%d/%m/%Y %H:%M') if self.fecha else ''
        }
