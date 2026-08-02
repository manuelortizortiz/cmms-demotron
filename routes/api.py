import io
import pandas as pd
from flask import Blueprint, request, jsonify, redirect, send_file, render_template
from datetime import datetime
from flask_login import login_required
from extensions import db
from sqlalchemy import text 

# Importación de Modelos
from models.equipo import Equipo, FiltroEquipo
from models.orden_trabajo import OrdenTrabajo
from models.historial import HistorialLectura, CompraRepuesto
from models.bodega import InventarioBodega
from models.personal import Personal, Mecanico

api_bp = Blueprint('api', __name__, url_prefix='/api')

@api_bp.route('/add_record', methods=['POST'])
@login_required
def add_record():
    tabla = request.form.get('tabla')
    referer = request.form.get('referer') or '/'
    
    try:
        if tabla == 'ot' or tabla == 'ot_corr':
            codigo = request.form.get('codigo').upper().strip()
            folio = request.form.get('folio')
            lectura = request.form.get('lectura', type=float) or 0.0
            costo = request.form.get('costo', type=float) or 0.0
            
            if tabla == 'ot':
                tipo = request.form.get('tipo')
                nueva_ot = OrdenTrabajo(codigo_equipo=codigo, tipo_ot='Preventiva', tipo_mantencion=tipo, folio=folio, lectura=lectura, costo_mantencion_clp=costo, estado='Pendiente')
            else:
                sistema_falla = request.form.get('sistema_falla')
                causa_raiz = request.form.get('causa_raiz')
                nueva_ot = OrdenTrabajo(codigo_equipo=codigo, tipo_ot='Correctiva', sistema_falla=sistema_falla, causa_raiz=causa_raiz, folio=folio, lectura=lectura, costo_mantencion_clp=costo, estado='Pendiente')
            db.session.add(nueva_ot)
            
        elif tabla == 'lectura':
            codigo = request.form.get('codigo').upper().strip()
            valor = request.form.get('valor', type=float)
            responsable = request.form.get('responsable')
            
            eq = Equipo.query.filter_by(codigo=codigo).first()
            tipo_ctrl = eq.control_base if eq else 'HORAS'
            
            nueva_lec = HistorialLectura(codigo_equipo=codigo, tipo_equipo=eq.tipo_equipo if eq else 'S/I', horometro=valor if tipo_ctrl == 'HORAS' else None, kilometraje=valor if tipo_ctrl == 'KM' else None, responsable=responsable)
            db.session.add(nueva_lec)
            if eq: eq.lectura_actual = valor
                
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        
    return redirect(referer)

@api_bp.route('/edit_record', methods=['POST'])
@login_required
def edit_record():
    tabla = request.form.get('tabla')
    obj_id = request.form.get('id')
    referer = request.form.get('referer') or '/'
    try:
        if tabla == 'equipo':
            eq = Equipo.query.filter_by(codigo=obj_id).first()
            if eq:
                eq.marca = request.form.get('marca', eq.marca).upper()
                eq.modelo = request.form.get('modelo', eq.modelo).upper()
                eq.patente = request.form.get('patente', eq.patente).upper()
                eq.estado_base = request.form.get('estado_base', eq.estado_base)
                db.session.commit()
    except Exception as e:
        db.session.rollback()
    return redirect(referer)

