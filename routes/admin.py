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
        archivo_filtros = next((f for f in archivos if "filtro" in f.lower() and f.endswith(('.xlsx', '.csv')) and not f.startswith('~$')), None)
        archivo_detalles = next((f for f in archivos if "detalles" in f.lower() and f.endswith(('.xlsx', '.csv')) and not f.startswith('~$')), None)

        if not excel_principal: return "Error: Falta el archivo principal CMMS DEMOTRON (.xlsx)."

        # --- 1. HOJA EQUIPOS ---
        df_eq = pd.read_excel(excel_principal, engine='openpyxl', sheet_name="Equipos", skiprows=2).replace({np.nan: None})
        df_eq.columns = df_eq.columns.str.strip()
        operadores_set = set()
        for indice, row in df_eq.iterrows():
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

        # --- 2. HOJA LECTURAS (C y D) ---
        df_lec = pd.read_excel(excel_principal, engine='openpyxl', sheet_name="Lecturas", skiprows=2).replace({np.nan: None})
        for indice, row in df_lec.iterrows():
            if len(row) < 4: continue
            cod = clean_string(str(row.iloc[1] or ''))
            if not cod or cod.lower() == 'none': continue
            
            fecha_dt = parse_date(row.iloc[0])
            eq = Equipo.query.filter_by(codigo=cod).first()
            
            if eq:
                if eq.control_base == 'HORAS':
                    hor = clean_int(row.iloc[2], 0)
                    kil = 0
                else:
                    hor = 0
                    kil = clean_int(row.iloc[3], 0)
            else:
                hor = clean_int(row.iloc[2], 0)
                kil = clean_int(row.iloc[3], 0)

            if not HistorialLectura.query.filter_by(codigo_equipo=cod, fecha=fecha_dt, horometro=hor, kilometraje=kil).first():
                db.session.add(HistorialLectura(
                    fecha=fecha_dt, codigo_equipo=cod, horometro=hor, kilometraje=kil,
                    obra_ubicacion='', responsable='', observacion=''
                ))
        db.session.commit()

        # --- 3. HOJA MANTENCIONES (PREVENTIVAS) ---
        df_man = pd.read_excel(excel_principal, engine='openpyxl', sheet_name="Mantenciones", skiprows=2).replace({np.nan: None})
        df_man.columns = df_man.columns.str.strip()
        for indice, row in df_man.iterrows():
            cod = clean_string(str(row.get('Codigo', '') or ''))
            if not cod or cod.lower() == 'none': continue
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
            df_corr.columns = df_corr.columns.str.strip()  
            for indice, row in df_corr.iterrows():
                cod = clean_string(str(row.get('Codigo Equipo', '') or ''))
                if not cod or cod.lower() == 'none': continue
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
                if any(x in falla_lower for x in ['motor','aceite','filtro','refrigerante','radiador','correa']): sistema_val='Motor'
                elif any(x in falla_lower for x in ['hidraulic','hidráulic','manguera','bomba','cilindro','oring','fuga']): sistema_val='Hidráulico'
                elif any(x in falla_lower for x in ['freno','balata','tambor','pastilla']): sistema_val='Frenos'
                elif any(x in falla_lower for x in ['electri','eléctri','bateria','luces','sensor','cable']): sistema_val='Eléctrico'
                elif any(x in falla_lower for x in ['neumatico','neumático','rueda','llanta']): sistema_val='Neumáticos'
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
                        lectura=lectura_val, costo_mantencion_clp=costo_val,
                        estado=estado_val, folio=folio_val, mecanico=mecanico_val,
                        sistema_falla=sistema_val, causa_raiz=falla
                    ))
            db.session.commit()
        except Exception as e: pass

        # --- 5. HOJA COMPRAS PM ---
        try:
            df_com = pd.read_excel(excel_principal, engine='openpyxl', sheet_name="Compras PM", skiprows=2).replace({np.nan: None})
            df_com.columns = df_com.columns.str.strip()
            for indice, row in df_com.iterrows():
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

        # PROYECCIONES (FIX CD-107 INCLUIDO)
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
                    cod = str(row.get('Código', row.get('Codigo', ''))).strip()
                    eq = Equipo.query.filter_by(codigo=cod).first()
                    if eq:
                        eq.patente = clean_string(row.get('Placa', ''))
                        eq.vin = clean_string(row.get('N° Chasis', ''))
                        eq.n_motor = clean_string(row.get('N° Motor', ''))
                db.session.commit()
            except Exception as e: pass

        # --- IMPORTE INTELIGENTE Y SOBREESCRITURA DE FILTROS (UPSERT) ---
        if archivo_filtros:
            try:
                # 1. Intentar primero con skiprows=2
                if archivo_filtros.endswith('.xlsx'): df_fil = pd.read_excel(archivo_filtros, engine='openpyxl', skiprows=2)
                else: df_fil = pd.read_csv(archivo_filtros, skiprows=2)
                
                df_fil.columns = df_fil.columns.astype(str).str.strip()
                cols = [c.lower() for c in df_fil.columns]
                
                # Fallback: Si no encuentra la columna del equipo, significa que no tenía filas en blanco arriba
                if not any('cod' in c or 'equipo' in c for c in cols):
                    if archivo_filtros.endswith('.xlsx'): df_fil = pd.read_excel(archivo_filtros, engine='openpyxl')
                    else: df_fil = pd.read_csv(archivo_filtros)
                    df_fil.columns = df_fil.columns.astype(str).str.strip()
                    cols = [c.lower() for c in df_fil.columns]

                df_fil = df_fil.replace({np.nan: "-"})
                
                # Detección flexible de nombres de columna
                cod_c = next((c for c in df_fil.columns if 'cod' in c.lower() or 'equipo' in c.lower()), df_fil.columns[0] if len(df_fil.columns)>0 else None)
                sis_c = next((c for c in df_fil.columns if 'sistem' in c.lower()), df_fil.columns[1] if len(df_fil.columns)>1 else None)
                can_c = next((c for c in df_fil.columns if 'cant' in c.lower()), df_fil.columns[2] if len(df_fil.columns)>2 else None)
                fg_c = next((c for c in df_fil.columns if 'fleet' in c.lower()), df_fil.columns[3] if len(df_fil.columns)>3 else None)
                bw_c = next((c for c in df_fil.columns if 'bald' in c.lower()), df_fil.columns[4] if len(df_fil.columns)>4 else None)
                or_c = next((c for c in df_fil.columns if 'orig' in c.lower()), df_fil.columns[5] if len(df_fil.columns)>5 else None)
                dn_c = next((c for c in df_fil.columns if 'donald' in c.lower()), df_fil.columns[6] if len(df_fil.columns)>6 else None)
                ot_c = next((c for c in df_fil.columns if 'otra' in c.lower() or 'altern' in c.lower()), df_fil.columns[7] if len(df_fil.columns)>7 else None)

                for indice, row in df_fil.iterrows():
                    cod = clean_string(str(row.get(cod_c, '')))
                    if not cod or cod == '-': continue
                    
                    sistema_f = clean_string(str(row.get(sis_c, '-')))
                    eq = Equipo.query.filter_by(codigo=cod).first()
                    
                    if eq:
                        cant_val = clean_int(row.get(can_c), 1) if can_c else 1
                        fg_val = clean_string(str(row.get(fg_c, '-'))) if fg_c else "-"
                        bw_val = clean_string(str(row.get(bw_c, '-'))) if bw_c else "-"
                        or_val = clean_string(str(row.get(or_c, '-'))) if or_c else "-"
                        dn_val = clean_string(str(row.get(dn_c, '-'))) if dn_c else "-"
                        ot_val = clean_string(str(row.get(ot_c, '-'))) if ot_c else "-"

                        fil_existente = FiltroEquipo.query.filter_by(codigo_equipo=cod, sistema=sistema_f).first()
                        if fil_existente:
                            # MODO UPSERT: Sobreescribe los códigos viejos obligatoriamente
                            fil_existente.cant = cant_val
                            fil_existente.fleetguard = fg_val
                            fil_existente.baldwind = bw_val
                            fil_existente.originales = or_val
                            fil_existente.donaldson = dn_val
                            fil_existente.otra = ot_val
                        else:
                            # Si es nuevo, lo registra
                            db.session.add(FiltroEquipo(
                                codigo_equipo=cod, sistema=sistema_f, cant=cant_val,
                                fleetguard=fg_val, baldwind=bw_val, originales=or_val,
                                donaldson=dn_val, otra=ot_val
                            ))
                db.session.commit()
            except Exception as e:
                print(f"Error crítico en filtros: {e}")

        return "Carga Completa y Exitosa. <a href='/'>Ir al Dashboard</a>"
    except Exception as e:
        db.session.rollback()
        return f"Error Crítico: {str(e)}"

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
    equipo_taller = [
        {"rut": "8.999.300-8", "nombre": "Marcelo Alegria Corvalan", "cargo": "ELECTROMECANICO"},
        {"rut": "6.741.275-3", "nombre": "Francisco Antonio Almuna Bravo", "cargo": "MECANICO"},
        {"rut": "19.472.077-7", "nombre": "Elias Alvarado Otarola", "cargo": "ENCARGADO DE MANTENCIONES"},
        {"rut": "8.748.105-0", "nombre": "Daniel Hernan Andrade Altamirano", "cargo": "JEFE DE TALLER"},
        {"rut": "10.376.515-3", "nombre": "Francisco Javier Beltran Troncoso", "cargo": "ASISTENTE DE BODEGA"},
        {"rut": "15.140.259-3", "nombre": "Pablo Sebastián Bulnes Benvenuto", "cargo": "MECANICO"},
        {"rut": "18.054.327-9", "nombre": "Jonathan Alejandro Care Morales", "cargo": "MECANICO ESPECIALISTA EN A/C"},
        {"rut": "10.771.415-4", "nombre": "Juan Carlos Celedon Salinas", "cargo": "MECANICO"},
        {"rut": "14.512.996-6", "nombre": "Juan Carlos Cheuque Inostroza", "cargo": "SOLDADOR"},
        {"rut": "20.350.628-7", "nombre": "Domingo Andres Garrido Faundez", "cargo": "ASISTENTE DE CONTROL DE GESTIÓN"},
        {"rut": "19.899.574-6", "nombre": "Sergio Enrique Ibañez Pinilla", "cargo": "CHOFER"},
        {"rut": "20.650.926-0", "nombre": "Sebastian Antonio Lastra Bustamante", "cargo": "AYUDANTE"},
        {"rut": "15.825.783-1", "nombre": "Manuel Alejandro Ortiz Ortiz", "cargo": "JEFE DE SERVICIOS Y MANTENCIONES"},
        {"rut": "8.107.911-0", "nombre": "Francisco Solano Parra Muñoz", "cargo": "MECANICO"},
        {"rut": "14.449.904-2", "nombre": "Israel Perez Gomez", "cargo": "MECANICO"},
        {"rut": "20.755.048-5", "nombre": "Matias Ignacio Piñaleo Molina", "cargo": "AYUDANTE MECANICO"},
        {"rut": "20.070.537-8", "nombre": "Alejandro Andres Poblete Olivares", "cargo": "ASISTENTE DE TALLER"},
        {"rut": "13.371.052-3", "nombre": "Claudio Antonio Ramirez Muñoz", "cargo": "VULCANIZADOR"},
        {"rut": "13.068.903-5", "nombre": "Rodrigo Fernando Rigaud Briceño", "cargo": "ASISTENTE DE TALLER"},
        {"rut": "13.553.175-8", "nombre": "Luis Alejandro Rios Hernandez", "cargo": "MECANICO"},
        {"rut": "12.519.854-6", "nombre": "Bernardo Miguel Salinas Espinoza", "cargo": "ELECTRICISTA"},
        {"rut": "15.669.798-2", "nombre": "Octavio Andres Santelices Utreras", "cargo": "DESARROLLADOR DE SISTEMAS Y SOPORTE"},
        {"rut": "9.522.019-3", "nombre": "Washington Ernesto Sanzana Molina", "cargo": "MECANICO"},
        {"rut": "9.107.114-2", "nombre": "Marcelino Antonio Silva Naranjo", "cargo": "ASISTENTE DE TALLER"},
        {"rut": "12.284.982-1", "nombre": "Marcos Ricardo Soto Mendoza", "cargo": "ELECTROMECANICO"},
        {"rut": "11.676.490-3", "nombre": "Luis Felipe Valenzuela Burgos", "cargo": "ASISTENTE DE MECANICOS"},
        {"rut": "7.860.039-k", "nombre": "Juan Enrique Villalobos Saez", "cargo": "MECANICO"},
        {"rut": "7.960.088-1", "nombre": "Jorge Enrique Villanueva Vega", "cargo": "SOLDADOR"},
        {"rut": "9.136.728-9", "nombre": "Carlos Cesar Viñals Medina", "cargo": "SUPERVISOR DE TERRENO"}
    ]
    
    try:
        agregados = 0
        actualizados = 0
        for persona in equipo_taller:
            mecanico_existente = Mecanico.query.filter_by(nombre=persona['nombre']).first()
            if mecanico_existente:
                mecanico_existente.rut = persona['rut']
                mecanico_existente.especialidad = persona['cargo'].upper()
                actualizados += 1
            else:
                nuevo_membro = Mecanico(
                    rut=persona['rut'],
                    nombre=persona['nombre'], 
                    especialidad=persona['cargo'].upper(), 
                    estado='Activo'
                )
                db.session.add(nuevo_membro)
                agregados += 1
                
        db.session.commit()
        return "Carga de taller exitosa."
    except Exception as e:
        db.session.rollback()
        return f"Error: {str(e)}"
