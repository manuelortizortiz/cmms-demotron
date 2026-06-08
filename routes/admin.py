from flask import Blueprint
import os
import random
import pandas as pd
import numpy as np
from sqlalchemy import text
from extensions import db
from models.equipo import Equipo, FiltroEquipo
from models.orden_trabajo import OrdenTrabajo
from models.historial import HistorialLectura, CompraRepuesto
from models.personal import Personal, RegistroUsoEquipo
from utils.formatters import clean_string, clean_int, clean_float, parse_date

admin_bp = Blueprint('admin', __name__)

@admin_bp.route('/admin/cargar_sql_final', strict_slashes=False)
def cargar_sql_final():
    try:
        db.create_all()
        archivos = os.listdir('.')
        excel_principal = next((f for f in archivos if "CMMS" in f.upper() and f.endswith(('.xlsx', '.xls')) and not f.startswith('~$')), None)
        archivo_filtros = next((f for f in archivos if "filtro" in f.lower() and f.endswith(('.xlsx', '.csv')) and not f.startswith('~$')), None)
        archivo_detalles = next((f for f in archivos if "detalles" in f.lower() and f.endswith(('.xlsx', '.csv')) and not f.startswith('~$')), None)

        if not excel_principal: return "Error: Falta el archivo principal CMMS DEMOTRON (.xlsx)."

        df_eq = pd.read_excel(excel_principal, engine='openpyxl', sheet_name="Equipos", skiprows=2).replace({np.nan: None})
        operadores_set = set()
        for _, row in df_eq.iterrows():
            if not row.iloc[0]: continue
            cod = str(row.iloc[0]).strip()
            responsable = str(row.iloc[6]).strip() if row.iloc[6] else 'Sin Asignar'
            if responsable and responsable.lower() != 'none': operadores_set.add(responsable)
            
            eq = Equipo.query.filter_by(codigo=cod).first()
            if not eq:
                eq = Equipo(codigo=cod)
                db.session.add(eq)
            
            eq.tipo_equipo = row.iloc[1]
            eq.marca = row.iloc[2]
            eq.modelo = str(row.iloc[3])
            eq.ubicacion = row.iloc[5]
            eq.responsable = responsable
            eq.estado_base = str(row.iloc[7]).strip() if row.iloc[7] else 'Operativo'
            eq.control_base = str(row.iloc[8]).strip() if row.iloc[8] else 'HORAS'
            eq.frecuencia_base = clean_int(row.iloc[9], 250)
            
        for op in operadores_set:
            if not Personal.query.filter_by(nombre=op).first():
                db.session.add(Personal(nombre=op, cargo="Operador", estado="Activo", equipo_asignado="Varios"))
        db.session.commit()

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

        df_lec = pd.read_excel(excel_principal, engine='openpyxl', sheet_name="Lecturas", skiprows=2).replace({np.nan: None})
        for _, row in df_lec.iterrows():
            if not row.iloc[1]: continue
            fecha_dt = parse_date(row.iloc[0])
            cod = str(row.iloc[1]).strip()
            hor = clean_int(row.iloc[2], 0)
            kil = clean_int(row.iloc[3], 0)
            if not HistorialLectura.query.filter_by(codigo_equipo=cod, fecha=fecha_dt, horometro=hor, kilometraje=kil).first():
                db.session.add(HistorialLectura(fecha=fecha_dt, codigo_equipo=cod, horometro=hor, kilometraje=kil, obra_ubicacion=row.iloc[4], responsable=row.iloc[5], observacion=row.iloc[6]))

        df_man = pd.read_excel(excel_principal, engine='openpyxl', sheet_name="Mantenciones", skiprows=2).replace({np.nan: None})
        for _, row in df_man.iterrows():
            if not row.iloc[1]: continue
            fecha_dt = parse_date(row.iloc[0])
            cod = str(row.iloc[1]).strip()
            tipo = str(row.iloc[2]).strip()
            if not OrdenTrabajo.query.filter_by(codigo_equipo=cod, fecha=fecha_dt, tipo_mantencion=tipo).first():
                db.session.add(OrdenTrabajo(
                    fecha=fecha_dt, codigo_equipo=cod, tipo_ot='Preventiva', tipo_mantencion=tipo, 
                    lectura=clean_int(row.iloc[3], 0), es_pm=str(row.iloc[4]), folio=str(row.iloc[5]), 
                    lugar=str(row.iloc[6]), costo_mantencion_clp=clean_float(row.iloc[8], 0.0), 
                    estado=str(row.iloc[9]) if row.iloc[9] else 'Finalizada', mecanico="Sin Asignar"
                ))

        try:
            df_corr = pd.read_excel(excel_principal, engine='openpyxl', sheet_name="Correctivas", skiprows=2).replace({np.nan: None})
            for _, row in df_corr.iterrows():
                if not row.iloc[1]: continue
                fecha_dt = parse_date(row.iloc[0])
                cod = str(row.iloc[1]).strip()
                falla = str(row.iloc[2]).strip()
                
                estado_val = str(row.iloc[5]).strip() if len(row)>5 and row.iloc[5] else 'Finalizada'
                folio_val = str(row.iloc[6]).strip() if len(row)>6 and row.iloc[6] else f"CM-{random.randint(1000,9999)}"
                mecanico_val = str(row.iloc[7]).strip() if len(row)>7 and row.iloc[7] else 'Sin Asignar'

                if not OrdenTrabajo.query.filter_by(codigo_equipo=cod, fecha=fecha_dt, tipo_mantencion=falla).first():
                    db.session.add(OrdenTrabajo(
                        fecha=fecha_dt, codigo_equipo=cod, tipo_ot='Correctiva', tipo_mantencion=falla, 
                        lectura=clean_int(row.iloc[3], 0), costo_mantencion_clp=clean_float(row.iloc[4], 0.0), 
                        estado=estado_val, folio=folio_val, mecanico=mecanico_val
                    ))
        except: pass

        df_com = pd.read_excel(excel_principal, engine='openpyxl', sheet_name="Compras PM", skiprows=2).replace({np.nan: None})
        for _, row in df_com.iterrows():
            if not row.iloc[2]: continue
            fecha_dt = parse_date(row.iloc[0])
            oc_str = str(row.iloc[1])
            cod = str(row.iloc[2]).strip()
            if not CompraRepuesto.query.filter_by(codigo_equipo=cod, oc=oc_str).first():
                db.session.add(CompraRepuesto(fecha=fecha_dt, oc=oc_str, codigo_equipo=cod, descripcion=row.iloc[3], proveedor=row.iloc[4], costo_pm_clp=clean_float(row.iloc[5], 0.0), estado_oc=str(row.iloc[7])))
        
        db.session.commit()

        for eq in Equipo.query.all():
            u_lec = HistorialLectura.query.filter_by(codigo_equipo=eq.codigo).order_by(HistorialLectura.fecha.desc(), HistorialLectura.id.desc()).first()
            if u_lec: eq.lectura_actual = u_lec.horometro if eq.control_base == 'HORAS' else u_lec.kilometraje
            u_pm = OrdenTrabajo.query.filter_by(codigo_equipo=eq.codigo, estado='Finalizada').order_by(OrdenTrabajo.fecha.desc()).first()
            if u_pm: eq.proxima_pm = u_pm.lectura + eq.frecuencia_base
            else: eq.proxima_pm = eq.lectura_actual + eq.frecuencia_base
        db.session.commit()

        return "Carga Completa y Exitosa con Sincronización Segura. <a href='/'>Ir al Dashboard</a>"
    except Exception as e:
        return f"Error Crítico durante la carga: {str(e)}"
