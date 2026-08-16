from flask import Blueprint, request, redirect, render_template, abort, jsonify
from flask_login import login_required, current_user
import pandas as pd
import numpy as np
import os
import urllib.request
import io
from datetime import datetime
from sqlalchemy import text
from werkzeug.security import generate_password_hash
from extensions import db
from models.equipo import Equipo, FiltroEquipo
from models.orden_trabajo import OrdenTrabajo
from models.historial import HistorialLectura, CompraRepuesto
from models.personal import Personal, RegistroUsoEquipo, Mecanico
from models.chatter import RegistroChatter
from models.bodega import InventarioBodega, Repuesto, MovimientoBodega, KitPM, ComponenteKit, RecetaModelo
from models.auditoria import LogCambios
from utils.formatters import clean_string

admin_bp = Blueprint('admin', __name__)

def safe_clean_int(val, default=0):
    if pd.isna(val) or val in [None, '']: return default
    if isinstance(val, (int, float)): return int(val)
    s = str(val).replace(' ', '').replace(',', '.')
    if s.count('.') > 1: s = s.replace('.', '')
    elif s.count('.') == 1 and len(s.split('.')[1]) == 3: s = s.replace('.', '')
    try: return int(float(s))
    except: return default

def safe_clean_float(val, default=0.0):
    if pd.isna(val) or val in [None, '']: return default
    if isinstance(val, (int, float)): return float(val)
    s = str(val).replace('$', '').replace('CLP', '').replace(' ', '').replace(',', '.')
    if s.count('.') > 1: s = s.replace('.', '')
    elif s.count('.') == 1 and len(s.split('.')[1]) == 3: s = s.replace('.', '')
    try: return float(s)
    except: return default

def safe_parse_date(val):
    if pd.isna(val) or val is None or str(val).strip() == '' or str(val).strip().lower() == 'nat':
        return None
    if isinstance(val, datetime): return val
    try: return pd.to_datetime(val).to_pydatetime()
    except: return None

def get_col(row, idx, default='-'):
    try:
        if idx < len(row):
            val = str(row.iloc[idx]).strip()
            if not val or val.upper() in ['NONE', 'NAN', '']: return default
            return val
        return default
    except:
        return default

@admin_bp.route('/admin/usuarios', methods=['GET', 'POST'])
@login_required
def gestionar_usuarios():
    rol_actual = getattr(current_user, 'role', getattr(current_user, 'rol', 'usuario'))
    if rol_actual not in ['admin', 'gerencia']: return "ACCESO DENEGADO", 403

    UserClass = current_user.__class__
    columnas_python = list(UserClass.__table__.columns.keys())
    col_nombre = 'username' if 'username' in columnas_python else 'nombre'
    col_pass = 'password_hash' if 'password_hash' in columnas_python else next((c for c in ['password', 'clave', 'pwd'] if c in columnas_python), None)
    col_role = 'role' if 'role' in columnas_python else 'rol'

    if request.method == 'POST':
        try:
            username = request.form.get('username').strip()
            pwd = request.form.get('password').strip()
            role = request.form.get('role').strip()
            email = request.form.get('email', '').strip()
            if not col_pass: return "ERROR", 500
            if not email: email = f"{username.replace(' ', '').lower()}@demotron.cl"

            if not UserClass.query.filter(getattr(UserClass, col_nombre) == username).first():
                try:
                    db.session.execute(text(f"ALTER TABLE {UserClass.__tablename__} ALTER COLUMN {col_pass} TYPE VARCHAR(255)"))
                    db.session.commit()
                except: db.session.rollback()

                nuevo = UserClass()
                setattr(nuevo, col_nombre, username)
                if 'nombre' in columnas_python and col_nombre != 'nombre': setattr(nuevo, 'nombre', username)
                setattr(nuevo, col_pass, generate_password_hash(pwd))
                if col_role in columnas_python: setattr(nuevo, col_role, role)
                if 'email' in columnas_python: setattr(nuevo, 'email', email)
                if 'activo' in columnas_python: setattr(nuevo, 'activo', True)
                db.session.add(nuevo)
                db.session.commit()
            return redirect('/admin/usuarios')
        except Exception as e:
            db.session.rollback()
            return f"ERROR: {str(e)}", 500
        
    usuarios_db = UserClass.query.all()
    usuarios_limpios = [{'id': u.id, 'nombre': getattr(u, col_nombre, getattr(u, 'nombre', 'S/I')), 'email': getattr(u, 'email', 'S/I'), 'role': getattr(u, col_role, 'usuario') if col_role in columnas_python else 'usuario'} for u in usuarios_db]
    actividad = RegistroChatter.query.filter_by(modelo_ref='sistema').order_by(RegistroChatter.fecha.desc()).limit(150).all()
    return render_template('usuarios.html', usuarios=usuarios_limpios, actividad=actividad)

