import io
import pandas as pd
from flask import Blueprint, request, jsonify, redirect, send_file, render_template
from datetime import datetime
from flask_login import login_required
from extensions import db

# Importación de Modelos
from models.equipo import Equipo, FiltroEquipo
from models.orden_trabajo import OrdenTrabajo
from models.historial import HistorialLectura, CompraRepuesto
from models.bodega import InventarioBodega
from models.personal import Personal, Mecanico

# Definición del Blueprint
api_bp = Blueprint('api', __name__, url_prefix='/api')

# =========================================================
# RUTAS DE INGRESO DE DATOS (FORMULARIOS)
# =========================================================
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
                nueva_ot = OrdenTrabajo(
                    codigo_equipo=codigo,
                    tipo_ot='Preventiva',
                    tipo_mantencion=tipo,
                    folio=folio,
                    lectura=lectura,
                    costo_mantencion_clp=costo,
                    estado='Pendiente'
                )
            else:
                sistema_falla = request.form.get('sistema_falla')
                causa_raiz = request.form.get('causa_raiz')
                nueva_ot = OrdenTrabajo(
                    codigo_equipo=codigo,
                    tipo_ot='Correctiva',
                    sistema_falla=sistema_falla,
                    causa_raiz=causa_raiz,
                    folio=folio,
                    lectura=lectura,
                    costo_mantencion_clp=costo,
                    estado='Pendiente'
                )
            db.session.add(nueva_ot)
            
        elif tabla == 'lectura':
            codigo = request.form.get('codigo').upper().strip()
            valor = request.form.get('valor', type=float)
            responsable = request.form.get('responsable')
            
            eq = Equipo.query.filter_by(codigo=codigo).first()
            tipo_ctrl = eq.control_base if eq else 'HORAS'
            
            nueva_lec = HistorialLectura(
                codigo_equipo=codigo,
                tipo_equipo=eq.tipo_equipo if eq else 'S/I',
                horometro=valor if tipo_ctrl == 'HORAS' else None,
                kilometraje=valor if tipo_ctrl == 'KM' else None,
                responsable=responsable
            )
            db.session.add(nueva_lec)
            
            if eq:
                eq.lectura_actual = valor
                
        db.session.commit()
    except Exception as e:
        print(f"Error al agregar registro: {e}")
        db.session.rollback()
        
    return redirect(referer)

# =========================================================
# EDICIÓN RÁPIDA Y ELIMINACIÓN
# =========================================================
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
        print(f"Error al editar: {e}")
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

