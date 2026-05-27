import os
import random
import pandas as pd
import numpy as np
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.secret_key = 'demotron_seguridad_maxima_2026'

ruta_db = os.getenv('DATABASE_URL', 'sqlite:///demotron_master.db')
if ruta_db.startswith("postgres://"):
    ruta_db = ruta_db.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = ruta_db
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ==========================================
# MODELOS DE BASE DE DATOS
# ==========================================
class Personal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100))
    cargo = db.Column(db.String(100), default="Operador")
    estado = db.Column(db.String(50), default="Activo")

class Equipo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), unique=True)
    tipo_equipo = db.Column(db.String(100))
    marca = db.Column(db.String(50))
    modelo = db.Column(db.String(100))
    ubicacion = db.Column(db.String(100))
    responsable = db.Column(db.String(100))
    estado_base = db.Column(db.String(50), default="Operativo")
    control_base = db.Column(db.String(50), default="HORAS")
    frecuencia_base = db.Column(db.Integer, default=250)
    lectura_actual = db.Column(db.Integer, default=0)
    proxima_pm = db.Column(db.Integer, default=0)
    vin = db.Column(db.String(100), default="")
    n_motor = db.Column(db.String(100), default="")
    patente = db.Column(db.String(50), default="")
    pauta_filtros = db.Column(db.Text, default="Registrar filtros...")
    planificacion_mantencion = db.Column(db.Text, default="Describir pauta...")

    @property
    def margen(self): return (self.proxima_pm or 0) - (self.lectura_actual or 0)

class OrdenTrabajo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=datetime.now)
    codigo_equipo = db.Column(db.String(50))
    tipo_mantencion = db.Column(db.String(100))
    costo_mantencion_clp = db.Column(db.Float, default=0.0)
    estado = db.Column(db.String(50), default="Pendiente")
    folio = db.Column(db.String(50))
    lectura = db.Column(db.Integer, default=0)

class HistorialLectura(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=datetime.now)
    codigo_equipo = db.Column(db.String(50))
    horometro = db.Column(db.Integer, default=0)
    kilometraje = db.Column(db.Integer, default=0)
    obra_ubicacion = db.Column(db.String(100))
    responsable = db.Column(db.String(100))
    observacion = db.Column(db.String(250))

class CompraRepuesto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=datetime.now)
    oc = db.Column(db.String(100))
    codigo_equipo = db.Column(db.String(50))
    descripcion = db.Column(db.String(250))
    proveedor = db.Column(db.String(100))
    costo_pm_clp = db.Column(db.Float, default=0.0)

with app.app_context(): db.create_all()

# ==========================================
# FUNCIONES AUXILIARES
# ==========================================
def clean_string(val):
    s = str(val).strip()
    return "" if s.lower() in ['nan', 'none', ''] else s

def clean_int(val, default=0):
    try: return int(float(clean_string(val))) if clean_string(val) else default
    except: return default

def format_num(val):
    try: return f"{int(float(str(val))):,}".replace(",", ".")
    except: return "0"

def format_clp(val):
    try: return f"$ {int(float(str(val))):,}".replace(",", ".")
    except: return "$ 0"

def buscar_foto_por_tipo(tipo_equipo, marca=""):
    t = str(tipo_equipo).lower(); m = str(marca).lower()
    if "tolva" in t: return "/static/equipos_real/camion_man_tolva.png"
    if "tracto" in t: return "/static/equipos_real/tractocamion.png"
    if "camioneta" in t: return "/static/equipos_real/maxus_t60.png"
    if any(x in t for x in ["furgon", "minibus", "bus"]): return "/static/equipos_real/minibus.png"
    if any(x in t for x in ["liviano", "pintura", "slurry", "plano"]): return "/static/equipos_real/camion_liviano.png"
    return "/static/equipos_real/tractocamion.png"

