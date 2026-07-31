import os
from werkzeug.utils import secure_filename
from flask import Blueprint, render_template, request, redirect, url_for
from datetime import datetime, timedelta
from collections import Counter
from flask_login import login_required
from sqlalchemy import func, case, text
from extensions import db

# Importamos todos los modelos necesarios en la cabecera
from models.equipo import Equipo, DocumentoEquipo, FiltroEquipo
from models.orden_trabajo import OrdenTrabajo
from models.historial import HistorialLectura, CompraRepuesto
from models.personal import Personal, Mecanico
from models.bodega import InventarioBodega
from utils.formatters import format_num, format_clp, buscar_foto_por_tipo

dashboard_bp = Blueprint('dashboard', __name__)

# =========================================================
# 1. VISTA PRINCIPAL: DASHBOARD PREDICTIVO (RELIABILITY)
# =========================================================
@dashboard_bp.route('/', strict_slashes=False)
@login_required
def dashboard():
    try:
        hoy = datetime.now()
        inicio_ano = datetime(hoy.year, 1, 1)
        
        eqs_db = Equipo.query.all()
        ots_db = OrdenTrabajo.query.all()
        compras_db = CompraRepuesto.query.all()

        total_eq = len(eqs_db)
        operativos = [e for e in eqs_db if e.estado_base == 'Operativo']
        en_taller = [e for e in eqs_db if e.estado_base == 'Taller']
        fuera_servicio = [e for e in eqs_db if e.estado_base == 'Fuera de Servicio']
        
        # DISPONIBILIDAD Y DOWNTIME
        disponibilidad_pct = round((len(operativos) / total_eq * 100), 1) if total_eq > 0 else 0.0
        downtime_pct = round(100.0 - disponibilidad_pct, 1)

        correctivas = [o for o in ots_db if o.tipo_ot == 'Correctiva']
        preventivas = [o for o in ots_db if o.tipo_ot == 'Preventiva']
        
        # CÁLCULOS GLOBALES MTTR y MTBF
        mttr_global_horas = 0
        cerradas_corr = [o for o in correctivas if o.estado == 'Finalizada' and o.fecha_cierre and o.fecha]
        if cerradas_corr:
            horas_tot = sum((o.fecha_cierre - o.fecha).total_seconds() / 3600 for o in cerradas_corr)
            mttr_global_horas = round(horas_tot / len(cerradas_corr), 1)

        dias_operacion_total = total_eq * 365 # Base anual para cálculos
        mtbf_global_dias = round(dias_operacion_total / max(1, len(correctivas)), 1)

        # =======================================================
        # NUEVO MOTOR PREDICTIVO POR SISTEMAS
        # =======================================================
        sistemas_stats = {}
        for o in correctivas:
            sys = o.sistema_falla or 'Otros'
            if sys not in sistemas_stats:
                sistemas_stats[sys] = {'count': 0, 'total_repair_hours': 0, 'last_date': None}
            sistemas_stats[sys]['count'] += 1
            
            if o.estado == 'Finalizada' and o.fecha_cierre and o.fecha:
                sistemas_stats[sys]['total_repair_hours'] += (o.fecha_cierre - o.fecha).total_seconds() / 3600
            
            if o.fecha:
                if not sistemas_stats[sys]['last_date'] or o.fecha > sistemas_stats[sys]['last_date']:
                    sistemas_stats[sys]['last_date'] = o.fecha

        resumen_sistemas = []
        for sys, data in sistemas_stats.items():
            count = data['count']
            mttr = round(data['total_repair_hours'] / count, 1) if count > 0 else 0
            mtbf_days = round(dias_operacion_total / max(1, count), 1)
            
            last_date = data['last_date']
            next_date = last_date + timedelta(days=mtbf_days) if last_date else None
            
            resumen_sistemas.append({
                'sistema': sys,
                'mtbf_days': mtbf_days,
                'mttr_hours': mttr,
                'last_date_str': last_date.strftime('%d/%m/%Y %H:%M') if last_date else 'S/I',
                'next_date_str': next_date.strftime('%d/%m/%Y %H:%M') if next_date else 'S/I',
                'count': count
            })
            
        resumen_sistemas = sorted(resumen_sistemas, key=lambda x: x['count'], reverse=True)
        
        # Generar porcentajes para las barras visuales en la tabla
        max_mtbf = max([s['mtbf_days'] for s in resumen_sistemas]) if resumen_sistemas else 1
        max_mttr = max([s['mttr_hours'] for s in resumen_sistemas]) if resumen_sistemas else 1
        
        for s in resumen_sistemas:
            s['mtbf_pct'] = min(100, (s['mtbf_days'] / max_mtbf) * 100)
            s['mttr_pct'] = min(100, (s['mttr_hours'] / max_mttr) * 100)

        # Gráficos (Data arrays)
        chart_sistemas_labels = [s['sistema'] for s in resumen_sistemas[:6]]
        chart_sistemas_mtbf = [s['mtbf_days'] for s in resumen_sistemas[:6]]
        chart_sistemas_mttr = [s['mttr_hours'] for s in resumen_sistemas[:6]]

        # =======================================================
        # PREPARACIÓN RESTO DEL SISTEMA (Tablas, Kanban, etc)
        # =======================================================
        equipos_dict = []
        eventos_calendario = []
        for e in eqs_db:
            margen = (e.proxima_pm or 0) - (e.lectura_actual or 0)
            if margen >= 0 and e.estado_base != 'Fuera de Servicio':
                dias_est = int(margen / (8 if e.control_base == 'HORAS' else 100))
                fecha_iso = (hoy + timedelta(days=max(1, dias_est))).strftime('%Y-%m-%d')
                if dias_est <= 45:
                    eventos_calendario.append({
                        'title': f"PM: {e.codigo}", 'start': fecha_iso, 'backgroundColor': '#DBEAFE', 'textColor': '#1E3A8A', 'borderColor': 'transparent'
                    })
            equipos_dict.append({
                'codigo': e.codigo, 'tipo': e.tipo_equipo or 'S/E', 'marca': e.marca or 'S/E', 'modelo': e.modelo or 'S/E',
                'patente': e.patente or 'S/I', 'ubicacion': e.ubicacion or 'S/I', 'lectura': format_num(e.lectura_actual), 
                'margen': margen, 'margen_str': format_num(margen), 'estado': e.estado_base, 'ctrl': e.control_base
            })

        bodega_db = InventarioBodega.query.order_by(InventarioBodega.nombre).all()
        personal_db = Personal.query.all()
        
        mants_prev = [{'id': m.id, 'fecha': m.fecha.strftime('%d/%m/%Y') if m.fecha else '', 'codigo': m.codigo_equipo, 'ot_generada': m.folio, 'tipo_mantencion': m.tipo_mantencion, 'costo_str': format_clp(m.costo_mantencion_clp), 'estado': m.estado, 'mecanico': m.mecanico} for m in preventivas]
        mants_corr = [{'id': m.id, 'fecha': m.fecha.strftime('%d/%m/%Y') if m.fecha else '', 'codigo': m.codigo_equipo, 'ot_generada': m.folio, 'sistema_falla': m.sistema_falla, 'causa_raiz': m.causa_raiz, 'costo_str': format_clp(m.costo_mantencion_clp), 'estado': m.estado, 'mecanico': m.mecanico} for m in correctivas]
        compras_formateadas = [{'id': c.id, 'fecha': c.fecha.strftime('%d/%m/%Y') if c.fecha else '', 'oc': c.oc, 'codigo': c.codigo_equipo, 'descripcion': c.descripcion, 'costo_str': format_clp(c.costo_pm_clp)} for c in compras_db]
        
        kanban = {'Pendiente': [], 'En Progreso': [], 'En Revisión': [], 'Finalizada': []}
        for ot in ots_db:
            k = ot.estado if ot.estado in kanban else 'Pendiente'
            detalle = getattr(ot, 'observacion', '')
            if not detalle:
                detalle = getattr(ot, 'causa_raiz', '')
            texto_tipo = f"{ot.tipo_mantencion} | {detalle}" if detalle else ot.tipo_mantencion
            kanban[k].append({'id': ot.id, 'codigo': ot.codigo_equipo, 'folio': ot.folio, 'tipo': texto_tipo, 'clasificacion': ot.tipo_ot, 'mecanico': ot.mecanico, 'fecha': ot.fecha.strftime('%d/%m %H:%M') if ot.fecha else ''})

        kpis = {
            'disponibilidad_pct': disponibilidad_pct, 'downtime_pct': downtime_pct,
            'mttr_global': mttr_global_horas, 'mtbf_global': mtbf_global_dias,
            'chart_labels': chart_sistemas_labels, 'chart_mtbf': chart_sistemas_mtbf, 'chart_mttr': chart_sistemas_mttr
        }

        return render_template('index.html', kpis=kpis, resumen_sistemas=resumen_sistemas, eqs=equipos_dict, mants_prev=mants_prev, mants_corr=mants_corr, compras=compras_formateadas, bodega=bodega_db, personal=personal_db, kanban=kanban, eventos_calendario=eventos_calendario)
    except Exception as e:
        return f"Error en Dashboard: {str(e)}"

