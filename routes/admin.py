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
from models.personal import Personal, RegistroUsoEquipo
from utils.formatters import clean_string, clean_int, clean_float, parse_date

admin_bp = Blueprint('admin', __name__)

@admin_bp.route('/admin/cargar_sql_final', strict_slashes=False)
@login_required
@role_required('admin', 'gerencia')
def cargar_sql_final():
    try:
        # Prevención: Agregar columnas si no existen
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
        archivo_filtros = next((f for f in archivos if "filtro" in f.lower() and f.endswith(('.xlsx', '.csv')) and not f.startswith('~$')), None)
        archivo_detalles = next((f for f in archivos if "detalles" in f.lower() and f.endswith(('.xlsx', '.csv')) and not f.startswith('~$')), None)

        if not excel_principal: return "Error: Falta el archivo principal CMMS DEMOTRON (.xlsx)."

        # --- 1. HOJA EQUIPOS ---
        df_eq = pd.read_excel(excel_principal, engine='openpyxl', sheet_name="Equipos", skiprows=2).replace({np.nan: None})
        df_eq.columns = df_eq.columns.str.strip()
        operadores_set = set()
        for _, row in df_eq.iterrows():
            cod = clean_string(str(row.get('Codigo', '') or ''))
            if not cod or cod.lower() == 'none': continue
            responsable = clean_string(str(row.get('Responsable', '') or 'Sin Asignar'))
            if responsable and responsable.lower() not in ['none','nan']: operadores_set.add(responsable)
            
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
        
        for op in operadores_set:
            if not Personal.query.filter_by(nombre=op).first():
                db.session.add(Personal(nombre=op, cargo="Operador", estado="Activo", equipo_asignado="Varios"))
        db.session.commit()

        # --- 2. HOJA LECTURAS ---
        df_lec = pd.read_excel(excel_principal, engine='openpyxl', sheet_name="Lecturas", skiprows=2).replace({np.nan: None})
        df_lec.columns = df_lec.columns.str.strip()
        for _, row in df_lec.iterrows():
            cod = clean_string(str(row.get('Codigo', '') or ''))
            if not cod or cod.lower() == 'none': continue
            fecha_dt = parse_date(row.get('Fecha'))
            hor = clean_int(row.get('Horometro'), 0)
            kil = clean_int(row.get('Kilometraje'), 0)
            if not HistorialLectura.query.filter_by(codigo_equipo=cod, fecha=fecha_dt, horometro=hor).first():
                db.session.add(HistorialLectura(
                    fecha=fecha_dt, codigo_equipo=cod, horometro=hor, kilometraje=kil,
                    obra_ubicacion=clean_string(str(row.get('Obra / Ubicacion', '') or '')),
                    responsable=clean_string(str(row.get('Responsable', '') or '')),
                    observacion=clean_string(str(row.get('Observacion', '') or ''))
                ))
        db.session.commit()

        # --- 3. HOJA MANTENCIONES (PREVENTIVAS) ---
        df_man = pd.read_excel(excel_principal, engine='openpyxl', sheet_name="Mantenciones", skiprows=2).replace({np.nan: None})
        df_man.columns = df_man.columns.str.strip()
        for _, row in df_man.iterrows():
            cod = clean_string(str(row.get('Codigo', '') or ''))
            if not cod or cod.lower() == 'none': continue
            fecha_dt = parse_date(row.get('Fecha'))
            tipo = clean_string(str(row.get('Tipo Mantencion', '') or ''))
            
            # --- FIX: MANEJO SEGURO DE FOLIO (Evita el error con 'SN' u otros textos) ---
            folio_raw = row.get('Folio')
            folio_str = ''
            if folio_raw is not None and str(folio_raw).lower() not in ['none', 'nan', '']:
                try:
                    # Intenta convertir a int si es número (ej: 15910.0 -> '15910')
                    folio_str = str(int(float(folio_raw)))
                except (ValueError, TypeError):
                    # Si falla (ej: 'SN'), lo deja como texto normal
                    folio_str = str(folio_raw).strip()
            # -----------------------------------------------------------------------------
            
            es_pm_raw = clean_string(str(row.get('EsPM', 'No') or 'No')).lower()
            tipo_ot = 'Preventiva' if es_pm_raw in ['sí','si','s','yes','1','true'] else 'Correctiva'
            
            if not OrdenTrabajo.query.filter_by(codigo_equipo=cod, fecha=fecha_dt, tipo_mantencion=tipo).first():
                db.session.add(OrdenTrabajo(
                    fecha=fecha_dt, codigo_equipo=cod, tipo_ot=tipo_ot, tipo_mantencion=tipo,
                    lectura=clean_int(row.get('Lectura'), 0),
                    es_pm=clean_string(str(row.get('EsPM', '') or '')),
                    folio=folio_str,
                    lugar=clean_string(str(row.get('Lugar', '') or '')),
                    costo_mantencion_clp=clean_float(row.get('Costo Mantencion CLP'), 0.0),
                    estado=clean_string(str(row.get('Estado', '') or 'Finalizada')) or 'Finalizada',
                    mecanico='Sin Asignar'
                ))
        db.session.commit()

        # --- 4. HOJA CORRECTIVAS ---
        try:
            df_corr = pd.read_excel(excel_principal, engine='openpyxl', sheet_name="Correctivas", skiprows=2).replace({np.nan: None})
            df_corr.columns = df_corr.columns.str.strip() # Corrige el bug del espacio "Falla / Averia "
            for _, row in df_corr.iterrows():
                cod = clean_string(str(row.get('Codigo Equipo', '') or ''))
                if not cod or cod.lower() == 'none': continue
                fecha_dt = parse_date(row.get('Fecha'))
                falla = clean_string(str(row.get('Falla / Averia', '') or ''))
                
                # --- FIX: MANEJO SEGURO DE FOLIO CORRECTIVAS ---
                folio_raw = row.get('Folio')
                if folio_raw is not None and str(folio_raw).lower() not in ['none', 'nan', '']:
                    try:
                        folio_val = str(int(float(folio_raw)))
                    except (ValueError, TypeError):
                        folio_val = str(folio_raw).strip()
                else:
                    folio_val = f"CM-{random.randint(1000,9999)}"
                # ------------------------------------------------
                
                mecanico_val = clean_string(str(row.get('Mecanico', '') or 'Sin Asignar')) or 'Sin Asignar'
                estado_val = clean_string(str(row.get('Estado', '') or 'Finalizada')) or 'Finalizada'
                
                # Inteligencia del Gráfico Pareto: Clasifica los registros viejos automáticamente
                falla_lower = falla.lower()
                if any(x in falla_lower for x in ['motor','aceite','filtro','refrigerante','radiador','correa']): sistema_val='Motor'
                elif any(x in falla_lower for x in ['hidraulic','hidráulic','manguera','bomba','cilindro','oring','fuga']): sistema_val='Hidráulico'
                elif any(x in falla_lower for x in ['freno','balata','tambor','pastilla']): sistema_val='Frenos'
                elif any(x in falla_lower for x in ['electri','eléctri','bateria','luces','sensor','cable']): sistema_val='Eléctrico'
                elif any(x in falla_lower for x in ['neumatico','neumático','rueda','llanta']): sistema_val='Neumáticos'
                else: sistema_val='Estructura'
                
                if not OrdenTrabajo.query.filter_by(codigo_equipo=cod, fecha=fecha_dt, tipo_mantencion=falla).first():
                    db.session.add(OrdenTrabajo(
                        fecha=fecha_dt, codigo_equipo=cod, tipo_ot='Correctiva', tipo_mantencion=falla,
                        lectura=clean_int(row.get('Lectura (Odo/Hor)'), 0),
                        costo_mantencion_clp=clean_float(row.get('Costo CLP'), 0.0),
                        estado=estado_val, folio=folio_val, mecanico=mecanico_val,
                        sistema_falla=sistema_val, causa_raiz=falla
                    ))
            db.session.commit()
        except Exception as e:
            print(f"Error Correctivas: {e}")

        # --- 5. HOJA COMPRAS PM ---
        try:
            df_com = pd.read_excel(excel_principal, engine='openpyxl', sheet_name="Compras PM", skiprows=2).replace({np.nan: None})
            df_com.columns = df_com.columns.str.strip()
            for _, row in df_com.iterrows():
                cod = clean_string(str(row.get('Codigo', '') or ''))
                oc_str = clean_string(str(row.get('OC', '') or ''))
                if not oc_str or oc_str.lower() in ['none','nan']: continue
                fecha_dt = parse_date(row.get('Fecha'))
                if not CompraRepuesto.query.filter_by(codigo_equipo=cod, oc=oc_str).first():
                    db.session.add(CompraRepuesto(
                        fecha=fecha_dt, oc=oc_str, codigo_equipo=cod,
                        descripcion=clean_string(str(row.get('Descripcion', '') or '')),
                        proveedor=clean_string(str(row.get('Proveedor', '') or '')),
                        costo_pm_clp=clean_float(row.get('Costo PM CLP'), 0.0),
                        estado_oc=clean_string(str(row.get('Estado OC', '') or ''))
                    ))
            db.session.commit()
        except Exception as e: pass

        # CÁLCULO DE PROYECCIONES FINALES
        for eq in Equipo.query.all():
            u_lec = HistorialLectura.query.filter_by(codigo_equipo=eq.codigo).order_by(HistorialLectura.fecha.desc(), HistorialLectura.id.desc()).first()
            if u_lec: eq.lectura_actual = u_lec.horometro if eq.control_base == 'HORAS' else u_lec.kilometraje
            u_pm = OrdenTrabajo.query.filter_by(codigo_equipo=eq.codigo, estado='Finalizada').order_by(OrdenTrabajo.fecha.desc()).first()
            if u_pm: eq.proxima_pm = u_pm.lectura + eq.frecuencia_base
            else: eq.proxima_pm = eq.lectura_actual + eq.frecuencia_base
        db.session.commit()

        # ARCHIVOS ADICIONALES (Filtros y detalles)
        if archivo_detalles:
            if archivo_detalles.endswith('.xlsx'): df_det = pd.read_excel(archivo_detalles, engine='openpyxl')
            else: df_det = pd.read_csv(archivo_detalles)
            df_det.columns = [str(c).strip() for c in df_det.columns]
            for _, row in df_det.iterrows():
                cod = str(row.get('Código', row.get('Codigo', ''))).strip()
                eq = Equipo.query.filter_by(codigo=cod).first()
                if eq:
                    eq.patente = clean_string(row.get('Placa', ''))
                    eq.vin = clean_string(row.get('N° Chasis', ''))
                    eq.n_motor = clean_string(row.get('N° Motor', ''))
            db.session.commit()

        if archivo_filtros:
            if archivo_filtros.endswith('.xlsx'): df_fil = pd.read_excel(archivo_filtros, engine='openpyxl')
            else: df_fil = pd.read_csv(archivo_filtros)
            df_fil = df_fil.replace({np.nan: "-"})
            for _, row in df_fil.iterrows():
                try:
                    cod = str(row.iloc[0]).strip()
                    sistema_f = str(row.iloc[1]).strip() if len(row)>1 else "-"
                    eq = Equipo.query.filter_by(codigo=cod).first()
                    if eq:
                        fil = FiltroEquipo.query.filter_by(codigo_equipo=cod, sistema=sistema_f).first()
                        if not fil:
                            db.session.add(FiltroEquipo(
                                codigo_equipo=cod, sistema=sistema_f,
                                cant=clean_int(row.iloc[2], 1) if len(row)>2 else 1, fleetguard=str(row.iloc[3]).strip() if len(row)>3 else "-",
                                baldwind=str(row.iloc[4]).strip() if len(row)>4 else "-", originales=str(row.iloc[5]).strip() if len(row)>5 else "-",
                                donaldson=str(row.iloc[6]).strip() if len(row)>6 else "-", otra=str(row.iloc[7]).strip() if len(row)>7 else "-"
                            ))
                except: pass
            db.session.commit()

        return "Carga Completa y Exitosa con Sincronización Segura. <a href='/'>Ir al Dashboard</a>"
    except Exception as e:
        db.session.rollback()
        return f"Error Crítico durante la carga: {str(e)}"

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