# ==========================================
# RUTAS DEL ERP
# ==========================================
@app.route('/', strict_slashes=False)
def dashboard():
    try:
        eqs_db = Equipo.query.all()
        ots_db = OrdenTrabajo.query.order_by(OrdenTrabajo.id.desc()).all()
        compras_db = CompraRepuesto.query.order_by(CompraRepuesto.fecha.desc()).all()
        lecturas_db = HistorialLectura.query.order_by(HistorialLectura.id.desc()).all()
        operadores = Personal.query.all()
        
        equipos_dict, taller, criticos = [], [], []
        conteo_estado = {'Operativo': 0, 'Fuera de Servicio': 0, 'Taller': 0}
        
        for e in eqs_db:
            eq_data = {
                'codigo': e.codigo, 'tipo': e.tipo_equipo or 'S/E', 'marca': e.marca or 'S/E', 'modelo': e.modelo or 'S/E',
                'ubicacion': e.ubicacion or 'Sin Ubicación', 'responsable': e.responsable or 'Sin Asignar', 'ctrl': e.control_base,
                'lectura': format_num(e.lectura_actual), 'margen': e.margen, 
                'margen_str': format_num(e.margen), 'estado': e.estado_base,
                'vin': e.vin, 'motor': e.n_motor, 'patente': e.patente,
                'foto_url': buscar_foto_por_tipo(e.tipo_equipo, e.marca)
            }
            equipos_dict.append(eq_data)
            estado_clean = 'Fuera de Servicio' if e.estado_base in ['Fuera de Servicio', 'No operativo'] else e.estado_base
            conteo_estado[estado_clean] = conteo_estado.get(estado_clean, 0) + 1
            
            if e.estado_base == 'Taller': taller.append(eq_data)
            if e.margen < 0 and e.estado_base != 'Fuera de Servicio': criticos.append(eq_data)

        equipos_aleatorios = list(equipos_dict)
        random.shuffle(equipos_aleatorios)

        kanban_tareas = {'Pendiente': [], 'En Progreso': [], 'En Revisión': [], 'Completado': []}
        equipos_con_ot = []
        for ot in ots_db:
            if ot.estado in kanban_tareas:
                kanban_tareas[ot.estado].append({'codigo': ot.codigo_equipo, 'tipo': ot.folio, 'margen': ot.fecha.strftime('%d/%m/%Y') if ot.fecha else 'S/F', 'estado': ot.estado})
                equipos_con_ot.append(ot.codigo_equipo)
        
        for c in criticos:
            if c['codigo'] not in equipos_con_ot:
                kanban_tareas['Pendiente'].append({'codigo': c['codigo'], 'tipo': c['tipo'], 'margen': c['margen_str'], 'estado': 'Pendiente'})

        todas_mants = [{'id': m.id, 'fecha': m.fecha.strftime('%d/%m/%Y') if m.fecha else 'S/F', 'fecha_iso': m.fecha.strftime('%Y-%m-%d') if m.fecha else '', 'codigo': m.codigo_equipo, 'ot_generada': m.folio, 'tipo_mantencion': m.tipo_mantencion, 'costo_str': format_clp(m.costo_mantencion_clp), 'estado': m.estado, 'lectura_str': format_num(m.lectura)} for m in ots_db]
        todas_compras = [{'id': c.id, 'fecha': c.fecha.strftime('%d/%m/%Y') if c.fecha else 'S/F', 'oc': c.oc, 'codigo': c.codigo_equipo, 'descripcion': c.descripcion, 'costo_str': format_clp(c.costo_pm_clp)} for c in compras_db]
        todas_lecturas = [{'id': l.id, 'fecha': l.fecha.strftime('%d/%m/%Y %H:%M') if l.fecha else 'S/F', 'codigo': l.codigo_equipo, 'valor_str': format_num(max(l.horometro or 0, l.kilometraje or 0)), 'tipo': 'HR' if (l.horometro and l.horometro > 0) else 'KM', 'obs': l.observacion, 'responsable': l.responsable, 'ubicacion': l.obra_ubicacion} for l in lecturas_db]
        logs_list = []

        mes_actual = datetime.now().month
        costos = {2:0, 3:0, 4:0, 5:0, 6:0}
        for ot in ots_db:
            if ot.fecha and ot.fecha.year >= 2026 and ot.fecha.month in costos:
                costos[ot.fecha.month] += (ot.costo_mantencion_clp or 0)
        for c in compras_db:
            if c.fecha and c.fecha.year >= 2026 and c.fecha.month in costos:
                costos[c.fecha.month] += (c.costo_pm_clp or 0)
                
        kpis = {
            'total': len(eqs_db),
            'operativos': conteo_estado.get('Operativo', 0),
            'atrasados': len(criticos),
            'ot_abiertas': len([o for o in ots_db if o.estado != 'Finalizada']),
            'costo_mes_str': format_clp(costos.get(mes_actual, 0))
        }
        
        charts = {
            'estado': conteo_estado,
            'costos_mensuales': {'labels': ['Feb', 'Mar', 'Abr', 'May', 'Jun'], 'data': list(costos.values())}
        }
        
        return render_template('index.html', kpis=kpis, charts=charts, eqs=equipos_dict, 
                               criticos=criticos, taller=taller,
                               mantenciones=todas_mants, compras=todas_compras, 
                               lecturas=todas_lecturas, kanban=kanban_tareas, logs=logs_list, 
                               equipos_aleatorios=equipos_aleatorios, operadores=operadores, current_user="Admin")
    except Exception as e:
        return f"<h1>Error en Dashboard:</h1><pre>{str(e)}</pre><p>Por favor, revisa que todas las tablas tengan información válida o toma captura de este error.</p>"

