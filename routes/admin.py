from flask import Blueprint, request, redirect, render_template, abort
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
    """ Función anti-errores para leer celdas de Excel vacías o inexistentes """
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

@admin_bp.route('/admin/cargar_sql_final', methods=['GET', 'POST'], strict_slashes=False)
def cargar_sql_final():
    token_esperado = os.environ.get('ADMIN_TOKEN')
    token_recibido = request.args.get('token') or request.headers.get('X-Admin-Token')
    if not token_esperado or token_recibido != token_esperado:
        return "ACCESO DENEGADO (403): Token de administración inválido o ausente.", 403

    reporte = {"equipos": 0, "lecturas": 0, "preventivas": 0, "correctivas": 0, "compras": 0, "filtros": 0, "repuestos": 0, "mensajes": []}
    
    try:
        db.session.execute(text("DELETE FROM orden_trabajo WHERE id NOT IN (SELECT MIN(id) FROM orden_trabajo GROUP BY codigo_equipo, tipo_ot, lectura)"))
        db.session.commit()

        try:
            db.session.execute(text("ALTER TABLE personal ADD COLUMN equipo_asignado VARCHAR(50) DEFAULT 'Ninguno'"))
            db.session.execute(text("ALTER TABLE orden_trabajo ADD COLUMN mecanico VARCHAR(100) DEFAULT 'Sin Asignar'"))
            db.session.commit()
        except: db.session.rollback()

        db.create_all()

        excel_principal = "https://raw.githubusercontent.com/manuelortizortiz/cmms-demotron/main/CMMS%20DEMOTRON%20MANU%20ORTIZ.xlsx"
        archivo_filtros = "https://raw.githubusercontent.com/manuelortizortiz/cmms-demotron/main/Plantilla_Maestro_Filtros_Demotron.xlsx"

        try:
            req_cmms = urllib.request.Request(excel_principal, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req_cmms) as response:
                xls_prin = pd.ExcelFile(io.BytesIO(response.read()), engine='openpyxl')
        except Exception as e:
            return f"<div style='padding:20px; font-family:Arial;'><h3 style='color:red;'>ERROR: No se pudo conectar a GitHub para leer el CMMS.</h3><p>{str(e)}</p></div>"

        # --- EQUIPOS ---
        try:
            df_eq = pd.read_excel(xls_prin, sheet_name="Equipos", skiprows=2).replace({np.nan: None})
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
            reporte['mensajes'].append(f"CMMS Equipos procesados: {reporte['equipos']}")
        except Exception as e:
            reporte['mensajes'].append(f"Error en Equipos: {str(e)}")

        # --- LECTURAS, PREVENTIVAS, CORRECTIVAS, COMPRAS, REPUESTOS, KITS (Sin cambios) ---
        try:
            df_lec = pd.read_excel(xls_prin, sheet_name="Lecturas", skiprows=2).replace({np.nan: None})
            for idx, row in df_lec.iterrows():
                if len(row) < 4: continue
                cod = clean_string(str(row.iloc[1] or '')).upper()
                if not cod or cod.lower() in ['none', 'nan', '']: continue
                fecha_dt = safe_parse_date(row.iloc[0])
                if not fecha_dt: continue
                eq = Equipo.query.filter_by(codigo=cod).first()
                if eq: hor, kil = (safe_clean_int(row.iloc[2]), 0) if eq.control_base == 'HORAS' else (0, safe_clean_int(row.iloc[3]))
                else: hor, kil = safe_clean_int(row.iloc[2]), safe_clean_int(row.iloc[3])
                lec = HistorialLectura.query.filter_by(codigo_equipo=cod, fecha=fecha_dt).first()
                if lec: lec.horometro, lec.kilometraje = hor, kil
                else: db.session.add(HistorialLectura(fecha=fecha_dt, codigo_equipo=cod, horometro=hor, kilometraje=kil))
            db.session.commit()
        except: pass

        try:
            df_man = pd.read_excel(xls_prin, sheet_name="Mantenciones", skiprows=2).replace({np.nan: None})
            for idx, row in df_man.iterrows():
                cod = clean_string(str(row.get('Codigo', '') or '')).upper()
                if not cod or cod.lower() in ['none', 'nan', '']: continue
                fecha_dt = safe_parse_date(row.get('Fecha'))
                tipo = clean_string(str(row.get('Tipo Mantencion', '') or ''))
                folio = str(row.get('Folio', '')).strip()
                es_pm = clean_string(str(row.get('EsPM', 'No') or 'No')).lower()
                tipo_ot = 'Preventiva' if es_pm in ['sí','si','s','yes','1','true'] else 'Correctiva'
                lectura_val = safe_clean_int(row.get('Lectura'))
                costo_val = safe_clean_float(row.get('Costo Mantencion CLP'))
                mecanico_val = clean_string(str(row.get('Mecanico', row.get('Proveedor', 'Sin Asignar'))))
                if not mecanico_val or mecanico_val.lower() in ['nan', 'none', '']: mecanico_val = 'Sin Asignar'
                ot = OrdenTrabajo.query.filter_by(codigo_equipo=cod, tipo_ot=tipo_ot, lectura=lectura_val).first()
                if ot:
                    ot.tipo_mantencion, ot.costo_mantencion_clp, ot.mecanico = tipo, costo_val, mecanico_val
                    if fecha_dt: ot.fecha = fecha_dt
                else: db.session.add(OrdenTrabajo(fecha=fecha_dt, codigo_equipo=cod, tipo_ot=tipo_ot, tipo_mantencion=tipo, lectura=lectura_val, folio=folio, costo_mantencion_clp=costo_val, estado='Finalizada', mecanico=mecanico_val))
            db.session.commit()
        except: pass

        try:
            df_corr = pd.read_excel(xls_prin, sheet_name="Correctivas", skiprows=2).replace({np.nan: None})
            for idx, row in df_corr.iterrows():
                cod = clean_string(str(row.get('Codigo Equipo', row.get('Codigo', '')) or '')).upper()
                if not cod or cod.lower() in ['none', 'nan', '']: continue
                fecha_dt = safe_parse_date(row.get('Fecha'))
                falla = clean_string(str(row.get('Causa Raiz', row.get('Falla / Averia', row.get('Falla', ''))) or ''))
                costo_val = safe_clean_float(row.get('Costo Mantencion CLP', row.get('Costo CLP', 0.0)))
                lectura_val = safe_clean_int(row.get('Lectura', row.get('Lectura (Odo/Hor)', 0)))
                mecanico_val = clean_string(str(row.get('Mecanico', row.get('Proveedor', 'Sin Asignar'))))
                if not mecanico_val or mecanico_val.lower() in ['nan', 'none', '']: mecanico_val = 'Sin Asignar'
                ot = OrdenTrabajo.query.filter_by(codigo_equipo=cod, tipo_ot='Correctiva', lectura=lectura_val).first()
                if ot:
                    if fecha_dt: ot.fecha = fecha_dt
                    ot.costo_mantencion_clp, ot.tipo_mantencion, ot.causa_raiz, ot.mecanico = costo_val, falla, falla, mecanico_val
                else: db.session.add(OrdenTrabajo(fecha=fecha_dt, codigo_equipo=cod, tipo_ot='Correctiva', tipo_mantencion=falla, lectura=lectura_val, costo_mantencion_clp=costo_val, estado='Finalizada', causa_raiz=falla, mecanico=mecanico_val))
            db.session.commit()
        except Exception as e: pass

        try:
            df_com = pd.read_excel(xls_prin, sheet_name="Compras PM", skiprows=2).replace({np.nan: None})
            ocs = [clean_string(str(r.get('OC', ''))) for _, r in df_com.iterrows() if str(r.get('OC', '')).lower() not in ['none', 'nan', '']]
            if ocs:
                CompraRepuesto.query.filter(CompraRepuesto.oc.in_(set(ocs))).delete(synchronize_session=False)
                db.session.commit()
            for idx, row in df_com.iterrows():
                cod = clean_string(str(row.get('Codigo', '') or '')).upper()
                oc_str = clean_string(str(row.get('OC', '') or ''))
                if not oc_str or oc_str.lower() in ['none','nan']: continue
                db.session.add(CompraRepuesto(fecha=safe_parse_date(row.get('Fecha')), oc=oc_str, codigo_equipo=cod, descripcion=clean_string(str(row.get('Descripcion', '') or '')), costo_pm_clp=safe_clean_float(row.get('Costo PM CLP'))))
            db.session.commit()
        except: pass

        try:
            df_rep = pd.read_excel(xls_prin, sheet_name="Repuestos", skiprows=2).replace({np.nan: None})
            db.session.query(Repuesto).delete()
            for idx, row in df_rep.iterrows():
                cod_oem = clean_string(str(row.iloc[0])).upper() if len(row) > 0 else ''
                if not cod_oem or cod_oem in ['NONE', 'NAN', '']: continue
                nombre = clean_string(str(row.iloc[1])) if len(row) > 1 else ''
                categoria = clean_string(str(row.iloc[2])) if len(row) > 2 else 'General'
                stock = safe_clean_float(row.iloc[3]) if len(row) > 3 else 0.0
                precio = safe_clean_float(row.iloc[4]) if len(row) > 4 else 0.0
                ubicacion = clean_string(str(row.iloc[5])) if len(row) > 5 else 'BODEGA CENTRAL'
                if not ubicacion or ubicacion.upper() in ['NONE', 'NAN', '']: ubicacion = 'BODEGA CENTRAL'
                db.session.add(Repuesto(codigo_oem=cod_oem, nombre=nombre, categoria=categoria, stock_actual=stock, stock_minimo=1.0, precio_promedio=precio, bodega=ubicacion))
            db.session.commit()
        except: pass

        try:
            df_recetas = pd.read_excel(xls_prin, sheet_name="Recetas_Kits", skiprows=2).replace({np.nan: None})
            db.session.query(RecetaModelo).delete()
            for idx, row in df_recetas.iterrows():
                modelo = str(row.iloc[0]).strip() if len(row) > 0 else ''
                sku = clean_string(str(row.iloc[1])).upper() if len(row) > 1 else ''
                cant = safe_clean_float(row.iloc[2]) if len(row) > 2 else 1.0
                if modelo and sku and modelo.lower() not in ['none', 'nan', ''] and sku.lower() not in ['none', 'nan', '']:
                    db.session.add(RecetaModelo(modelo_equipo=modelo, sku_repuesto=sku, cantidad=cant))
            db.session.commit()
        except: pass

        # =========================================================
        # 🚀 MAESTRO DE FILTROS BLINDADO Y CORREGIDO 🚀
        # =========================================================
        try:
            req_filtros = urllib.request.Request(archivo_filtros, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req_filtros) as response:
                df_filtros = pd.read_excel(io.BytesIO(response.read()), engine='openpyxl').replace({np.nan: None})
                
            db.session.query(FiltroEquipo).delete() 
            
            df_filtros.columns = df_filtros.columns.astype(str).str.strip().str.lower()
            
            for idx, row in df_filtros.iterrows():
                c_eq = get_col(row, 0, '').upper()
                
                if not c_eq or c_eq in ['EQUIPO', 'CODIGO EQUIPO', 'CÓDIGO EQUIPO', 'MODELO', 'MAESTRO', 'NONE', 'NAN'] or len(c_eq) < 2:
                    continue
                    
                c_sist = get_col(row, 1, '-')
                # --- SOLUCIÓN DEL ERROR DE TIPO ---
                # Pasamos la cadena de texto a número entero asegurándonos de que si falla, por defecto sea 1
                c_cant = safe_clean_int(get_col(row, 2, '1'), 1) 
                c_fleet = get_col(row, 3, '-')
                c_bald = get_col(row, 4, '-')
                c_orig = get_col(row, 5, '-')
                c_don = get_col(row, 6, '-')
                c_otra = get_col(row, 7, '-')
                
                db.session.add(FiltroEquipo(
                    codigo_equipo=c_eq, 
                    sistema=c_sist, 
                    cant=c_cant, # Ahora sí es un entero válido
                    originales=c_orig, 
                    fleetguard=c_fleet, 
                    donaldson=c_don, 
                    baldwind=c_bald, 
                    otra_alternativa=c_otra
                ))
                reporte['filtros'] += 1
                
            db.session.commit()
            reporte['mensajes'].append(f"ÉXITO: Maestro de Filtros importado con {reporte['filtros']} registros reales.")
        except Exception as e:
            db.session.rollback()
            reporte['mensajes'].append(f"ERROR CRÍTICO LEYENDO FILTROS: {str(e)}")

        # --- ACTUALIZAR MÁRGENES ---
        for eq in Equipo.query.all():
            u_lec = HistorialLectura.query.filter_by(codigo_equipo=eq.codigo).order_by(HistorialLectura.fecha.desc(), HistorialLectura.id.desc()).first()
            if u_lec: eq.lectura_actual = u_lec.horometro if eq.control_base == 'HORAS' else u_lec.kilometraje
            u_pm = OrdenTrabajo.query.filter_by(codigo_equipo=eq.codigo, tipo_ot='Preventiva').order_by(OrdenTrabajo.lectura.desc()).first()
            if u_pm: eq.proxima_pm = u_pm.lectura + eq.frecuencia_base
            else: eq.proxima_pm = (eq.lectura_actual or 0) + eq.frecuencia_base
        db.session.commit()

        # --- LOG AUDITORIA ---
        log = RegistroChatter(modelo_ref='sistema', registro_id='0', autor='Sistema(Token)', accion='auditoria', mensaje="Sincronización Maestra desde GitHub.")
        db.session.add(log)
        db.session.commit()

        # Generar lista de mensajes para diagnóstico
        mensajes_html = "".join([f"<li>{m}</li>" for m in reporte['mensajes']])

        html_report = f"""
        <div style="font-family: Arial, sans-serif; max-w: 600px; margin: 40px auto; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 24px;">
            <h2 style="color: #16a34a; text-align: center;">ACTUALIZADO CON ÉXITO</h2>
            <ul style="list-style: none; padding: 0; font-size: 14px; font-weight: bold;">
                <li style="padding: 10px; border-bottom: 1px solid #e2e8f0; color: #2563EB;">MAESTRO DE FILTROS IMPORTADOS: <b style="float: right;">{reporte['filtros']}</b></li>
            </ul>
            
            <div style="margin-top: 20px; padding: 15px; background: #fef2f2; border: 1px solid #f87171; border-radius: 8px;">
                <h4 style="margin:0 0 10px 0; color: #991b1b;">Diagnóstico del Robot:</h4>
                <ul style="margin:0; padding-left: 20px; color: #7f1d1d; font-size: 12px;">
                    {mensajes_html}
                </ul>
            </div>
            
            <div style='text-align: center; margin-top: 24px;'><a href='/' style='background: #1e293b; color: white; padding: 10px 24px; text-decoration: none; border-radius: 4px;'>VOLVER AL DASHBOARD</a></div>
        </div>
        """
        return html_report

    except Exception as e:
        db.session.rollback()
        return f"<div style='font-family: Arial; padding: 40px; color: red;'><b>FALLO TÉCNICO AL ACTUALIZAR:</b> {str(e)}</div>"
