from extensions import db
from flask_login import UserMixin

class Usuario(db.Model, UserMixin):
    __tablename__ = 'usuarios'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    nombre = db.Column(db.String(100))
    email = db.Column(db.String(120))
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='usuario')
    activo = db.Column(db.Boolean, default=True)
