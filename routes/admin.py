from flask import Blueprint, send_file
import os
import random
import pandas as pd
import numpy as np
from sqlalchemy import text
from flask_login import login_required
from utils.auth import role_required
from extensions import db
from models.equipo import Equipo, FiltroEquipo
from models.orden_trabajo import OrdenTrabajo
from models.historial import HistorialLectura, CompraRepuesto
from models.personal import Personal, RegistroUsoEquipo, Mecanico
from utils.formatters import clean_string, clean_int, clean_float, parse_date

admin_bp = Blueprint('admin', __name__)

@admin_bp.route('/admin/cargar_sql_final', strict_slashes=False)
@login_required
@role_required('admin', 'gerencia')
def cargar_sql_final():
    reporte = {
        "equipos": 0, "lecturas": 0, "preventivas": 0, 
        "correctivas": 0, "compras": 0, "filtros": 0, "mensajes": []
    }
    
    try:
        try:
            db.session.execute(text("ALTER TABLE personal ADD COLUMN equipo_asignado VARCHAR(50) DEFAULT 'Ninguno'"))
            db.session.execute(text("ALTER TABLE orden_trabajo ADD COLUMN mecanico VARCHAR(100) DEFAULT 'Sin Asignar'"))
            db.session.commit()
        except Exception: 
            db.session.rollback()

        try:
            db.session.execute(text("ALTER TABLE orden_trabajo ALTER COLUMN tipo_mantencion TYPE TEXT"))
            db.session.execute(text("ALTER TABLE compra_repuesto ALTER COLUMN descripcion TYPE TEXT"))
            db.session.execute(text("ALTER TABLE historial_lectura ALTER COLUMN observacion TYPE TEXT"))
            db.session.execute(text("ALTER TABLE registro_uso_equipo ALTER COLUMN observacion TYPE TEXT"))
            db.session.commit()
        except Exception: 
            db.session.rollback()

        db.create_all()

        archivos = os.listdir('.')
        excel_principal = next((f for f in archivos if "CMMS" in f.upper() and f.endswith(('.xlsx', '.xls')) and not f.startswith('~$')), None)
        # Se asegura de leer el archivo de filtros detectando su nombre específico o extensión csv/xlsx
        archivo_filtros = next((f for f in archivos if "filtro" in f.lower() and f.endswith(('.xlsx', '.xls', '.csv')) and not f.startswith('~$')), None)
        archivo_detalles = next((f for f in archivos if "detalles" in f.lower() and f.endswith(('.xlsx', '.csv')) and not f.startswith('~$')), None)

        if not excel_principal: 
            return "Error: Falta el archivo principal CMMS DEMOTRON (.xlsx)."

        # --- 1. HOJA EQUIPOS ---
        df_eq = pd.read_excel(excel_principal, engine='openpyxl', sheet_name="Equipos", skiprows=2).replace({np.nan: None})
        df_eq.columns = df_eq.columns.str.strip()
        operadores_set = set()
        for indice, row in df_eq.iterrows():
            raw_cod = str(row.get('Codigo', '') or '')
            if not raw_cod or raw_cod.lower() in ['none', 'nan', '']: continue
            cod = clean_string(raw_cod).upper()
            
            responsable = clean_string(str(row.get('Responsable', '') or 'Sin Asignar'))
            if responsable and responsable.lower() not in ['none','nan']: 
                operadores_set.add(responsable)
            
            eq = Equipo.query.filter_by(codigo=cod).first()
            if not eq:
                eq = Equipo(codigo=cod)
                db.session.add(eq)
            
            eq.tipo_equipo     = clean_string(str(row.get('Tipo Equipo', '') or ''))
            eq.marca           = clean_string(str(row.get('Marca', '') or ''))
            eq.modelo          = clean_string(str(row.get('Modelo', '') or ''))
            eq.ubicacion       = clean_string(str(row.get('Ubicacion', '') or ''))
            eq.responsable     = responsable
            eq.estado_base     = clean_string(str(row.get('Estado Base', '') or 'Operativo')) or 'Operativo'
            eq.control_base    = clean_string(str(row.get('Control Base', '') or 'HORAS')) or 'HORAS'
            eq.frecuencia_base = clean_int(row.get('Frecuencia Base'), 250)
            reporte['equipos'] += 1
            
        for op in operadores_set:
            if not Personal.query.filter_by(nombre=op).first():
                db.session.add(Personal(nombre=op, cargo="Operador", estado="Activo", equipo_asignado="Varios"))
        db.session.commit()

        # --- 2. HOJA LECTURAS ---
        df_lec = pd.read_excel(excel_principal, engine='openpyxl', sheet_name="Lecturas", skiprows=2).replace({np.nan: None})
        for indice, row in df_lec.iterrows():
            if len(row) < 4: continue
            raw_cod = str(row.iloc[1] or '')
            if not raw_cod or raw_cod.lower() in ['none', 'nan', '']: continue
            cod = clean_string(raw_cod).upper()
            
            fecha_dt = parse_date(row.iloc[0])
            eq = Equipo.query.filter_by(codigo=cod).first()
            
            if eq:
                if eq.control_base == 'HORAS':
                    hor, kil = clean_int(row.iloc[2], 0), 0
                else:
                    hor, kil = 0, clean_int(row.iloc[3], 0)
            else:
                hor, kil = clean_int(row.iloc[2], 0), clean_int(row.iloc[3], 0)

            if not HistorialLectura.query.filter_by(codigo_equipo=cod, fecha=fecha_dt, horometro=hor, kilometraje=kil).first():
                db.session.add(HistorialLectura(fecha=fecha_dt, codigo_equipo=cod, horometro=hor, kilometraje=kil, obra_ubicacion='', responsable='', observacion=''))
                reporte['lecturas'] += 1
        db.session.commit()

        # --- 3. HOJA MANTENCIONES (PREVENTIVAS) ---
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
            
            ot_existente = OrdenTrabajo.query.filter_by(codigo_equipo=cod, fecha=fecha_dt, tipo_mantencion=tipo).first()
            if ot_existente:
                ot_existente.lectura = clean_int(row.get('Lectura'), 0)
                ot_existente.costo_mantencion_clp = clean_float(row.get('Costo Mantencion CLP'), 0.0)
                ot_existente.folio = folio_str
            else:
                db.session.add(OrdenTrabajo(
                    fecha=fecha_dt, codigo_equipo=cod, tipo_ot=tipo_ot, tipo_mantencion=tipo,
                    lectura=clean_int(row.get('Lectura'), 0), es_pm=clean_string(str(row.get('EsPM', '') or '')),
                    folio=folio_str, lugar=clean_string(str(row.get('Lugar', '') or '')),
                    costo_mantencion_clp=clean_float(row.get('Costo Mantencion CLP'), 0.0),
                    estado=clean_string(str(row.get('Estado', '') or 'Finalizada')) or 'Finalizada', mecanico='Sin Asignar'
                ))
            reporte['preventivas'] += 1
        db.session.commit()

        # --- 4. HOJA CORRECTIVAS ---
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
                else: 
                    folio_val = f"OT-CR-{random.randint(1000,9999)}"
                
                mecanico_val = clean_string(str(row.get('Mecanico', '') or 'Sin Asignar')) or 'Sin Asignar'
                estado_val = clean_string(str(row.get('Estado', '') or 'Finalizada')) or 'Finalizada'
                lectura_val = clean_int(row.iloc[4], 0) if len(row) > 4 else 0
                costo_val = 0.0
                
                falla_lower = falla.lower()
                if any(x in falla_lower for x in ['motor','aceite','filtro','refrig','radiador','correa']): sistema_val='Motor'
                elif any(x in falla_lower for x in ['hidraulic','manguera','bomba','cilindro','oring','fuga']): sistema_val='Hidráulico'
                elif any(x in falla_lower for x in ['freno','balata','tambor','pastilla']): sistema_val='Frenos'
                elif any(x in falla_lower for x in ['electri','bateria','luces','sensor','cable']): sistema_val='Eléctrico'
                elif any(x in falla_lower for x in ['neumatico','rueda','llanta']): sistema_val='Neumáticos'
                else: sistema_val='Estructura'
                
                ot_existente = OrdenTrabajo.query.filter_by(codigo_equipo=cod, fecha=fecha_dt, tipo_mantencion=falla).first()
                if ot_existente:
                    ot_existente.lectura = lectura_val
                    ot_existente.costo_mantencion_clp = costo_val
                    ot_existente.folio = folio_val
                    ot_existente.sistema_falla = sistema_val
                else:
                    db.session.add(OrdenTrabajo(
                        fecha=fecha_dt, codigo_equipo=cod, tipo_ot='Correctiva', tipo_mantencion=falla,
                        lectura=lectura_val, costo_mantencion_clp=costo_val, estado=estado_val, 
                        folio=folio_val, mecanico=mecanico_val, sistema_falla=sistema_val, causa_raiz=falla
                    ))
                reporte['correctivas'] += 1
            db.session.commit()
        except Exception as e: 
            pass

        # --- 5. COMPRAS PM ---
        try:
            df_com = pd.read_excel(excel_principal, engine='openpyxl', sheet_name="Compras PM", skiprows=2).replace({np.nan: None})
            df_com.columns = df_com.columns.str.strip()
            for indice, row in df_com.iterrows():
                cod = clean_string(str(row.get('Codigo', '') or '')).upper()
                oc_str = clean_string(str(row.get('OC', '') or ''))
                if not oc_str or oc_str.lower() in ['none','nan']: continue
                fecha_dt = parse_date(row.get('Fecha'))
                if not CompraRepuesto.query.filter_by(codigo_equipo=cod, oc=oc_str).first():
                    db.session.add(CompraRepuesto(
                        fecha=fecha_dt, oc=oc_str, codigo_equipo=cod,
                        descripcion=clean_string(str(row.get('Descripcion', '') or '')),
                        proveedor=clean_string(str(row.get('Proveedor', '') or '')),
                        costo_pm_clp=clean_float(row.get('Costo PM CLP'), 0.0), estado_oc=clean_string(str(row.get('Estado OC', '') or ''))
                    ))
            db.session.commit()
        except Exception as e: pass

        # --- 6. SUPER IMPORTADOR DE FILTROS (BULLETPROOF CSV) ---
        if archivo_filtros:
            reporte['mensajes'].append(f"🔍 Archivo de filtros encontrado: {archivo_filtros}")
            try:
                # Sistema de lectura forzada con detección automática de separador
                if archivo_filtros.endswith(('.xlsx', '.xls')):
                    xls_f = pd.ExcelFile(archivo_filtros, engine='openpyxl')
                    df_fil_raw = pd.read_excel(archivo_filtros, engine='openpyxl', sheet_name=xls_f.sheet_names[0], header=None)
                else:
                    try:
                        df_fil_raw = pd.read_csv(archivo_filtros, header=None, sep=None, engine='python', encoding='utf-8-sig')
                    except Exception:
                        df_fil_raw = pd.read_csv(archivo_filtros, header=None, sep=None, engine='python', encoding='latin1')
                
                header_idx = 0
                for i, r in df_fil_raw.iterrows():
                    row_str = " ".join(str(val).lower() for val in r.values)
                    if 'equipo' in row_str or 'cod' in row_str or 'sistem' in row_str or 'fleet' in row_str:
                        header_idx = i
                        break
                
                if archivo_filtros.endswith(('.xlsx', '.xls')):
                    df_fil = pd.read_excel(archivo_filtros, engine='openpyxl', skiprows=header_idx)
                else:
                    try:
                        df_fil = pd.read_csv(archivo_filtros, skiprows=header_idx, sep=None, engine='python', encoding='utf-8-sig')
                    except Exception:
                        df_fil = pd.read_csv(archivo_filtros, skiprows=header_idx, sep=None, engine='python', encoding='latin1')
                
                # Obtención pura de columnas por posición si fallan los nombres
                df_fil = df_fil.replace({np.nan: "-"})
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
                    sistema_f = sistema_f.upper()
                    
                    eq = Equipo.query.filter_by(codigo=cod).first()
                    # Si el equipo de la lista de filtros NO existe, ¡LO CREAMOS!
                    if not eq:
                        eq = Equipo(codigo=cod, tipo_equipo='S/E', estado_base='Operativo', responsable='Sin Asignar', control_base='HORAS')
                        db.session.add(eq)
                        db.session.commit()
                        reporte['mensajes'].append(f"⚠️ Equipo '{cod}' auto-creado en la base de datos para no perder su filtro.")
                        reporte['equipos'] += 1

                    cant_val = clean_int(row.get(can_c), 1) if can_c else 1
                    fg_val = clean_string(str(row.get(fg_c, '-'))) if fg_c else "-"
                    bw_val = clean_string(str(row.get(bw_c, '-'))) if bw_c else "-"
                    or_val = clean_string(str(row.get(or_c, '-'))) if or_c else "-"
                    dn_val = clean_string(str(row.get(dn_c, '-'))) if dn_c else "-"
                    ot_val = clean_string(str(row.get(ot_c, '-'))) if ot_c else "-"

                    fil_existente = FiltroEquipo.query.filter_by(codigo_equipo=eq.codigo, sistema=sistema_f).first()
                    if fil_existente:
                        # MODO UPSERT: Sobreescribe los códigos viejos obligatoriamente
                        fil_existente.cant = cant_val
                        fil_existente.fleetguard = fg_val
                        fil_existente.baldwind = bw_val
                        fil_existente.originales = or_val
                        fil_existente.donaldson = dn_val
                        fil_existente.otra = ot_val
                    else:
                        db.session.add(FiltroEquipo(
                            codigo_equipo=eq.codigo, sistema=sistema_f, cant=cant_val,
                            fleetguard=fg_val, baldwind=bw_val, originales=or_val, donaldson=dn_val, otra=ot_val
                        ))
                    reporte['filtros'] += 1
                db.session.commit()
            except Exception as e:
                reporte['mensajes'].append(f"❌ Error interno procesando Filtros: {str(e)}")
        else:
            reporte['mensajes'].append("⚠️ No se encontró el archivo de filtros en la carpeta.")

        # PROYECCIONES FINALES
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
            except Exception as e: pass

        # DIAGNÓSTICO EN PANTALLA
        html_report = f"""
        <div style="font-family: Arial, sans-serif; max-w: 600px; margin: 40px auto; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 24px; box-shadow: 0 4px 6px rgba(0,0,0,0.05);">
            <h2 style="color: #16a34a; text-align: center; margin-bottom: 20px;">✅ Sincronización Realizada</h2>
            <ul style="list-style: none; padding: 0; font-size: 14px; color: #334155;">
                <li style="padding: 10px; border-bottom: 1px solid #e2e8f0;">🚜 Equipos en Sistema: <b>{reporte['equipos']}</b></li>
                <li style="padding: 10px; border-bottom: 1px solid #e2e8f0;">📅 Historial de Lecturas: <b>{reporte['lecturas']}</b></li>
                <li style="padding: 10px; border-bottom: 1px solid #e2e8f0;">🔧 Preventivas (PM): <b>{reporte['preventivas']}</b></li>
                <li style="padding: 10px; border-bottom: 1px solid #e2e8f0;">🚨 Correctivas registradas: <b>{reporte['correctivas']}</b></li>
                <li style="padding: 10px; border-bottom: 1px solid #e2e8f0; background: #eff6ff;">📦 <b>Filtros Vinculados a Equipos: <span style="color: #2563eb; font-size: 16px;">{reporte['filtros']}</span></b></li>
            </ul>
        """
        if reporte['mensajes']:
            html_report += f"<div style='background: #fee2e2; color: #991b1b; padding: 12px; border-radius: 8px; margin-top: 16px; font-size: 11px;'>{'<br>'.join(reporte['mensajes'])}</div>"
            
        html_report += "<div style='text-align: center; margin-top: 24px;'><a href='/' style='background: #2563eb; color: white; padding: 10px 24px; text-decoration: none; border-radius: 8px; font-weight: bold;'>Ir al Dashboard</a></div></div>"
        
        return html_report

    except Exception as e:
        db.session.rollback()
        return f"<div style='font-family: Arial; padding: 40px; color: red;'><b>Error Crítico:</b> {str(e)}</div>"

@admin_bp.route('/admin/generar_migraciones')
@login_required
@role_required('admin', 'gerencia')
def generar_migraciones():
    from flask_migrate import init, migrate as db_migrate
    import shutil
    try:
        if not os.path.exists('migrations'): init()
        db_migrate(message="Estructura inicial completa")
        zip_path = os.path.join(os.getcwd(), 'migrations_backup')
        shutil.make_archive(zip_path, 'zip', os.getcwd(), 'migrations')
        return send_file(f"{zip_path}.zip", as_attachment=True)
    except Exception as e:
        return f"Ocurrió un error generando las migraciones: {str(e)}"

@admin_bp.route('/admin/cargar_taller', strict_slashes=False)
@login_required
@role_required('admin', 'gerencia')
def cargar_taller():
    return "Taller ya cargado."
