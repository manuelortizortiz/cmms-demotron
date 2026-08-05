from flask import Blueprint, request, redirect, render_template, abort
from flask_login import login_required, current_user
import pandas as pd
import numpy as np
import os
import random
from datetime import datetime
from sqlalchemy import text
from werkzeug.security import generate_password_hash
from extensions import db
from models.equipo import Equipo, FiltroEquipo
from models.orden_trabajo import OrdenTrabajo
from models.historial import HistorialLectura, CompraRepuesto
from models.personal import Personal, RegistroUsoEquipo, Mecanico
from models.chatter import RegistroChatter
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

# =====================================================================
# GESTIÓN DE USUARIOS Y AUDITORÍA GLOBAL
# =====================================================================
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

# =====================================================================
# MOTOR DE IMPORTACIÓN MASIVA Y PURGA DE DUPLICADOS (PROTEGIDO POR TOKEN)
# =====================================================================
@admin_bp.route('/admin/cargar_sql_final', methods=['GET', 'POST'], strict_slashes=False)
def cargar_sql_final():
    token_esperado = os.environ.get('ADMIN_TOKEN')
    token_recibido = request.args.get('token') or request.headers.get('X-Admin-Token')
    if not token_esperado or token_recibido != token_esperado:
        return "ACCESO DENEGADO (403): Token de administración inválido o ausente.", 403

    reporte = {"equipos": 0, "lecturas": 0, "preventivas": 0, "correctivas": 0, "compras": 0, "filtros": 0, "mensajes": []}
    
    try:
        db.session.execute(text("DELETE FROM orden_trabajo WHERE id NOT IN (SELECT MIN(id) FROM orden_trabajo GROUP BY codigo_equipo, tipo_ot, lectura)"))
        db.session.commit()

        try:
            db.session.execute(text("ALTER TABLE personal ADD COLUMN equipo_asignado VARCHAR(50) DEFAULT 'Ninguno'"))
            db.session.execute(text("ALTER TABLE orden_trabajo ADD COLUMN mecanico VARCHAR(100) DEFAULT 'Sin Asignar'"))
            db.session.commit()
        except: db.session.rollback()

        db.create_all()

        archivos = os.listdir('.')
        excel_principal = next((f for f in archivos if "CMMS" in f.upper() and f.endswith(('.xlsx', '.xls')) and not f.startswith('~$')), None)
        archivo_filtros = next((f for f in archivos if "filtro" in f.lower() and f.endswith(('.xlsx', '.xls', '.csv')) and not f.startswith('~$')), None)
        archivo_ubicaciones = next((f for f in archivos if "ubicacion" in f.lower() and f.endswith(('.xlsx', '.csv', '.xls')) and not f.startswith('~$')), None)

        if not excel_principal: return "ERROR: NO SE DETECTA ARCHIVO CMMS (.xlsx)."

        # --- EQUIPOS ---
        df_eq = pd.read_excel(excel_principal, engine='openpyxl', sheet_name="Equipos", skiprows=2).replace({np.nan: None})
        operadores_set = set()
        for idx, row in df_eq.iterrows():
            raw_cod = str(row.get('Codigo', '') or '')
            if not raw_cod or raw_cod.lower() in ['none', 'nan', '']: continue
            cod = clean_string(raw_cod).upper()
            responsable = clean_string(str(row.get('Responsable', '') or 'Sin Asignar'))
            if responsable and responsable.lower() not in ['none','nan']: operadores_set.add(responsable)
            eq = Equipo.query.filter_by(codigo=cod).first()
            if not eq:
                eq = Equipo(codigo=cod)
                db.session.add(eq)
            eq.tipo_equipo = clean_string(str(row.get('Tipo Equipo', '') or ''))
            eq.marca = clean_string(str(row.get('Marca', '') or ''))
            eq.modelo = clean_string(str(row.get('Modelo', '') or ''))
            eq.ubicacion = clean_string(str(row.get('Ubicacion', '') or ''))
            eq.responsable = responsable
            eq.estado_base = clean_string(str(row.get('Estado Base', '') or 'Operativo')) or 'Operativo'
            eq.control_base = clean_string(str(row.get('Control Base', '') or 'HORAS')) or 'HORAS'
            eq.frecuencia_base = safe_clean_int(row.get('Frecuencia Base'), 250)
            reporte['equipos'] += 1
            
        for op in operadores_set:
            if not Personal.query.filter_by(nombre=op).first(): db.session.add(Personal(nombre=op, cargo="Operador", estado="Activo", equipo_asignado="Varios"))
        db.session.commit()

        # --- LECTURAS ---
        df_lec = pd.read_excel(excel_principal, engine='openpyxl', sheet_name="Lecturas", skiprows=2).replace({np.nan: None})
        for idx, row in df_lec.iterrows():
            if len(row) < 4: continue
            cod = clean_string(str(row.iloc[1] or '')).upper()
            if not cod or cod.lower() in ['none', 'nan', '']: continue
            fecha_dt = safe_parse_date(row.iloc[0])
            if not fecha_dt: continue
            
            eq = Equipo.query.filter_by(codigo=cod).first()
            if eq:
                hor, kil = (safe_clean_int(row.iloc[2]), 0) if eq.control_base == 'HORAS' else (0, safe_clean_int(row.iloc[3]))
            else: hor, kil = safe_clean_int(row.iloc[2]), safe_clean_int(row.iloc[3])

            lec = HistorialLectura.query.filter_by(codigo_equipo=cod, fecha=fecha_dt).first()
            if lec: lec.horometro, lec.kilometraje = hor, kil
            else:
                db.session.add(HistorialLectura(fecha=fecha_dt, codigo_equipo=cod, horometro=hor, kilometraje=kil))
                reporte['lecturas'] += 1
        db.session.commit()

        # --- PREVENTIVAS (AQUÍ ESTABA EL ERROR DEL MECÁNICO EN DURO) ---
        df_man = pd.read_excel(excel_principal, engine='openpyxl', sheet_name="Mantenciones", skiprows=2).replace({np.nan: None})
        for idx, row in df_man.iterrows():
            cod = clean_string(str(row.get('Codigo', '') or '')).upper()
            if not cod or cod.lower() in ['none', 'nan', '']: continue
            fecha_dt = safe_parse_date(row.get('Fecha'))
            tipo = clean_string(str(row.get('Tipo Mantencion', '') or ''))
            folio = str(row.get('Folio', '')).strip()
            if folio.lower() in ['none', 'nan']: folio = ''
            es_pm = clean_string(str(row.get('EsPM', 'No') or 'No')).lower()
            tipo_ot = 'Preventiva' if es_pm in ['sí','si','s','yes','1','true'] else 'Correctiva'
            lectura_val = safe_clean_int(row.get('Lectura'))
            costo_val = safe_clean_float(row.get('Costo Mantencion CLP'))
            
            # MAGIA: Ahora lee la columna "Mecanico" o "Proveedor" del Excel y no lo fuerza a "Sin Asignar"
            mecanico_val = clean_string(str(row.get('Mecanico', row.get('Proveedor', 'Sin Asignar'))))
            if not mecanico_val or mecanico_val.lower() in ['nan', 'none', '']: mecanico_val = 'Sin Asignar'

            ot = OrdenTrabajo.query.filter_by(codigo_equipo=cod, tipo_ot=tipo_ot, lectura=lectura_val).first()
            if ot:
                ot.tipo_mantencion, ot.costo_mantencion_clp = tipo, costo_val
                ot.mecanico = mecanico_val
                if fecha_dt: ot.fecha = fecha_dt
            else:
                db.session.add(OrdenTrabajo(fecha=fecha_dt, codigo_equipo=cod, tipo_ot=tipo_ot, tipo_mantencion=tipo, lectura=lectura_val, folio=folio, costo_mantencion_clp=costo_val, estado='Finalizada', mecanico=mecanico_val))
                reporte['preventivas'] += 1
        db.session.commit()

        # --- CORRECTIVAS (AQUÍ ESTABA LA CEGUERA DE COLUMNAS) ---
        try:
            df_corr = pd.read_excel(excel_principal, engine='openpyxl', sheet_name="Correctivas", skiprows=2).replace({np.nan: None})
            for idx, row in df_corr.iterrows():
                cod = clean_string(str(row.get('Codigo Equipo', row.get('Codigo', '')) or '')).upper()
                if not cod or cod.lower() in ['none', 'nan', '']: continue
                fecha_dt = safe_parse_date(row.get('Fecha'))
                
                # MAGIA: Ahora busca la falla se llame como se llame en tu Excel
                falla = clean_string(str(row.get('Causa Raiz', row.get('Falla / Averia', row.get('Falla', ''))) or ''))
                
                # MAGIA: Atrapa el costo
                costo_val = safe_clean_float(row.get('Costo Mantencion CLP', row.get('Costo CLP', 0.0)))
                
                # MAGIA: Atrapa la lectura y al mecánico
                lectura_val = safe_clean_int(row.get('Lectura', row.get('Lectura (Odo/Hor)', 0)))
                if lectura_val == 0 and len(row) > 4:
                    try: lectura_val = safe_clean_int(row.iloc[4])
                    except: pass

                mecanico_val = clean_string(str(row.get('Mecanico', row.get('Proveedor', 'Sin Asignar'))))
                if not mecanico_val or mecanico_val.lower() in ['nan', 'none', '']: mecanico_val = 'Sin Asignar'

                ot = OrdenTrabajo.query.filter_by(codigo_equipo=cod, tipo_ot='Correctiva', lectura=lectura_val).first()
                if ot:
                    if fecha_dt: ot.fecha = fecha_dt
                    ot.costo_mantencion_clp = costo_val
                    ot.tipo_mantencion = falla
                    ot.causa_raiz = falla
                    ot.mecanico = mecanico_val
                else:
                    db.session.add(OrdenTrabajo(fecha=fecha_dt, codigo_equipo=cod, tipo_ot='Correctiva', tipo_mantencion=falla, lectura=lectura_val, costo_mantencion_clp=costo_val, estado='Finalizada', causa_raiz=falla, mecanico=mecanico_val))
                    reporte['correctivas'] += 1
            db.session.commit()
        except Exception as e: 
            reporte['mensajes'].append(f"ADVERTENCIA EN CORRECTIVAS: {str(e)}")

        # --- COMPRAS PM ---
        try:
            df_com = pd.read_excel(excel_principal, engine='openpyxl', sheet_name="Compras PM", skiprows=2).replace({np.nan: None})
            ocs = [clean_string(str(r.get('OC', ''))) for _, r in df_com.iterrows() if str(r.get('OC', '')).lower() not in ['none', 'nan', '']]
            if ocs:
                CompraRepuesto.query.filter(CompraRepuesto.oc.in_(set(ocs))).delete(synchronize_session=False)
                db.session.commit()

            for idx, row in df_com.iterrows():
                cod = clean_string(str(row.get('Codigo', '') or '')).upper()
                oc_str = clean_string(str(row.get('OC', '') or ''))
                if not oc_str or oc_str.lower() in ['none','nan']: continue
                db.session.add(CompraRepuesto(fecha=safe_parse_date(row.get('Fecha')), oc=oc_str, codigo_equipo=cod, descripcion=clean_string(str(row.get('Descripcion', '') or '')), costo_pm_clp=safe_clean_float(row.get('Costo PM CLP'))))
                reporte['compras'] += 1
            db.session.commit()
        except: pass

        # --- FILTROS ---
        if archivo_filtros:
            try:
                db.session.query(FiltroEquipo).delete()
                db.session.commit()
                if archivo_filtros.endswith(('.xlsx', '.xls')): df_fil_raw = pd.read_excel(archivo_filtros, engine='openpyxl', header=None)
                else: df_fil_raw = pd.read_csv(archivo_filtros, header=None, sep=None, engine='python')
                
                header_idx = next((i for i, r in df_fil_raw.iterrows() if 'cod' in " ".join(str(val).lower() for val in r.values) or 'sistem' in " ".join(str(val).lower() for val in r.values)), 0)
                df_fil = pd.read_excel(archivo_filtros, engine='openpyxl', skiprows=header_idx) if archivo_filtros.endswith(('.xlsx', '.xls')) else pd.read_csv(archivo_filtros, skiprows=header_idx, sep=None, engine='python')
                
                df_fil.columns = df_fil.columns.astype(str).str.strip()
                cols = df_fil.columns.tolist()
                for idx, row in df_fil.iterrows():
                    cod = clean_string(str(row.get(cols[0], ''))).upper() if len(cols)>0 else ''
                    if not cod or cod.lower() in ['none', 'nan', '-', '']: continue
                    eq = Equipo.query.filter_by(codigo=cod).first()
                    if not eq:
                        eq = Equipo(codigo=cod, estado_base='Operativo')
                        db.session.add(eq)
                        db.session.commit()
                        reporte['equipos'] += 1

                    db.session.add(FiltroEquipo(codigo_equipo=eq.codigo, sistema=clean_string(str(row.get(cols[1], 'GENERAL'))) if len(cols)>1 else 'GENERAL', cant=safe_clean_int(row.get(cols[2]), 1) if len(cols)>2 else 1, fleetguard=clean_string(str(row.get(cols[3], '-'))) if len(cols)>3 else "-", baldwind=clean_string(str(row.get(cols[4], '-'))) if len(cols)>4 else "-", originales=clean_string(str(row.get(cols[5], '-'))) if len(cols)>5 else "-", donaldson=clean_string(str(row.get(cols[6], '-'))) if len(cols)>6 else "-", otra=clean_string(str(row.get(cols[7], '-'))) if len(cols)>7 else "-"))
                    reporte['filtros'] += 1
                db.session.commit()
            except Exception as e: reporte['mensajes'].append(f"ERROR FILTROS: {str(e)}")

        # --- ACTUALIZAR MÁRGENES ---
        for eq in Equipo.query.all():
            u_lec = HistorialLectura.query.filter_by(codigo_equipo=eq.codigo).order_by(HistorialLectura.fecha.desc(), HistorialLectura.id.desc()).first()
            if u_lec: eq.lectura_actual = u_lec.horometro if eq.control_base == 'HORAS' else u_lec.kilometraje
            u_pm = OrdenTrabajo.query.filter_by(codigo_equipo=eq.codigo, tipo_ot='Preventiva').order_by(OrdenTrabajo.lectura.desc()).first()
            if u_pm: eq.proxima_pm = u_pm.lectura + eq.frecuencia_base
            else: eq.proxima_pm = (eq.lectura_actual or 0) + eq.frecuencia_base
        db.session.commit()

        # --- LOG AUDITORIA ---
        log = RegistroChatter(modelo_ref='sistema', registro_id='0', autor='Sistema(Token)', accion='auditoria', mensaje="EJECUTÓ SINCRONIZACIÓN Y PURGA MAESTRA VÍA TOKEN DE SEGURIDAD.")
        db.session.add(log)
        db.session.commit()

        html_report = f"""
        <div style="font-family: Arial, sans-serif; max-w: 600px; margin: 40px auto; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 24px;">
            <h2 style="color: #16a34a; text-align: center; text-transform: uppercase; letter-spacing: 2px;">SISTEMA LIMPIADO Y ACTUALIZADO</h2>
            <ul style="list-style: none; padding: 0; font-size: 14px; color: #334155; text-transform: uppercase; font-weight: bold;">
                <li style="padding: 10px; border-bottom: 1px solid #e2e8f0;">EQUIPOS: <b style="float: right;">{reporte['equipos']}</b></li>
                <li style="padding: 10px; border-bottom: 1px solid #e2e8f0;">PREVENTIVAS ACTUALIZADAS: <b style="float: right;">{reporte['preventivas']}</b></li>
                <li style="padding: 10px; border-bottom: 1px solid #e2e8f0;">CORRECTIVAS ACTUALIZADAS: <b style="float: right;">{reporte['correctivas']}</b></li>
                <li style="padding: 10px; border-bottom: 1px solid #e2e8f0;">COMPRAS: <b style="float: right;">{reporte['compras']}</b></li>
            </ul>
            <div style='text-align: center; margin-top: 24px;'><a href='/' style='background: #1e293b; color: white; padding: 10px 24px; text-decoration: none; border-radius: 4px; font-weight: bold; text-transform: uppercase;'>VOLVER AL DASHBOARD</a></div>
        </div>
        """
        return html_report

    except Exception as e:
        db.session.rollback()
        return f"<div style='font-family: Arial; padding: 40px; color: red;'><b>FALLO TÉCNICO:</b> {str(e)}</div>"
