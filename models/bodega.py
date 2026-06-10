from extensions import db

class InventarioBodega(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    codigo_item = db.Column(db.String(50), nullable=True)
    nombre = db.Column(db.String(100), nullable=False)
    categoria = db.Column(db.String(50), default='Filtro') # Ej: Filtro, Kit, Lubricante
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