# ==========================================
# RUTAS DE CONTROL (CRUD TOTAL)
# ==========================================
@app.route('/api/add_record', methods=['POST'])
def add_record():
    tabla = request.form.get('tabla')
    
    if tabla == 'lectura':
        val = clean_int(request.form.get('valor'))
        ctrl = request.form.get('control', 'HR')
        nueva = HistorialLectura(
            codigo_equipo=request.form.get('codigo'),
            horometro=val if ctrl == 'HR' else 0,
            kilometraje=val if ctrl == 'KM' else 0,
            observacion=request.form.get('observacion', ''),
            fecha=datetime.now()
        )
        db.session.add(nueva)
        eq = Equipo.query.filter_by(codigo=request.form.get('codigo')).first()
        if eq: eq.lectura_actual = val

    elif tabla == 'ot':
        nueva = OrdenTrabajo(
            codigo_equipo=request.form.get('codigo'),
            folio=request.form.get('folio', f"OT-DMT-{random.randint(1000,9999)}"),
            tipo_mantencion=request.form.get('tipo', ''),
            costo_mantencion_clp=clean_int(request.form.get('costo')),
            estado=request.form.get('estado', 'Pendiente'),
            fecha=datetime.now()
        )
        db.session.add(nueva)

    elif tabla == 'compra':
        nueva = CompraRepuesto(
            codigo_equipo=request.form.get('codigo'),
            oc=request.form.get('oc', ''),
            descripcion=request.form.get('descripcion', ''),
            costo_pm_clp=clean_int(request.form.get('costo')),
            fecha=datetime.now()
        )
        db.session.add(nueva)

    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/api/delete_record/<tabla>/<int:id>', methods=['POST'])
def delete_record(tabla, id):
    if tabla == 'lectura': obj = HistorialLectura.query.get(id)
    elif tabla == 'ot': obj = OrdenTrabajo.query.get(id)
    elif tabla == 'compra': obj = CompraRepuesto.query.get(id)
    else: return jsonify({"status": "error"}), 400
        
    if obj:
        db.session.delete(obj)
        db.session.commit()
        return jsonify({"status": "success"})
    return jsonify({"status": "not_found"}), 404

@app.route('/update_inline', methods=['POST'])
def update_inline():
    data = request.json
    tabla = data.get('tabla', 'equipo')
    cod = data.get('codigo')
    campo = data.get('campo')
    valor = data.get('valor')

    if tabla == 'equipo': obj = Equipo.query.filter_by(codigo=cod).first()
    elif tabla == 'lectura': obj = HistorialLectura.query.get(cod)
    elif tabla == 'ot': obj = OrdenTrabajo.query.get(cod)
    elif tabla == 'compra': obj = CompraRepuesto.query.get(cod)
    elif tabla == 'personal': obj = Personal.query.get(cod)
    else: return jsonify({"status": "error"})

    if obj:
        if 'costo' in campo or 'lectura' in campo or 'horometro' in campo or 'kilometraje' in campo:
            valor = clean_int(valor)
        setattr(obj, campo, valor)
        db.session.commit()
        return jsonify({"status": "success"})
    return jsonify({"status": "error"}), 404