# =========================================================
# KANBAN (DRAG & DROP)
# =========================================================
@api_bp.route('/cambiar_estado_ot/<int:id>', methods=['POST'])
@login_required
def cambiar_estado_ot(id):
    try:
        data = request.get_json()
        nuevo_estado = data.get('estado')
        ot = OrdenTrabajo.query.get(id)
        if ot and nuevo_estado:
            ot.estado = nuevo_estado
            if nuevo_estado == 'Finalizada':
                ot.fecha_cierre = datetime.now()
            db.session.commit()
            return jsonify({'status': 'success'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    return jsonify({'status': 'error'}), 400

# =========================================================
# EXPORTACIÓN EXCEL
# =========================================================
@api_bp.route('/exportar/excel_maestro', methods=['GET'])
@login_required
def exportar_excel():
    try:
        equipos = Equipo.query.all()
        data = []
        for e in equipos:
            data.append({
                'Código': e.codigo,
                'Marca': e.marca,
                'Modelo': e.modelo,
                'Patente': e.patente,
                'Estado': e.estado_base,
                'Ubicación': e.ubicacion,
                'Lectura': e.lectura_actual
            })
        df = pd.DataFrame(data)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name='Equipos', index=False)
        output.seek(0)
        return send_file(output, download_name=f"Maestro_Equipos_{datetime.now().strftime('%Y%m%d')}.xlsx", as_attachment=True)
    except Exception as e:
        return f"Error al generar Excel: {str(e)}"

# =========================================================
# RUTAS DE IMPRESIÓN PDF (HISTORIAL Y FILTROS)
# =========================================================
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
        return f"Aviso del Sistema: No se pudo generar la vista del PDF corporativo ({str(e)})."

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

# =========================================================
# CARGA MASIVA DEL EXCEL "MAESTRO DE FILTROS" (CORREGIDO)
# =========================================================
@api_bp.route('/cargar_maestro_filtros', methods=['GET', 'POST'])
def cargar_maestro_filtros():
    token = request.args.get('token')
    if token != 'DemotronFiltros2026':
        return "Acceso denegado. Token inválido.", 403

    if request.method == 'GET':
        return '''
        <div style="font-family: sans-serif; padding: 40px; text-align: center; max-width: 600px; margin: auto;">
            <h2 style="color: #1E3A8A;">Subir Maestro de Filtros (Excel)</h2>
            <p style="color: #64748B; font-size: 14px;">Asegúrate de seleccionar el archivo antes de presionar el botón azul.</p>
            
            <form method="POST" enctype="multipart/form-data" style="margin-top: 30px; padding: 20px; border: 2px dashed #CBD5E1; border-radius: 10px; background: #F8FAFC;">
                <input type="file" name="file" accept=".xlsx, .xls" required style="margin-bottom: 20px; width: 100%; font-size: 16px;"><br>
                <button type="submit" style="padding: 12px 25px; background: #1E3A8A; color: white; border: none; border-radius: 5px; font-weight: bold; cursor: pointer; width: 100%;">Subir e Importar</button>
            </form>
        </div>
        '''
    
    # 1. Verificamos que el archivo venga en la solicitud
    if 'file' not in request.files:
        return "<h3 style='color:red; text-align:center;'>Error: No se envió la instrucción de archivo.</h3>", 400
        
    file = request.files['file']
    
    # 2. Verificamos que el archivo tenga nombre (que no esté vacío)
    if file.filename == '':
        return "<div style='text-align:center; padding: 40px;'><h2 style='color:red;'>No se seleccionó ningún archivo</h2><p>Por favor, haz clic en 'Elegir archivo' antes de presionar el botón.</p><a href='/api/cargar_maestro_filtros?token=DemotronFiltros2026'>Volver atrás</a></div>", 400
        
    try:
        df = pd.read_excel(file)
        
        columnas_reales = list(df.columns)
        df.columns = df.columns.astype(str).str.strip().str.lower()
        
        db.session.query(FiltroEquipo).delete()
        registros_agregados = 0
        
        for index, row in df.iterrows():
            # Lector Blindado por Posición y Nombre adaptado exactamente a tu Maestro
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
            
            # Buscamos en 'originales', 'fleetguard' u otra posición
            c_orig = row.get('originales') or row.get('codigo')
            if c_orig is None and len(df.columns) > 5: c_orig = row.iloc[5] # Columna 6 (ORIGINALES)
            
            if pd.isna(c_orig) or str(c_orig).strip().lower() == 'nan':
                # Si Originales está vacío, intentamos sacar de Fleetguard (Columna 4)
                if len(df.columns) > 3 and pd.notna(row.iloc[3]): c_orig = row.iloc[3]
                
            c_orig = str(c_orig).strip() if pd.notna(c_orig) else '-'
            
            # AQUÍ ESTÁ LA CORRECCIÓN: Quitamos fleetguard, donaldson y baldwind
            nuevo_filtro = FiltroEquipo(
                codigo_equipo=c_eq,
                sistema=c_sist,
                cant=c_cant,
                originales=c_orig
            )
            
            db.session.add(nuevo_filtro)
            registros_agregados += 1
            
        db.session.commit()
        
        if registros_agregados == 0:
            return f"<div style='padding: 40px; text-align: center; color: red;'><h2>El archivo está vacío.</h2><p>Columnas que el sistema detectó: <b>{columnas_reales}</b></p><br><a href='/api/cargar_maestro_filtros?token=DemotronFiltros2026'>Intentar de nuevo</a></div>"

        return f"<div style='font-family: sans-serif; padding: 40px; text-align: center; color: green;'><h2>¡Éxito Total!</h2><p>Se importaron {registros_agregados} filtros corporativos correctamente.</p><a href='/'>Volver al Inicio</a></div>"
        
    except Exception as e:
        db.session.rollback()
        return f"Error al procesar el Excel: {str(e)}"