@api_bp.route('/delete_record/<tabla>/<int:id>', methods=['POST'])
@login_required
def delete_record(tabla, id):
    try:
        obj = None
        if tabla == 'ot' or tabla == 'ot_corr': obj = OrdenTrabajo.query.get(id)
        elif tabla == 'lectura': obj = HistorialLectura.query.get(id)
        elif tabla == 'bodega': obj = InventarioBodega.query.get(id)
        elif tabla == 'compra': obj = CompraRepuesto.query.get(id)
        elif tabla == 'personal': obj = Personal.query.get(id)
        elif tabla == 'mecanico': obj = Mecanico.query.get(id)
        if obj:
            db.session.delete(obj)
            db.session.commit()
            return jsonify({'status': 'success'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    return jsonify({'status': 'not_found'}), 404

@api_bp.route('/cambiar_estado_ot/<int:id>', methods=['POST'])
@login_required
def cambiar_estado_ot(id):
    try:
        data = request.get_json()
        nuevo_estado = data.get('estado')
        ot = OrdenTrabajo.query.get(id)
        if ot and nuevo_estado:
            ot.estado = nuevo_estado
            if nuevo_estado == 'Finalizada': ot.fecha_cierre = datetime.now()
            db.session.commit()
            return jsonify({'status': 'success'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    return jsonify({'status': 'error'}), 400

@api_bp.route('/exportar/excel_maestro', methods=['GET'])
@login_required
def exportar_excel():
    try:
        equipos = Equipo.query.all()
        data = [{'Código': e.codigo, 'Marca': e.marca, 'Modelo': e.modelo, 'Patente': e.patente, 'Estado': e.estado_base, 'Ubicación': e.ubicacion, 'Lectura': e.lectura_actual} for e in equipos]
        df = pd.DataFrame(data)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name='Equipos', index=False)
        output.seek(0)
        return send_file(output, download_name=f"Maestro_Equipos_{datetime.now().strftime('%Y%m%d')}.xlsx", as_attachment=True)
    except Exception as e:
        return f"Error al generar Excel: {str(e)}"

@api_bp.route('/imprimir_registro/<codigo>', strict_slashes=False)
@login_required
def imprimir_registro(codigo):
    try:
        equipo = Equipo.query.filter_by(codigo=codigo).first()
        if not equipo: return "Equipo no encontrado en la Base de Datos", 404
        mants_prev = OrdenTrabajo.query.filter_by(codigo_equipo=codigo, tipo_ot='Preventiva').order_by(OrdenTrabajo.fecha.desc()).all()
        mants_corr = OrdenTrabajo.query.filter_by(codigo_equipo=codigo, tipo_ot='Correctiva').order_by(OrdenTrabajo.fecha.desc()).all()
        return render_template('imprimir_registro.html', equipo=equipo, mants_prev=mants_prev, mants_corr=mants_corr, hoy=datetime.now())
    except Exception as e:
        return f"Aviso del Sistema: No se pudo generar la vista del PDF ({str(e)})."

@api_bp.route('/imprimir_filtros/<codigo>', strict_slashes=False)
@login_required
def imprimir_filtros(codigo):
    try:
        equipo = Equipo.query.filter_by(codigo=codigo).first()
        if not equipo: return "Equipo no encontrado en la Base de Datos", 404
        filtros = FiltroEquipo.query.filter_by(codigo_equipo=codigo).all()
        return render_template('imprimir_filtros.html', equipo=equipo, filtros=filtros, hoy=datetime.now())
    except Exception as e:
        return f"Aviso del Sistema: No se pudo generar la hoja de filtros PDF ({str(e)})."

@api_bp.route('/cargar_maestro_filtros', methods=['GET', 'POST'])
def cargar_maestro_filtros():
    token = request.args.get('token')
    if token != 'DemotronFiltros2026': return "Acceso denegado.", 403

    if request.method == 'GET':
        return '''
        <div style="font-family: sans-serif; padding: 40px; text-align: center; max-width: 600px; margin: auto;">
            <h2 style="color: #1E3A8A;">Subir Maestro de Filtros (Excel)</h2>
            <form method="POST" enctype="multipart/form-data" style="margin-top: 30px; padding: 20px; border: 2px dashed #CBD5E1; border-radius: 10px; background: #F8FAFC;">
                <input type="file" name="file" accept=".xlsx, .xls" required style="margin-bottom: 20px; width: 100%; font-size: 16px;"><br>
                <button type="submit" style="padding: 12px 25px; background: #1E3A8A; color: white; border: none; border-radius: 5px; font-weight: bold; cursor: pointer; width: 100%;">Subir e Importar</button>
            </form>
        </div>
        '''
    
    if 'file' not in request.files or request.files['file'].filename == '': return "Error de archivo.", 400
        
    try:
        file = request.files['file']
        df = pd.read_excel(file)
        df.columns = df.columns.astype(str).str.strip().str.lower()
        
        # === MAGIA: AUTO-CREADOR DE COLUMNA EN POSTGRESQL ===
        try:
            db.session.execute(text("ALTER TABLE filtro_equipo ADD COLUMN otra_alternativa VARCHAR(150)"))
            db.session.commit()
        except Exception:
            db.session.rollback() # Si la columna ya existe, ignora el error y avanza
            
        db.session.execute(text("DELETE FROM filtro_equipo"))
        registros_agregados = 0
        
        # INYECTAMOS INCLUYENDO OTRA_ALTERNATIVA
        sql_insert = text("""
            INSERT INTO filtro_equipo 
            (codigo_equipo, sistema, cant, originales, fleetguard, donaldson, baldwind, otra_alternativa) 
            VALUES (:eq, :sist, :cant, :orig, :fleet, :don, :bald, :otra)
        """)
        
        for index, row in df.iterrows():
            c_eq = row.get('equipo') or row.get('codigo equipo') or row.get('código equipo')
            if c_eq is None and len(df.columns) > 0: c_eq = row.iloc[0]
            c_eq = str(c_eq).strip() if pd.notna(c_eq) else ''
            if not c_eq or c_eq.lower() in ['nan', 'none', '']: continue
                
            c_sist = row.get('sistema / tipo de filtro') or row.get('filtro') or row.get('sistema')
            if c_sist is None and len(df.columns) > 1: c_sist = row.iloc[1]
            c_sist = str(c_sist).strip() if pd.notna(c_sist) else '-'
            
            c_cant = row.get('cant') or row.get('cantidad')
            if c_cant is None and len(df.columns) > 2: c_cant = row.iloc[2]
            c_cant = str(c_cant).strip() if pd.notna(c_cant) else '1'
            
            c_fleet = row.get('fleetguard')
            if c_fleet is None and len(df.columns) > 3: c_fleet = row.iloc[3]
            c_fleet = str(c_fleet).strip() if pd.notna(c_fleet) and str(c_fleet).strip().lower() != 'nan' else '-'
            
            c_bald = row.get('baldwind') or row.get('baldwin')
            if c_bald is None and len(df.columns) > 4: c_bald = row.iloc[4]
            c_bald = str(c_bald).strip() if pd.notna(c_bald) and str(c_bald).strip().lower() != 'nan' else '-'
            
            c_orig = row.get('originales') or row.get('codigo')
            if c_orig is None and len(df.columns) > 5: c_orig = row.iloc[5]
            c_orig = str(c_orig).strip() if pd.notna(c_orig) and str(c_orig).strip().lower() != 'nan' else '-'
            
            c_don = row.get('donaldson')
            if c_don is None and len(df.columns) > 6: c_don = row.iloc[6]
            c_don = str(c_don).strip() if pd.notna(c_don) and str(c_don).strip().lower() != 'nan' else '-'
            
            # NUEVO: Leer Otra Alternativa (Columna 8 de tu Excel)
            c_otra = row.get('otra alternativa') or row.get('otra')
            if c_otra is None and len(df.columns) > 7: c_otra = row.iloc[7]
            c_otra = str(c_otra).strip() if pd.notna(c_otra) and str(c_otra).strip().lower() != 'nan' else '-'
            
            db.session.execute(sql_insert, {
                "eq": c_eq, "sist": c_sist, "cant": c_cant, 
                "orig": c_orig, "fleet": c_fleet, "bald": c_bald, 
                "don": c_don, "otra": c_otra
            })
            registros_agregados += 1
            
        db.session.commit()
        return f"<div style='padding: 40px; text-align: center; color: green;'><h2>¡Éxito!</h2><p>Se importaron {registros_agregados} filtros con la columna OTRA ALTERNATIVA.</p><a href='/'>Volver</a></div>"
        
    except Exception as e:
        db.session.rollback()
        return f"Error: {str(e)}"