# ==========================================
# FICHA DE EQUIPO E IMPRESIÓN
# ==========================================
@app.route('/equipo/<codigo>', strict_slashes=False)
def ficha_equipo(codigo):
    equipo = Equipo.query.filter_by(codigo=codigo).first_or_404()
    
    vin_texto = equipo.vin if equipo.vin and str(equipo.vin).lower() not in ["none", "nan", ""] else "S/I"
    motor_texto = equipo.n_motor if equipo.n_motor and str(equipo.n_motor).lower() not in ["none", "nan", ""] else "S/I"
    patente_texto = equipo.patente if equipo.patente and str(equipo.patente).lower() not in ["none", "nan", ""] else "S/P"
    
    desc_tecnica = f"Unidad {equipo.tipo_equipo} marca {equipo.marca} {equipo.modelo}. Identificación de chasis (VIN): {vin_texto}. Número de Motor: {motor_texto}."
    
    mants_db = OrdenTrabajo.query.filter_by(codigo_equipo=codigo).order_by(OrdenTrabajo.id.desc()).all()
    compras_db = CompraRepuesto.query.filter_by(codigo_equipo=codigo).order_by(CompraRepuesto.fecha.desc()).all()
    lecturas_db = HistorialLectura.query.filter_by(codigo_equipo=codigo).order_by(HistorialLectura.fecha.desc()).limit(5).all()

    mants = [{'fecha': m.fecha.strftime('%d/%m/%Y') if m.fecha else 'S/F', 'tipo': m.tipo_mantencion, 'costo_str': format_clp(m.costo_mantencion_clp), 'estado': m.estado, 'folio': m.folio} for m in mants_db]
    compras = [{'fecha': c.fecha.strftime('%d/%m/%Y') if c.fecha else 'S/F', 'oc': c.oc, 'descripcion': c.descripcion, 'costo_str': format_clp(c.costo_pm_clp), 'proveedor': c.proveedor} for c in compras_db]
    lecturas = [{'fecha': l.fecha.strftime('%d/%m/%Y %H:%M') if l.fecha else 'S/F', 'valor': format_num(max(l.horometro or 0, l.kilometraje or 0)), 'tipo': 'HR' if (l.horometro and l.horometro > 0) else 'KM', 'obs': l.observacion} for l in lecturas_db]

    return render_template('ficha_equipo.html', eq=equipo, desc_tecnica=desc_tecnica, foto_url=buscar_foto_por_tipo(equipo.tipo_equipo, equipo.marca), mants=mants, compras=compras, lecturas=lecturas)

@app.route('/imprimir_ot/<codigo>', strict_slashes=False)
def imprimir_ot(codigo):
    equipo = Equipo.query.filter_by(codigo=codigo).first_or_404()
    ot = OrdenTrabajo.query.filter_by(codigo_equipo=codigo).order_by(OrdenTrabajo.id.desc()).first()
    ot_data = {'folio': ot.folio if (ot and ot.folio and str(ot.folio).lower() != 'none') else f"OT-DMT-0{random.randint(2000, 9000)}", 'tipo_mantencion': ot.tipo_mantencion if (ot and ot.tipo_mantencion) else "MANTENIMIENTO PREVENTIVO 250 HRS"}
    return render_template('ot_print.html', equipo=equipo, ot=ot_data, fecha_actual=datetime.now().strftime("%d/%m/%Y"))


