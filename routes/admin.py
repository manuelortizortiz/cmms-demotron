from flask import Blueprint, request, redirect, render_template
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
from utils.formatters import clean_string, parse_date

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

# =====================================================================
# GESTIÓN DE USUARIOS Y AUDITORÍA GLOBAL
# =====================================================================
@admin_bp.route('/admin/usuarios', methods=['GET', 'POST'])
@login_required
def gestionar_usuarios():
    rol_actual = getattr(current_user, 'role', getattr(current_user, 'rol', 'usuario'))
    if rol_actual not in ['admin', 'gerencia']:
        return "ACCESO DENEGADO: PERMISOS INSUFICIENTES.", 403

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
            
            if not col_pass: return f"ERROR CRÍTICO: No se encontró la columna de contraseña.", 500

            if not email:
                email = f"{username.replace(' ', '').lower()}@demotron.cl"

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
                autor_log = getattr(current_user, col_nombre, getattr(current_user, 'nombre', 'Admin'))
                db.session.add(RegistroChatter(modelo_ref='sistema', registro_id='0', autor=autor_log, accion='auditoria', mensaje=f"CREACIÓN DE ACCESO: Usuario {username} ({role})"))
                db.session.commit()
            return redirect('/admin/usuarios')
            
        except Exception as e:
            db.session.rollback()
            return f"ERROR TÉCNICO AL CREAR USUARIO: {str(e)}", 500
        
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
        nombre_u = getattr(u, col_nombre, 'Desconocido')
        nombre_actual = getattr(current_user, col_nombre, 'Actual')
        if nombre_u != nombre_actual:
            db.session.delete(u)
            db.session.add(RegistroChatter(modelo_ref='sistema', registro_id='0', autor=nombre_actual, accion='auditoria', mensaje=f"REVOCACIÓN DE ACCESO: Se eliminó el usuario {nombre_u}"))
            db.session.commit()
    except Exception: db.session.rollback()
    return redirect('/admin/usuarios')


