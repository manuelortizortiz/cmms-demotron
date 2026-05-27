import os
import random
import pandas as pd
import numpy as np
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash

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
    eqs = Equipo.query.all()
    ots = OrdenTrabajo.query.order_by(OrdenTrabajo.id.desc()).all()
    compras = CompraRepuesto.query.order_by(CompraRepuesto.fecha.desc()).all()
    lecturas = HistorialLectura.query.order_by(HistorialLectura.id.desc()).all()
    operadores = Personal.query.filter_by(cargo='Operador').all()
    
    # Costos Mensuales
    mes_actual = datetime.now().month
    costos = {2:0, 3:0, 4:0, 5:0, 6:0}
    for ot in ots:
        if ot.fecha and ot.fecha.year == 2026 and ot.fecha.month in costos:
            costos[ot.fecha.month] += (ot.costo_mantencion_clp or 0)
    for c in compras:
        if c.fecha and c.fecha.year == 2026 and c.fecha.month in costos:
            costos[c.fecha.month] += (c.costo_pm_clp or 0)
            
    # Preparar KPIs
    kpis = {
        'total': len(eqs),
        'operativos': len([e for e in eqs if e.estado_base == 'Operativo']),
        'atrasados': len([e for e in eqs if e.margen < 0]),
        'ot_abiertas': len([o for o in ots if o.estado != 'Finalizada']),
        'costo_mes_str': format_clp(costos.get(mes_actual, 0))
    }
    
    # Preparar diccionarios para Jinja
    equipos_dict = []
    for e in eqs:
        equipos_dict.append({
            'codigo': e.codigo, 'tipo': e.tipo_equipo, 'marca': e.marca, 'modelo': e.modelo,
            'ubicacion': e.ubicacion, 'responsable': e.responsable, 'ctrl': e.control_base,
            'lectura': format_num(e.lectura_actual), 'margen': e.margen, 
            'margen_str': format_num(e.margen), 'estado': e.estado_base,
            'vin': e.vin, 'motor': e.n_motor, 'patente': e.patente,
            'foto_url': buscar_foto_por_tipo(e.tipo_equipo, e.marca)
        })

    todas_mants = [{'id': m.id, 'fecha': m.fecha.strftime('%d/%m/%Y'), 'fecha_iso': m.fecha.strftime('%Y-%m-%d'), 'codigo': m.codigo_equipo, 'ot_generada': m.folio, 'tipo_mantencion': m.tipo_mantencion, 'costo_str': format_clp(m.costo_mantencion_clp), 'estado': m.estado, 'lectura_str': format_num(m.lectura)} for m in ots]
    todas_compras = [{'id': c.id, 'fecha': c.fecha.strftime('%d/%m/%Y'), 'oc': c.oc, 'codigo': c.codigo_equipo, 'descripcion': c.descripcion, 'costo_str': format_clp(c.costo_pm_clp)} for c in compras]
    todas_lecturas = [{'id': l.id, 'fecha': l.fecha.strftime('%d/%m/%Y'), 'codigo': l.codigo_equipo, 'valor_str': format_num(max(l.horometro, l.kilometraje)), 'tipo': 'HR' if l.horometro > 0 else 'KM', 'obs': l.observacion, 'responsable': l.responsable, 'ubicacion': l.obra_ubicacion} for l in lecturas]
    
    charts = {'costos': {'labels': ['Feb', 'Mar', 'Abr', 'May', 'Jun'], 'data': list(costos.values())}}
    
    return render_template('index.html', kpis=kpis, charts=charts, eqs=equipos_dict, 
                           mantenciones=todas_mants, compras=todas_compras, 
                           lecturas=todas_lecturas, operadores=operadores, current_user="Admin Principal")

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
        
        # Actualizar lectura en equipo
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
    if tabla == 'lectura':
        obj = HistorialLectura.query.get(id)
    elif tabla == 'ot':
        obj = OrdenTrabajo.query.get(id)
    elif tabla == 'compra':
        obj = CompraRepuesto.query.get(id)
    else:
        return jsonify({"status": "error"}), 400
        
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
    else: return jsonify({"status": "error"})

    if obj:
        if 'costo' in campo or 'lectura' in campo or 'horometro' in campo or 'kilometraje' in campo:
            valor = clean_int(valor)
        setattr(obj, campo, valor)
        db.session.commit()
        return jsonify({"status": "success"})
    return jsonify({"status": "error"}), 404

# ==========================================
# INYECCIÓN AUTOMÁTICA DESDE EXCEL
# ==========================================
@app.route('/admin/cargar_sql_final', strict_slashes=False)
def cargar_sql_final():
    try:
        archivos = os.listdir('.')
        excel_principal = next((f for f in archivos if "CMMS" in f.upper()), None)
        archivo_filtros = next((f for f in archivos if "filtro" in f.lower() and f.endswith(('.xlsx', '.csv'))), None)

        if not excel_principal: return "<h1>Error:</h1> Falta el archivo principal CMMS DEMOTRON."

        db.session.query(OrdenTrabajo).delete()
        db.session.query(CompraRepuesto).delete()
        db.session.query(HistorialLectura).delete()
        db.session.query(Equipo).delete()
        db.session.commit()

        # 1. CARGA DE EQUIPOS
        df_eq = pd.read_excel(excel_principal, sheet_name="Equipos", skiprows=2).replace({np.nan: None})
        for _, row in df_eq.iterrows():
            if not row.iloc[0]: continue
            eq = Equipo(codigo=str(row.iloc[0]).strip(), tipo_equipo=row.iloc[1], marca=row.iloc[2], 
                        modelo=str(row.iloc[3]), ubicacion=row.iloc[5], responsable=row.iloc[6],
                        control_base=str(row.iloc[8]).strip() if row.iloc[8] else 'HORAS', 
                        frecuencia_base=clean_int(row.iloc[9], 250))
            db.session.add(eq)
        db.session.commit()

        # 2. CARGA INTELIGENTE DE FILTROS DESDE EL NUEVO EXCEL
        if archivo_filtros:
            df_fil = pd.read_excel(archivo_filtros) if archivo_filtros.endswith('.xlsx') else pd.read_csv(archivo_filtros)
            df_fil = df_fil.replace({np.nan: "-"})
            
            for _, row in df_fil.iterrows():
                try:
                    cod = str(row.iloc[0]).strip()
                    eq = Equipo.query.filter_by(codigo=cod).first()
                    if eq:
                        # Extraemos las columnas de la fila omitiendo Código y CANT para armar un párrafo limpio
                        info = []
                        for col_name in df_fil.columns[1:]:
                            if col_name.upper() != 'CANT' and row[col_name] != "-":
                                info.append(f"{col_name}: {row[col_name]}")
                        
                        texto_filtro = " | ".join(info)
                        
                        # Si ya tenía texto, se lo sumamos (porque son varias filas por equipo)
                        if "Registrar" in eq.pauta_filtros: eq.pauta_filtros = texto_filtro
                        else: eq.pauta_filtros += "\n" + texto_filtro
                except: pass
            db.session.commit()

        return "<h1>Carga Exitosa</h1><p>Equipos y Filtros vinculados.</p><a href='/'>Ir al Dashboard</a>"
    except Exception as e:
        return f"<h1>Error Crítico:</h1><pre>{str(e)}</pre>"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