# ==========================================
# INYECCIÓN AUTOMÁTICA DESDE EXCEL
# ==========================================
@app.route('/admin/cargar_sql_final', strict_slashes=False)
def cargar_sql_final():
    try:
        archivos = os.listdir('.')
        excel_principal = next((f for f in archivos if "CMMS" in f.upper() and f.endswith(('.xlsx', '.xls')) and not f.startswith('~$')), None)
        archivo_filtros = next((f for f in archivos if "filtro" in f.lower() and f.endswith(('.xlsx', '.csv')) and not f.startswith('~$')), None)

        if not excel_principal: return "<h1>Error:</h1> Falta el archivo principal CMMS DEMOTRON (.xlsx)."

        db.session.query(OrdenTrabajo).delete()
        db.session.query(CompraRepuesto).delete()
        db.session.query(HistorialLectura).delete()
        db.session.query(Equipo).delete()
        db.session.commit()

        # 1. CARGA DE EQUIPOS
        df_eq = pd.read_excel(excel_principal, engine='openpyxl', sheet_name="Equipos", skiprows=2).replace({np.nan: None})
        for _, row in df_eq.iterrows():
            if not row.iloc[0]: continue
            eq = Equipo(codigo=str(row.iloc[0]).strip(), tipo_equipo=row.iloc[1], marca=row.iloc[2], 
                        modelo=str(row.iloc[3]), ubicacion=row.iloc[5], responsable=row.iloc[6],
                        estado_base=str(row.iloc[7]).strip() if row.iloc[7] else 'Operativo',
                        control_base=str(row.iloc[8]).strip() if row.iloc[8] else 'HORAS', 
                        frecuencia_base=clean_int(row.iloc[9], 250))
            db.session.add(eq)
        db.session.commit()

        # 2. CARGA INTELIGENTE DE FILTROS DESDE EL NUEVO EXCEL
        if archivo_filtros:
            if archivo_filtros.endswith('.xlsx'):
                df_fil = pd.read_excel(archivo_filtros, engine='openpyxl')
            else:
                df_fil = pd.read_csv(archivo_filtros)
            
            df_fil = df_fil.replace({np.nan: "-"})
            
            for _, row in df_fil.iterrows():
                try:
                    cod = str(row.iloc[0]).strip()
                    eq = Equipo.query.filter_by(codigo=cod).first()
                    if eq:
                        info = []
                        for col_name in df_fil.columns[1:]:
                            if col_name.upper() != 'CANT' and str(row[col_name]).strip() != "-":
                                info.append(f"{col_name}: {row[col_name]}")
                        
                        texto_filtro = " | ".join(info)
                        if "Registrar" in eq.pauta_filtros: eq.pauta_filtros = texto_filtro
                        else: eq.pauta_filtros += "\n" + texto_filtro
                except: pass
            db.session.commit()

        # 3. CARGA DE RESTO DE TABLAS
        df_lec = pd.read_excel(excel_principal, engine='openpyxl', sheet_name="Lecturas", skiprows=2).replace({np.nan: None})
        for _, row in df_lec.iterrows():
            if not row.iloc[1]: continue
            try: fecha_dt = datetime.strptime(str(row.iloc[0]).split()[0], "%Y-%m-%d")
            except: fecha_dt = datetime.now()
            db.session.add(HistorialLectura(fecha=fecha_dt, codigo_equipo=str(row.iloc[1]).strip(), horometro=clean_int(row.iloc[2], 0), kilometraje=clean_int(row.iloc[3], 0), obra_ubicacion=row.iloc[4], responsable=row.iloc[5], observacion=row.iloc[6]))

        df_man = pd.read_excel(excel_principal, engine='openpyxl', sheet_name="Mantenciones", skiprows=2).replace({np.nan: None})
        for _, row in df_man.iterrows():
            if not row.iloc[1]: continue
            try: fecha_dt = datetime.strptime(str(row.iloc[0]).split()[0], "%Y-%m-%d")
            except: fecha_dt = datetime.now()
            db.session.add(OrdenTrabajo(fecha=fecha_dt, codigo_equipo=str(row.iloc[1]).strip(), tipo_mantencion=str(row.iloc[2]).strip(), lectura=clean_int(row.iloc[3], 0), es_pm=row.iloc[4], folio=str(row.iloc[5]), lugar=row.iloc[6], costo_mantencion_clp=clean_float(row.iloc[8], 0.0), estado=row.iloc[9] if row.iloc[9] else 'Finalizada'))

        df_com = pd.read_excel(excel_principal, engine='openpyxl', sheet_name="Compras PM", skiprows=2).replace({np.nan: None})
        for _, row in df_com.iterrows():
            if not row.iloc[2]: continue
            try: fecha_dt = datetime.strptime(str(row.iloc[0]).split()[0], "%Y-%m-%d")
            except: fecha_dt = datetime.now()
            db.session.add(CompraRepuesto(fecha=fecha_dt, oc=str(row.iloc[1]), codigo_equipo=str(row.iloc[2]).strip(), descripcion=row.iloc[3], proveedor=row.iloc[4], costo_pm_clp=clean_float(row.iloc[5], 0.0)))
        
        db.session.commit()

        for eq in Equipo.query.all():
            u_lec = HistorialLectura.query.filter_by(codigo_equipo=eq.codigo).order_by(HistorialLectura.fecha.desc(), HistorialLectura.id.desc()).first()
            if u_lec: eq.lectura_actual = u_lec.horometro if eq.control_base == 'HORAS' else u_lec.kilometraje
            u_pm = OrdenTrabajo.query.filter_by(codigo_equipo=eq.codigo, estado='Finalizada').order_by(OrdenTrabajo.fecha.desc()).first()
            if u_pm: eq.proxima_pm = u_pm.lectura + eq.frecuencia_base
            else: eq.proxima_pm = eq.lectura_actual + eq.frecuencia_base
        db.session.commit()

        return "<h1>Carga Exitosa</h1><p>Equipos, Mantenimientos y Filtros vinculados.</p><a href='/'>Ir al Dashboard</a>"
    except Exception as e:
        return f"<h1>Error Crítico:</h1><pre>{str(e)}</pre>"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