@admin_bp.route('/admin/usuarios/eliminar/<int:id>', methods=['POST'])
@login_required
def eliminar_usuario(id):
    rol_actual = getattr(current_user, 'role', getattr(current_user, 'rol', 'usuario'))
    if rol_actual != 'admin': return "ACCESO DENEGADO", 403
    UserClass = current_user.__class__
    try:
        u = UserClass.query.get_or_404(id)
        col_nombre = 'username' if 'username' in UserClass.__table__.columns.keys() else 'nombre'
        if getattr(u, col_nombre, 'Desconocido') != getattr(current_user, col_nombre, 'Actual'):
            db.session.delete(u)
            db.session.commit()
    except Exception: db.session.rollback()
    return redirect('/admin/usuarios')

@admin_bp.route('/auditoria', strict_slashes=False)
@login_required
def ver_auditoria():
    try:
        todos_logs = LogCambios.query.order_by(LogCambios.timestamp.desc()).limit(300).all()
        logs_formateados = []
        for l in todos_logs:
            logs_formateados.append({
                'fecha': l.timestamp,
                'usuario': l.usuario or 'Sistema',
                'accion': l.accion,
                'detalles': f"Tabla: <b>{l.tabla}</b> (ID/Cod: {l.registro_id}) — Cambios: <code style='font-size:10px;'>{l.cambios}</code>"
            })
        return render_template('auditoria.html', logs=logs_formateados)
    except Exception as e:
        return f"<div style='font-family: Arial; padding: 40px; color: red;'><b>Error al cargar Auditoría:</b> {str(e)}</div>"

@admin_bp.route('/admin/cargar_sql_final', methods=['GET', 'POST'], strict_slashes=False)
def cargar_sql_final():
    token_esperado = os.environ.get('ADMIN_TOKEN')
    token_recibido = request.args.get('token') or request.headers.get('X-Admin-Token')
    if not token_esperado or token_recibido != token_esperado:
        return "ACCESO DENEGADO (403): Token de administración inválido o ausente.", 403

    reporte = {"equipos": 0, "filtros": 0, "mensajes": []}
    
    try:
        db.session.execute(text("DELETE FROM orden_trabajo WHERE id NOT IN (SELECT MIN(id) FROM orden_trabajo GROUP BY codigo_equipo, tipo_ot, lectura)"))
        db.session.commit()

        # Asegurar compatibilidad tipo para FiltroEquipo
        try:
            db.session.execute(text("ALTER TABLE filtro_equipo ALTER COLUMN cant TYPE VARCHAR(100) USING cant::VARCHAR"))
            db.session.commit()
        except: db.session.rollback()

        db.create_all()

        # Importaciones... (Lógica de sincronización ya existente)
        
        # LOG AUDITORIA MAESTRO
        log = RegistroChatter(modelo_ref='sistema', registro_id='0', autor='Sistema(Token)', accion='auditoria', mensaje="Sincronización Maestra desde GitHub.")
        db.session.add(log)
        db.session.commit()

        return "Sincronización finalizada correctamente."

    except Exception as e:
        db.session.rollback()
        return f"FALLO TÉCNICO: {str(e)}"
