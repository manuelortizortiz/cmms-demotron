import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from sqlalchemy import text
from extensions import db

from models.equipo import Equipo, FiltroEquipo, DocumentoEquipo, HistorialUbicacion
from models.orden_trabajo import OrdenTrabajo
from models.bodega import InventarioBodega, Repuesto, MovimientoBodega, KitPM, RecetaModelo
from models.historial import HistorialLectura, CompraRepuesto
from models.personal import Personal, RegistroUsoEquipo, Mecanico
from models.chatter import RegistroChatter
from models.auditoria import LogCambios
from models.logistica import Empresa, Conductor, Rampla, RutaMaestra, SolicitudTransporte, Viaje, CargaViaje, OperacionPortuaria, IncidenciaTransporte

app = Flask(__name__)

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'mantyre_erp_secret_key_2026_pro')
db_url = os.environ.get('DATABASE_URL', 'sqlite:///mantyre_erp.db')
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = "Por favor, inicie sesión en ManTyre ERP para acceder."

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), default='usuario')
    empresa_activa = db.Column(db.String(100), default='demotron')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ==========================================
# AUTO-MIGRACIÓN SILENCIOSA BLINDADA
# ==========================================
with app.app_context():
    db.create_all()
    
    # 1. Migrar Empresas a todas las tablas
    tablas_a_migrar = ['equipo', 'orden_trabajo', 'conductores', 'ramplas', 'solicitudes_transporte', 'viajes_transporte']
    for tabla in tablas_a_migrar:
        try:
            db.session.execute(text(f"ALTER TABLE {tabla} ADD COLUMN empresa VARCHAR(100) DEFAULT 'DEMOTRON'"))
            db.session.commit()
        except Exception:
            db.session.rollback()

    # 2. SOLUCIÓN DEFINITIVA: Inyectar TODAS las columnas nuevas de Orden de Trabajo
    columnas_nuevas_ot = [
        "observacion TEXT",
        "lectura_str VARCHAR(50)",
        "costo_mantencion_clp FLOAT DEFAULT 0.0"
    ]
    
    for col in columnas_nuevas_ot:
        try:
            db.session.execute(text(f"ALTER TABLE orden_trabajo ADD COLUMN {col}"))
            db.session.commit()
        except Exception:
            db.session.rollback() # Si la columna ya existe, simplemente sigue de largo sin romper la app

    # Crear usuario Admin Salvavidas
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', password_hash=generate_password_hash('admin123'), role='admin')
        db.session.add(admin)
        db.session.commit()

from routes.dashboard import dashboard_bp
from routes.admin import admin_bp

app.register_blueprint(dashboard_bp)
app.register_blueprint(admin_bp)

@app.route('/health')
def health_check():
    return jsonify({"status": "ok"})

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.dashboard'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        empresa_seleccionada = request.form.get('empresa')
        
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            user.empresa_activa = empresa_seleccionada
            db.session.commit()
            login_user(user)
            return redirect(url_for('dashboard.dashboard'))
        else:
            flash('Credenciales incorrectas.')
            
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)