@dashboard_bp.route('/equipo/<codigo>', strict_slashes=False)
@login_required
def detalle_equipo(codigo):
    try:
        equipo = Equipo.query.filter_by(codigo=codigo).first()
        if not equipo:
            return "Equipo no encontrado en la base de datos.", 404
        mants_prev = OrdenTrabajo.query.filter_by(codigo_equipo=codigo, tipo_ot='Preventiva').order_by(OrdenTrabajo.fecha.desc()).all()
        mants_corr = OrdenTrabajo.query.filter_by(codigo_equipo=codigo, tipo_ot='Correctiva').order_by(OrdenTrabajo.fecha.desc()).all()
        lecturas = HistorialLectura.query.filter_by(codigo_equipo=codigo).order_by(HistorialLectura.fecha.desc()).all()
        compras = CompraRepuesto.query.filter_by(codigo_equipo=codigo).order_by(CompraRepuesto.fecha.desc()).all()
        documentos = DocumentoEquipo.query.filter_by(codigo_equipo=codigo).order_by(DocumentoEquipo.fecha_vencimiento.asc()).all()
        operador = Personal.query.filter_by(equipo_asignado=codigo).first()
        foto_url = buscar_foto_por_tipo(equipo.tipo_equipo, equipo.marca)
        return render_template('equipo.html', equipo=equipo, mants_prev=mants_prev, mants_corr=mants_corr, lecturas=lecturas, compras=compras, documentos=documentos, operador=operador, foto_url=foto_url, hoy=datetime.now())
    except Exception as e:
        return f"Error al cargar la ficha del equipo: {str(e)}"

