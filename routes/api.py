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
            
            # Actualizar lectura automáticamente en la Ficha del Equipo
            if eq:
                eq.lectura_actual = valor
                
        db.session.commit()
    except Exception as e:
        print(f"Error al agregar registro: {e}")
        db.session.rollback()
        
    return redirect(referer)

# =========================================================
# EDICIÓN RÁPIDA (MODAL)
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

# =========================================================
# ELIMINACIÓN DE REGISTROS
# =========================================================
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
# EXPORTACIÓN EXCEL Y EXTRAS
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

@api_bp.route('/guardar_programacion', methods=['POST'])
@login_required
def guardar_programacion():
    # Lógica de correos automatizados
    return redirect('/?tab=automatizacion')

@api_bp.route('/powerbi/dataset', methods=['GET'])
def powerbi_dataset():
    # Endpoint para extraer datos desde PowerBI
    return jsonify({"status": "activo", "conexion": "ok"})

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
