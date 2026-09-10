import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix

# Importar extensión de BD (Instancia de SQLAlchemy)
from extensions import db

# ==========================================
# IMPORTACIÓN DE MODELOS (Mantenimiento y Flota)
# ==========================================
from models.equipo import Equipo, FiltroEquipo, DocumentoEquipo, HistorialUbicacion
from models.orden_trabajo import OrdenTrabajo
from models.bodega import InventarioBodega, Repuesto, MovimientoBodega, KitPM, RecetaModelo
from models.historial import HistorialLectura, CompraRepuesto
from models.personal import Personal, RegistroUsoEquipo, Mecanico
from models.chatter import RegistroChatter
from models.auditoria import LogCambios

# ==========================================
# IMPORTACIÓN DE MODELOS (Nuevo ERP Logístico ManTyre)
# ==========================================
from models.logistica import Empresa, Conductor, Rampla, RutaMaestra, SolicitudTransporte, Viaje, CargaViaje, OperacionPortuaria, IncidenciaTransporte


app = Flask(__name__)

# Configuración de Seguridad y Sesiones
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'mantyre_erp_secret_key_2026_pro')

# Configuración de Base de Datos (Soporta PostgreSQL en Coolify o SQLite local)
db_url = os.environ.get('DATABASE_URL', 'sqlite:///mantyre_erp.db')
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Solución esencial para Coolify y proxys inversos (Evita bucles de redirección HTTPS)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Inicializar Base de Datos con la App
db.init_app(app)

# ==========================================
# SISTEMA DE USUARIOS Y AUTENTICACIÓN
# ==========================================
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
    # Nuevo campo para identificar en qué entorno está trabajando el usuario (Demotron o Mimbral)
    empresa_activa = db.Column(db.String(100), default='demotron')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ==========================================
# CREACIÓN DE TABLAS INICIALES Y MIGRACIÓN SILENCIOSA
# ==========================================
with app.app_context():
    db.create_all() # Genera las tablas de logística sin borrar el historial existente de Demotron
    
    # Crear un usuario administrador por defecto (Salvavidas si la BD está vacía)
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', password_hash=generate_password_hash('admin123'), role='admin')
        db.session.add(admin)
        db.session.commit()

# ==========================================
# REGISTRO DE MÓDULOS (Blueprints)
# ==========================================
from routes.dashboard import dashboard_bp
from routes.admin import admin_bp

app.register_blueprint(dashboard_bp)
app.register_blueprint(admin_bp)

# ==========================================
# RUTAS BASE (LOGIN, LOGOUT, HEALTH CHECK)
# ==========================================
@app.route('/health')
def health_check():
    """Ruta solicitada por Coolify para verificar que el contenedor está vivo"""
    return jsonify({"status": "ok", "message": "ManTyre ERP operando al 100%."})

@app.route('/login', methods=['GET', 'POST'])
def login():
    # Si ya está logueado, lo mandamos al Dashboard
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.dashboard'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        empresa_seleccionada = request.form.get('empresa') # Captura 'demotron' o 'mimbral'
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            # Guardamos la empresa elegida en su sesión activa
            user.empresa_activa = empresa_seleccionada
            db.session.commit()
            
            login_user(user)
            return redirect(url_for('dashboard.dashboard'))
        else:
            flash('Credenciales incorrectas. Verifique su usuario y contraseña.')
            
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ==========================================
# ARRANQUE DEL SERVIDOR
# ==========================================
if __name__ == '__main__':
    # Gunicorn tomará el control en Coolify, pero esto sirve para pruebas locales
    app.run(host='0.0.0.0', port=8000, debug=True)