@dashboard_bp.route('/equipo/<codigo>/subir_documento', methods=['POST'])
@login_required
def subir_documento(codigo):
    try:
        tipo_documento = request.form.get('tipo_documento')
        fecha_vencimiento_str = request.form.get('fecha_vencimiento')
        archivo = request.files.get('archivo')
        if not tipo_documento or not archivo:
            return "Faltan datos o archivo", 400
        upload_folder = os.path.join('static', 'uploads', 'documentos')
        os.makedirs(upload_folder, exist_ok=True)
        ext = archivo.filename.rsplit('.', 1)[1].lower() if '.' in archivo.filename else 'pdf'
        filename = secure_filename(f"{codigo}_{tipo_documento.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{ext}")
        filepath = os.path.join(upload_folder, filename)
        archivo.save(filepath)
        fecha_vencimiento = datetime.strptime(fecha_vencimiento_str, '%Y-%m-%d').date() if fecha_vencimiento_str else None
        nuevo_doc = DocumentoEquipo(codigo_equipo=codigo, tipo_documento=tipo_documento, fecha_vencimiento=fecha_vencimiento, archivo_url=f"/static/uploads/documentos/{filename}")
        db.session.add(nuevo_doc)
        db.session.commit()
        return redirect(url_for('dashboard.detalle_equipo', codigo=codigo))
    except Exception as e:
        return f"Error al subir documento: {str(e)}", 500

@dashboard_bp.route('/imprimir_ot/<int:ot_id>', strict_slashes=False)
@login_required
def imprimir_ot(ot_id):
    try:
        ot = OrdenTrabajo.query.get(ot_id)
        if not ot:
            return "Orden de trabajo no encontrada.", 404
        equipo = Equipo.query.filter_by(codigo=ot.codigo_equipo).first()
        filtros = []
        if equipo:
            filtros = FiltroEquipo.query.filter_by(codigo_equipo=equipo.codigo).all()
        return render_template('imprimir_ot.html', ot=ot, equipo=equipo, filtros=filtros, hoy=datetime.now())
    except Exception as e:
        return f"Error al generar la Orden de Trabajo: {str(e)}"