# =====================================================================
# MOTOR DE IMPORTACIÓN Y LIMPIEZA DE BASE DE DATOS EXCEL
# =====================================================================
@admin_bp.route('/admin/cargar_sql_final', strict_slashes=False)
@login_required
def cargar_sql_final():
    rol_actual = getattr(current_user, 'role', getattr(current_user, 'rol', 'usuario'))
    if rol_actual not in ['admin', 'gerencia']: return "ACCESO DENEGADO", 403

    reporte = {"equipos": 0, "lecturas": 0, "preventivas": 0, "correctivas": 0, "compras": 0, "filtros": 0, "mensajes": []}
    estado_ubicaciones = "NO DETECTADO"
    
    try:
        try:
            db.session.execute(text("ALTER TABLE personal ADD COLUMN equipo_asignado VARCHAR(50) DEFAULT 'Ninguno'"))
            db.session.execute(text("ALTER TABLE orden_trabajo ADD COLUMN mecanico VARCHAR(100) DEFAULT 'Sin Asignar'"))
            db.session.commit()
        except Exception: db.session.rollback()

        try:
            db.session.execute(text("ALTER TABLE orden_trabajo ALTER COLUMN tipo_mantencion TYPE TEXT"))
            db.session.execute(text("ALTER TABLE compra_repuesto ALTER COLUMN descripcion TYPE TEXT"))
            db.session.execute(text("ALTER TABLE historial_lectura ALTER COLUMN observacion TYPE TEXT"))
            db.session.execute(text("ALTER TABLE registro_uso_equipo ALTER COLUMN observacion TYPE TEXT"))
            db.session.commit()
        except Exception: db.session.rollback()

        db.create_all()

        archivos = os.listdir('.')
        excel_principal = next((f for f in archivos if "CMMS" in f.upper() and f.endswith(('.xlsx', '.xls')) and not f.startswith('~$')), None)
        archivo_filtros = next((f for f in archivos if "filtro" in f.lower() and f.endswith(('.xlsx', '.xls', '.csv')) and not f.startswith('~$')), None)
        archivo_detalles = next((f for f in archivos if "detalles" in f.lower() and f.endswith(('.xlsx', '.csv')) and not f.startswith('~$')), None)
        
        # NUEVO: Detector de archivo de Ubicaciones Externo
        archivo_ubicaciones = next((f for f in archivos if "ubicacion" in f.lower() and f.endswith(('.xlsx', '.csv', '.xls')) and not f.startswith('~$')), None)

        if not excel_principal: return "ERROR: NO SE DETECTA ARCHIVO CMMS (.xlsx)."

        # --- EQUIPOS ---
        df_eq = pd.read_excel(excel_principal, engine='openpyxl', sheet_name="Equipos", skiprows=2).replace({np.nan: None})
        df_eq.columns = df_eq.columns.str.strip()
        operadores_set = set()
        for indice, row in df_eq.iterrows():
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
        for indice, row in df_lec.iterrows():
            if len(row) < 4: continue
            raw_cod = str(row.iloc[1] or '')
            if not raw_cod or raw_cod.lower() in ['none', 'nan', '']: continue
            cod = clean_string(raw_cod).upper()
            fecha_dt = parse_date(row.iloc[0])
            eq = Equipo.query.filter_by(codigo=cod).first()
            if eq:
                if eq.control_base == 'HORAS': hor, kil = safe_clean_int(row.iloc[2]), 0
                else: hor, kil = 0, safe_clean_int(row.iloc[3])
            else: hor, kil = safe_clean_int(row.iloc[2]), safe_clean_int(row.iloc[3])

            lecs_existentes = HistorialLectura.query.filter_by(codigo_equipo=cod, fecha=fecha_dt).all()
            if lecs_existentes:
                lec_prin = lecs_existentes[0]
                lec_prin.horometro, lec_prin.kilometraje = hor, kil
                for copia in lecs_existentes[1:]: db.session.delete(copia)
            else:
                db.session.add(HistorialLectura(fecha=fecha_dt, codigo_equipo=cod, horometro=hor, kilometraje=kil, obra_ubicacion='', responsable='', observacion=''))
                reporte['lecturas'] += 1
        db.session.commit()

        # --- PREVENTIVAS ---
        df_man = pd.read_excel(excel_principal, engine='openpyxl', sheet_name="Mantenciones", skiprows=2).replace({np.nan: None})
        df_man.columns = df_man.columns.str.strip()
        for indice, row in df_man.iterrows():
            raw_cod = str(row.get('Codigo', '') or '')
            if not raw_cod or raw_cod.lower() in ['none', 'nan', '']: continue
            cod = clean_string(raw_cod).upper()
            fecha_dt = parse_date(row.get('Fecha'))
            tipo = clean_string(str(row.get('Tipo Mantencion', '') or ''))
            folio_raw = row.get('Folio')
            folio_str = ''
            if folio_raw is not None and str(folio_raw).lower() not in ['none', 'nan', '']:
                try: folio_str = str(int(float(folio_raw)))
                except: folio_str = str(folio_raw).strip()
            es_pm_raw = clean_string(str(row.get('EsPM', 'No') or 'No')).lower()
            tipo_ot = 'Preventiva' if es_pm_raw in ['sí','si','s','yes','1','true'] else 'Correctiva'
            
            ots_existentes = OrdenTrabajo.query.filter_by(codigo_equipo=cod, fecha=fecha_dt, tipo_ot=tipo_ot).all()
            if ots_existentes:
                ot_principal = ots_existentes[0]
                ot_principal.tipo_mantencion = tipo
                ot_principal.lectura = safe_clean_int(row.get('Lectura'))
                ot_principal.costo_mantencion_clp = safe_clean_float(row.get('Costo Mantencion CLP'))
                if folio_str: ot_principal.folio = folio_str
                for copia in ots_existentes[1:]: db.session.delete(copia)
                reporte['preventivas'] += 1
            else:
                db.session.add(OrdenTrabajo(
                    fecha=fecha_dt, codigo_equipo=cod, tipo_ot=tipo_ot, tipo_mantencion=tipo,
                    lectura=safe_clean_int(row.get('Lectura')), es_pm=clean_string(str(row.get('EsPM', '') or '')),
                    folio=folio_str, lugar=clean_string(str(row.get('Lugar', '') or '')),
                    costo_mantencion_clp=safe_clean_float(row.get('Costo Mantencion CLP')),
                    estado=clean_string(str(row.get('Estado', '') or 'Finalizada')) or 'Finalizada', mecanico='Sin Asignar'
                ))
                reporte['preventivas'] += 1
        db.session.commit()

        # --- CORRECTIVAS ---
        try:
            df_corr = pd.read_excel(excel_principal, engine='openpyxl', sheet_name="Correctivas", skiprows=2).replace({np.nan: None})
            df_corr.columns = df_corr.columns.str.strip()  
            for indice, row in df_corr.iterrows():
                raw_cod = str(row.get('Codigo Equipo', '') or '')
                if not raw_cod or raw_cod.lower() in ['none', 'nan', '']: continue
                cod = clean_string(raw_cod).upper()
                fecha_dt = parse_date(row.get('Fecha'))
                falla = clean_string(str(row.get('Falla / Averia', '') or ''))  
                folio_raw = row.get('Folio')
                if folio_raw is not None and str(folio_raw).lower() not in ['none', 'nan', '']:
                    try: f_num = str(int(float(folio_raw)))
                    except: f_num = str(folio_raw).strip()
                    folio_val = f"OT-CR-{f_num}"
                else: folio_val = f"OT-CR-{random.randint(1000,9999)}"
                mecanico_val = clean_string(str(row.get('Mecanico', '') or 'Sin Asignar')) or 'Sin Asignar'
                estado_val = clean_string(str(row.get('Estado', '') or 'Finalizada')) or 'Finalizada'
                lectura_val = safe_clean_int(row.iloc[4]) if len(row) > 4 else 0
                costo_val = safe_clean_float(row.get('Costo CLP', 0.0))
                
                falla_lower = falla.lower()
                if any(x in falla_lower for x in ['motor','aceite','filtro','refrig','radiador','correa']): sistema_val='Motor'
                elif any(x in falla_lower for x in ['hidraulic','manguera','bomba','cilindro','oring','fuga']): sistema_val='Hidráulico'
                elif any(x in falla_lower for x in ['freno','balata','tambor','pastilla']): sistema_val='Frenos'
                elif any(x in falla_lower for x in ['electri','bateria','luces','sensor','cable']): sistema_val='Eléctrico'
                elif any(x in falla_lower for x in ['neumatico','rueda','llanta']): sistema_val='Neumáticos'
                else: sistema_val='Estructura'
                
                ots_existentes = OrdenTrabajo.query.filter_by(codigo_equipo=cod, fecha=fecha_dt, tipo_ot='Correctiva', tipo_mantencion=falla).all()
                if ots_existentes:
                    ot_principal = ots_existentes[0]
                    ot_principal.lectura = lectura_val
                    ot_principal.costo_mantencion_clp = costo_val
                    if folio_val != ot_principal.folio and not ot_principal.folio.startswith('OT-CR-'): ot_principal.folio = folio_val
                    ot_principal.sistema_falla = sistema_val
                    ot_principal.causa_raiz = falla
                    for copia in ots_existentes[1:]: db.session.delete(copia)
                else:
                    db.session.add(OrdenTrabajo(
                        fecha=fecha_dt, codigo_equipo=cod, tipo_ot='Correctiva', tipo_mantencion=falla,
                        lectura=lectura_val, costo_mantencion_clp=costo_val, estado=estado_val, 
                        folio=folio_val, mecanico=mecanico_val, sistema_falla=sistema_val, causa_raiz=falla
                    ))
                reporte['correctivas'] += 1
            db.session.commit()
        except Exception: pass

        # --- COMPRAS PM ---
        try:
            df_com = pd.read_excel(excel_principal, engine='openpyxl', sheet_name="Compras PM", skiprows=2).replace({np.nan: None})
            df_com.columns = df_com.columns.str.strip()
            
            ocs_en_excel = []
            for idx, r in df_com.iterrows():
                o = clean_string(str(r.get('OC', '')))
                if o and o.lower() not in ['none', 'nan']: ocs_en_excel.append(o)
            
            if ocs_en_excel:
                CompraRepuesto.query.filter(CompraRepuesto.oc.in_(set(ocs_en_excel))).delete(synchronize_session=False)
                db.session.commit()

            for indice, row in df_com.iterrows():
                cod = clean_string(str(row.get('Codigo', '') or '')).upper()
                oc_str = clean_string(str(row.get('OC', '') or ''))
                if not oc_str or oc_str.lower() in ['none','nan']: continue
                
                db.session.add(CompraRepuesto(
                    fecha=parse_date(row.get('Fecha')), oc=oc_str, codigo_equipo=cod, 
                    descripcion=clean_string(str(row.get('Descripcion', '') or '')),
                    proveedor=clean_string(str(row.get('Proveedor', '') or '')), 
                    costo_pm_clp=safe_clean_float(row.get('Costo PM CLP')), 
                    estado_oc=clean_string(str(row.get('Estado OC', '') or ''))
                ))
                reporte['compras'] += 1
            db.session.commit()
        except Exception: pass

        # --- FILTROS ---
        if archivo_filtros:
            try:
                db.session.query(FiltroEquipo).delete()
                db.session.commit()
                if archivo_filtros.endswith(('.xlsx', '.xls')):
                    xls_f = pd.ExcelFile(archivo_filtros, engine='openpyxl')
                    df_fil_raw = pd.read_excel(archivo_filtros, engine='openpyxl', sheet_name=xls_f.sheet_names[0], header=None)
                else:
                    try: df_fil_raw = pd.read_csv(archivo_filtros, header=None, sep=None, engine='python', encoding='utf-8-sig')
                    except Exception: df_fil_raw = pd.read_csv(archivo_filtros, header=None, sep=None, engine='python', encoding='latin1')
                
                header_idx = 0
                for i, r in df_fil_raw.iterrows():
                    row_str = " ".join(str(val).lower() for val in r.values)
                    if 'equipo' in row_str or 'cod' in row_str or 'sistem' in row_str or 'fleet' in row_str:
                        header_idx = i; break
                
                if archivo_filtros.endswith(('.xlsx', '.xls')): df_fil = pd.read_excel(archivo_filtros, engine='openpyxl', skiprows=header_idx)
                else:
                    try: df_fil = pd.read_csv(archivo_filtros, skiprows=header_idx, sep=None, engine='python', encoding='utf-8-sig')
                    except Exception: df_fil = pd.read_csv(archivo_filtros, skiprows=header_idx, sep=None, engine='python', encoding='latin1')
                
                df_fil.columns = df_fil.columns.astype(str).str.strip()
                cols = df_fil.columns.tolist()
                cod_c = cols[0] if len(cols) > 0 else None
                sis_c = cols[1] if len(cols) > 1 else None
                can_c = cols[2] if len(cols) > 2 else None
                fg_c  = cols[3] if len(cols) > 3 else None
                bw_c  = cols[4] if len(cols) > 4 else None
                or_c  = cols[5] if len(cols) > 5 else None
                dn_c  = cols[6] if len(cols) > 6 else None
                ot_c  = cols[7] if len(cols) > 7 else None

                for indice, row in df_fil.iterrows():
                    raw_cod = str(row.get(cod_c, '')) if cod_c else ''
                    if not raw_cod or raw_cod.lower() in ['none', 'nan', '-', '']: continue
                    cod = clean_string(raw_cod).upper()
                    sistema_f = clean_string(str(row.get(sis_c, 'GENERAL'))) if sis_c else 'GENERAL'
                    eq = Equipo.query.filter_by(codigo=cod).first()
                    if not eq:
                        eq = Equipo(codigo=cod, tipo_equipo='S/E', estado_base='Operativo', responsable='Sin Asignar', control_base='HORAS')
                        db.session.add(eq)
                        db.session.commit()
                        reporte['equipos'] += 1

                    db.session.add(FiltroEquipo(
                        codigo_equipo=eq.codigo, sistema=sistema_f.upper(), cant=safe_clean_int(row.get(can_c), 1),
                        fleetguard=clean_string(str(row.get(fg_c, '-'))) if fg_c else "-", 
                        baldwind=clean_string(str(row.get(bw_c, '-'))) if bw_c else "-", 
                        originales=clean_string(str(row.get(or_c, '-'))) if or_c else "-", 
                        donaldson=clean_string(str(row.get(dn_c, '-'))) if dn_c else "-", 
                        otra=clean_string(str(row.get(ot_c, '-'))) if ot_c else "-"
                    ))
                    reporte['filtros'] += 1
                db.session.commit()
            except Exception as e: reporte['mensajes'].append(f"ERROR EN FILTROS: {str(e)}")

        # --- IMPORTADOR MASIVO DE UBICACIONES / MAPA ---
        if archivo_ubicaciones:
            try:
                if archivo_ubicaciones.endswith('.xlsx') or archivo_ubicaciones.endswith('.xls'): 
                    df_ubi = pd.read_excel(archivo_ubicaciones, engine='openpyxl')
                else: 
                    df_ubi = pd.read_csv(archivo_ubicaciones)
                
                df_ubi.columns = [str(c).strip().lower() for c in df_ubi.columns]
                
                cod_col = next((c for c in df_ubi.columns if 'cod' in c or 'equipo' in c), None)
                ubi_col = next((c for c in df_ubi.columns if 'ubic' in c or 'ciudad' in c or 'obra' in c), None)

                if cod_col and ubi_col:
                    for indice, row in df_ubi.iterrows():
                        cod = str(row.get(cod_col, '')).strip().upper()
                        ubi = clean_string(str(row.get(ubi_col, '')))
                        if cod and ubi and ubi.lower() != 'none':
                            eq = Equipo.query.filter_by(codigo=cod).first()
                            if eq: eq.ubicacion = ubi
                    db.session.commit()
                    estado_ubicaciones = "ACTUALIZADO CON ÉXITO"
                else:
                    estado_ubicaciones = "ERROR: FALTAN COLUMNAS 'CODIGO' O 'UBICACION'"
            except Exception as e:
                estado_ubicaciones = f"ERROR: {str(e)}"

        for eq in Equipo.query.all():
            u_lec = HistorialLectura.query.filter_by(codigo_equipo=eq.codigo).order_by(HistorialLectura.fecha.desc(), HistorialLectura.id.desc()).first()
            if u_lec: eq.lectura_actual = u_lec.horometro if eq.control_base == 'HORAS' else u_lec.kilometraje
            u_pm = OrdenTrabajo.query.filter_by(codigo_equipo=eq.codigo, tipo_ot='Preventiva', estado='Finalizada').order_by(OrdenTrabajo.fecha.desc()).first()
            if u_pm: eq.proxima_pm = u_pm.lectura + eq.frecuencia_base
            else: eq.proxima_pm = (eq.lectura_actual or 0) + eq.frecuencia_base
        db.session.commit()

        if archivo_detalles:
            try:
                if archivo_detalles.endswith('.xlsx'): df_det = pd.read_excel(archivo_detalles, engine='openpyxl')
                else: df_det = pd.read_csv(archivo_detalles)
                df_det.columns = [str(c).strip() for c in df_det.columns]
                for indice, row in df_det.iterrows():
                    cod = str(row.get('Código', row.get('Codigo', ''))).strip().upper()
                    eq = Equipo.query.filter_by(codigo=cod).first()
                    if eq:
                        eq.patente = clean_string(row.get('Placa', ''))
                        eq.vin = clean_string(row.get('N° Chasis', ''))
                        eq.n_motor = clean_string(row.get('N° Motor', ''))
                db.session.commit()
            except Exception: pass

        UserClass = current_user.__class__
        columnas = UserClass.__table__.columns.keys()
        col_nombre = 'username' if 'username' in columnas else 'nombre'
        nombre_actual = getattr(current_user, col_nombre, getattr(current_user, 'nombre', 'Administrador'))
        
        log = RegistroChatter(modelo_ref='sistema', registro_id='0', autor=nombre_actual, accion='auditoria', mensaje="EJECUTÓ SINCRONIZACIÓN Y PURGA MAESTRA DE DATOS EXCEL.")
        db.session.add(log)
        db.session.commit()

        html_report = f"""
        <div style="font-family: Arial, sans-serif; max-w: 600px; margin: 40px auto; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 24px;">
            <h2 style="color: #16a34a; text-align: center; text-transform: uppercase; letter-spacing: 2px;">SINCRONIZACIÓN EXITOSA</h2>
            <ul style="list-style: none; padding: 0; font-size: 14px; color: #334155; text-transform: uppercase; font-weight: bold;">
                <li style="padding: 10px; border-bottom: 1px solid #e2e8f0;">EQUIPOS: <b style="float: right;">{reporte['equipos']}</b></li>
                <li style="padding: 10px; border-bottom: 1px solid #e2e8f0;">LECTURAS CORREGIDAS: <b style="float: right;">{reporte['lecturas']}</b></li>
                <li style="padding: 10px; border-bottom: 1px solid #e2e8f0;">PREVENTIVAS: <b style="float: right;">{reporte['preventivas']}</b></li>
                <li style="padding: 10px; border-bottom: 1px solid #e2e8f0;">CORRECTIVAS: <b style="float: right;">{reporte['correctivas']}</b></li>
                <li style="padding: 10px; border-bottom: 1px solid #e2e8f0;">REPUESTOS (COMPRAS): <b style="float: right;">{reporte['compras']}</b></li>
                <li style="padding: 10px; border-bottom: 1px solid #e2e8f0;">FILTROS VINCULADOS: <span style="color: #2563eb; float: right;">{reporte['filtros']}</span></li>
                <li style="padding: 10px; border-bottom: 1px solid #e2e8f0; background: #f0fdf4;">MAPAS Y UBICACIONES EXCEL: <span style="color: #16a34a; float: right;">{estado_ubicaciones}</span></li>
            </ul>
            <div style='text-align: center; margin-top: 24px;'><a href='/' style='background: #1e293b; color: white; padding: 10px 24px; text-decoration: none; border-radius: 4px; font-weight: bold; text-transform: uppercase;'>VOLVER AL SISTEMA</a></div>
        </div>
        """
        return html_report

    except Exception as e:
        db.session.rollback()
        return f"<div style='font-family: Arial; padding: 40px; color: red;'><b>FALLO TÉCNICO ESTRUCTURAL:</b> {str(e)}</div>"
