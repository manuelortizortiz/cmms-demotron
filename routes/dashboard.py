import os
from werkzeug.utils import secure_filename
from flask import Blueprint, render_template, request, redirect, url_for
from datetime import datetime, timedelta
from collections import Counter
from flask_login import login_required
from sqlalchemy import func, case, text
from extensions import db
from models.equipo import Equipo, DocumentoEquipo
from models.orden_trabajo import OrdenTrabajo
from models.historial import HistorialLectura, CompraRepuesto
from models.personal import Personal, Mecanico
from models.bodega import InventarioBodega
from utils.formatters import format_num, format_clp, buscar_foto_por_tipo

dashboard_bp = Blueprint('dashboard', __name__)

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
        atrasados = [e for e in eqs_db if (e.proxima_pm or 0) - (e.lectura_actual or 0) < 0 and e.estado_base != 'Fuera de Servicio']
        
        disponibilidad_pct = round((len(operativos) / total_eq * 100), 1) if total_eq > 0 else 0
        cumpl_pm_pct = round(((total_eq - len(atrasados)) / total_eq * 100), 1) if total_eq > 0 else 100.0

        correctivas = [o for o in ots_db if o.tipo_ot == 'Correctiva']
        preventivas = [o for o in ots_db if o.tipo_ot == 'Preventiva']
        
        total_ots = len(correctivas) + len(preventivas)
        ratio_corr = int(round((len(correctivas) / total_ots * 100), 0)) if total_ots > 0 else 0
        ratio_prev = 100 - ratio_corr if total_ots > 0 else 0

        costo_ytd_ots = sum(float(o.costo_mantencion_clp or 0) for o in ots_db if o.fecha and o.fecha >= inicio_ano)
        costo_ytd_compras = sum(float(c.costo_pm_clp or 0) for c in compras_db if c.fecha and c.fecha >= inicio_ano)
        costo_ytd_total = costo_ytd_ots + costo_ytd_compras

        mttr_horas = 0
        cerradas_corr = [o for o in correctivas if o.estado == 'Finalizada' and o.fecha_cierre and o.fecha]
        if cerradas_corr:
            horas_tot = sum((o.fecha_cierre - o.fecha).total_seconds() / 3600 for o in cerradas_corr)
            mttr_horas = round(horas_tot / len(cerradas_corr), 1)

        dias_operacion_total = total_eq * 30 
        mttb_dias = round(dias_operacion_total / max(1, len(correctivas)), 1)

        eqs_con_pm = set(o.codigo_equipo for o in preventivas)
        equipos_sin_pm = len([e for e in eqs_db if e.codigo not in eqs_con_pm and e.estado_base != 'Fuera de Servicio'])

        eq_fallas_counter = Counter(o.codigo_equipo for o in correctivas)
        top_equipos_fallas = []
        for cod, qty in eq_fallas_counter.most_common(5):
            eq_obj = next((e for e in eqs_db if e.codigo == cod), None)
            if eq_obj:
                foto = buscar_foto_por_tipo(eq_obj.tipo_equipo, eq_obj.marca)
                top_equipos_fallas.append({'codigo': cod, 'cantidad': qty, 'foto_url': foto})

        marcas_stats = {}
        equipos_dict = []
        eventos_calendario = []
        
        for e in eqs_db:
            m = e.marca or 'S/I'
            if m not in marcas_stats: marcas_stats[m] = {'total': 0, 'operativos': 0, 'costo': 0, 'fallas': 0}
            marcas_stats[m]['total'] += 1
            if e.estado_base == 'Operativo': marcas_stats[m]['operativos'] += 1
            
            c_ots = sum(float(o.costo_mantencion_clp or 0) for o in ots_db if o.codigo_equipo == e.codigo)
            c_compras = sum(float(c.costo_pm_clp or 0) for c in compras_db if c.codigo_equipo == e.codigo)
            c_eq_total = c_ots + c_compras
            
            f_eq = len([o for o in correctivas if o.codigo_equipo == e.codigo])
            marcas_stats[m]['costo'] += c_eq_total
            marcas_stats[m]['fallas'] += f_eq

            margen = (e.proxima_pm or 0) - (e.lectura_actual or 0)
            if margen >= 0 and e.estado_base != 'Fuera de Servicio':
                dias_est = int(margen / (8 if e.control_base == 'HORAS' else 100))
                fecha_iso = (hoy + timedelta(days=max(1, dias_est))).strftime('%Y-%m-%d')
                if dias_est <= 45:
                    eventos_calendario.append({
                        'title': f"PM: {e.codigo}",
                        'start': fecha_iso,
                        'backgroundColor': '#DBEAFE',
                        'textColor': '#1E3A8A',
                        'borderColor': 'transparent'
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
            
            # SOLUCIÓN: Recuperar todo el texto descriptivo y detalles (Filtros, Aceite, etc)
            detalle = getattr(ot, 'observacion', '')
            if not detalle:
                detalle = getattr(ot, 'causa_raiz', '')
                
            texto_tipo = f"{ot.tipo_mantencion} | {detalle}" if detalle else ot.tipo_mantencion
            
            kanban[k].append({
                'id': ot.id, 
                'codigo': ot.codigo_equipo, 
                'folio': ot.folio, 
                'tipo': texto_tipo, 
                'clasificacion': ot.tipo_ot, 
                'mecanico': ot.mecanico,
                'fecha': ot.fecha.strftime('%d/%m %H:%M') if ot.fecha else ''
            })

        kpis = {
            'total': total_eq, 'operativos': len(operativos), 'en_taller': len(en_taller), 'fuera_servicio': len(fuera_servicio), 'atrasados': len(atrasados),
            'disponibilidad_pct': disponibilidad_pct, 'cumpl_pm_pct': cumpl_pm_pct,
            'mttr': mttr_horas, 'mttb': mttb_dias, 'equipos_sin_mantencion': equipos_sin_pm,
            'costo_total_ytd': format_clp(costo_ytd_total), 'ratio_corr': ratio_corr, 'ratio_prev': ratio_prev,
            'correctivas_count': len(correctivas), 'preventivas_count': len(preventivas),
        }

        dist_marcas = [{'marca': k, 'total': v['total'], 'operativos': v['operativos'], 'costo': v['costo']} for k, v in marcas_stats.items()]
        dist_marcas = sorted(dist_marcas, key=lambda x: x['total'], reverse=True)

        chart_costo_marcas = {
            'labels': [m['marca'] for m in dist_marcas[:7]],
            'data': [m['costo'] for m in dist_marcas[:7]]
        }

        return render_template('index.html', kpis=kpis, eqs=equipos_dict, mants_prev=mants_prev, 
                               mants_corr=mants_corr, compras=compras_formateadas, bodega=bodega_db, 
                               personal=personal_db, kanban=kanban, eventos_calendario=eventos_calendario,
                               dist_marcas=dist_marcas, top_equipos_fallas=top_equipos_fallas, chart_costo_marcas=chart_costo_marcas)
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
