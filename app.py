from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from sqlalchemy import create_engine, text
from datetime import datetime
import os

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'demotron-cmms-pro-ui')
DATABASE_URL = os.environ.get('DATABASE_URL', '')
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://','postgresql://',1)
if DATABASE_URL:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
else:
    os.makedirs('data', exist_ok=True)
    engine = create_engine('sqlite:///data/cmms_local.db', future=True)

def is_pg(): return bool(DATABASE_URL)
def id_col(): return 'SERIAL PRIMARY KEY' if is_pg() else 'INTEGER PRIMARY KEY AUTOINCREMENT'
def real_col(): return 'DOUBLE PRECISION' if is_pg() else 'REAL'
def exec_sql(sql, params=None):
    with engine.begin() as conn: conn.execute(text(sql), params or {})
def rows(sql, params=None):
    with engine.begin() as conn: return [dict(r._mapping) for r in conn.execute(text(sql), params or {})]
def one(sql, params=None):
    with engine.begin() as conn: return conn.execute(text(sql), params or {}).mappings().first()

def calc_estado(freq, lectura, ultima_pm, estado_operacional):
    op = str(estado_operacional or '').upper()
    if 'FUERA' in op: return 'FUERA DE SERVICIO','gray',0,0
    if 'TALLER' in op: return 'EN TALLER','gray',0,0
    freq, lectura, ultima_pm = float(freq or 0), float(lectura or 0), float(ultima_pm or 0)
    proxima = ultima_pm + freq if ultima_pm > 0 and freq > 0 else 0
    margen = proxima - lectura if proxima > 0 and lectura > 0 else 0
    if freq <= 0 or lectura <= 0 or ultima_pm <= 0: return 'SIN HISTORIAL','orange',proxima,margen
    if margen < 0: return 'ATRASADA','red',proxima,margen
    if margen <= max(15, freq*0.10): return 'PRÓXIMA','orange',proxima,margen
    return 'AL DÍA','green',proxima,margen

def tipo_img(e):
    s = f"{e.get('codigo','')} {e.get('familia','')} {e.get('descripcion','')} {e.get('marca','')}".lower()
    if 'tolva' in s or s.startswith('cd'): return 'tolva.svg'
    if 'motoniveladora' in s or 'grader' in s: return 'motoniveladora.svg'
    if 'cargador' in s or 'loader' in s or 'wa' in s: return 'cargador.svg'
    if 'camioneta' in s or s.startswith('vd'): return 'camioneta.svg'
    if 'excav' in s or s.startswith('md'): return 'excavadora.svg'
    return 'equipo.svg'

def guardar_equipo(data):
    estado, semaforo, proxima, margen = calc_estado(data.get('frecuencia_base'), data.get('lectura_actual'), data.get('ultima_pm'), data.get('estado_operacional'))
    desc = data.get('descripcion') or f"{data.get('familia','')} {data.get('marca','')} {data.get('modelo','')}".strip()
    if not str(data.get('codigo','')).strip(): return
    upsert = 'ON CONFLICT (codigo) DO UPDATE SET tipo_equipo=excluded.tipo_equipo,familia=excluded.familia,marca=excluded.marca,modelo=excluded.modelo,descripcion=excluded.descripcion,ubicacion=excluded.ubicacion,control_base=excluded.control_base,frecuencia_base=excluded.frecuencia_base,lectura_actual=excluded.lectura_actual,ultima_pm=excluded.ultima_pm,proxima_pm=excluded.proxima_pm,margen=excluded.margen,costo_total_pm=excluded.costo_total_pm,estado_operacional=excluded.estado_operacional,estado_calculado=excluded.estado_calculado,semaforo=excluded.semaforo,fecha_actualizacion=excluded.fecha_actualizacion' if is_pg() else 'ON CONFLICT(codigo) DO UPDATE SET tipo_equipo=excluded.tipo_equipo,familia=excluded.familia,marca=excluded.marca,modelo=excluded.modelo,descripcion=excluded.descripcion,ubicacion=excluded.ubicacion,control_base=excluded.control_base,frecuencia_base=excluded.frecuencia_base,lectura_actual=excluded.lectura_actual,ultima_pm=excluded.ultima_pm,proxima_pm=excluded.proxima_pm,margen=excluded.margen,costo_total_pm=excluded.costo_total_pm,estado_operacional=excluded.estado_operacional,estado_calculado=excluded.estado_calculado,semaforo=excluded.semaforo,fecha_actualizacion=excluded.fecha_actualizacion'
    exec_sql(f'''INSERT INTO equipos(codigo,tipo_equipo,familia,marca,modelo,descripcion,ubicacion,control_base,frecuencia_base,lectura_actual,ultima_pm,proxima_pm,margen,costo_total_pm,estado_operacional,estado_calculado,semaforo,fecha_actualizacion)
    VALUES(:codigo,:tipo_equipo,:familia,:marca,:modelo,:descripcion,:ubicacion,:control_base,:frecuencia_base,:lectura_actual,:ultima_pm,:proxima_pm,:margen,:costo_total_pm,:estado_operacional,:estado_calculado,:semaforo,:fecha_actualizacion) {upsert}''',
    dict(codigo=str(data.get('codigo','')).strip(), tipo_equipo=data.get('tipo_equipo',''), familia=data.get('familia',''), marca=data.get('marca',''), modelo=data.get('modelo',''), descripcion=desc, ubicacion=data.get('ubicacion',''), control_base=data.get('control_base','HORAS'), frecuencia_base=float(data.get('frecuencia_base') or 0), lectura_actual=float(data.get('lectura_actual') or 0), ultima_pm=float(data.get('ultima_pm') or 0), proxima_pm=proxima, margen=margen, costo_total_pm=float(data.get('costo_total_pm') or 0), estado_operacional=data.get('estado_operacional','OPERATIVO'), estado_calculado=estado, semaforo=semaforo, fecha_actualizacion=datetime.now().strftime('%Y-%m-%d %H:%M')))

def init_db():
    idt, real = id_col(), real_col()
    exec_sql(f"CREATE TABLE IF NOT EXISTS usuarios(id {idt}, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, rol TEXT NOT NULL, activo INTEGER DEFAULT 1)")
    exec_sql(f"CREATE TABLE IF NOT EXISTS equipos(id {idt}, codigo TEXT UNIQUE NOT NULL, tipo_equipo TEXT, familia TEXT, marca TEXT, modelo TEXT, descripcion TEXT, ubicacion TEXT, control_base TEXT, frecuencia_base {real} DEFAULT 0, lectura_actual {real} DEFAULT 0, ultima_pm {real} DEFAULT 0, proxima_pm {real} DEFAULT 0, margen {real} DEFAULT 0, costo_total_pm {real} DEFAULT 0, estado_operacional TEXT DEFAULT 'OPERATIVO', estado_calculado TEXT, semaforo TEXT, fecha_actualizacion TEXT)")
    exec_sql(f"CREATE TABLE IF NOT EXISTS ot(id {idt}, numero TEXT UNIQUE, codigo TEXT, tipo TEXT, prioridad TEXT, estado TEXT, fecha_creacion TEXT, lectura {real} DEFAULT 0, descripcion TEXT, responsable TEXT, costo_estimado {real} DEFAULT 0)")
    exec_sql(f"CREATE TABLE IF NOT EXISTS lecturas(id {idt}, fecha TEXT, codigo TEXT, tipo_lectura TEXT, valor {real} DEFAULT 0, ubicacion TEXT, responsable TEXT, observacion TEXT)")
    exec_sql(f"CREATE TABLE IF NOT EXISTS compras(id {idt}, fecha TEXT, codigo_equipo TEXT, oc TEXT, proveedor TEXT, item TEXT, cantidad {real} DEFAULT 0, costo_total {real} DEFAULT 0, estado TEXT, observacion TEXT)")
    exec_sql(f"CREATE TABLE IF NOT EXISTS bodega(id {idt}, fecha TEXT, codigo_equipo TEXT, ot_numero TEXT, repuesto TEXT, cantidad {real} DEFAULT 0, costo_unitario {real} DEFAULT 0, movimiento TEXT, observacion TEXT)")
    if one('SELECT COUNT(*) n FROM usuarios')['n'] == 0:
        for u,p,r in [('admin','admin123','Administrador'),('gerencia','gerencia123','Gerencia'),('mantencion','mantencion123','Mantención'),('bodega','bodega123','Bodega'),('lectura','lectura123','Lecturas')]:
            exec_sql('INSERT INTO usuarios(username,password_hash,rol,activo) VALUES(:u,:p,:r,1)', {'u':u,'p':generate_password_hash(p),'r':r})
    if one('SELECT COUNT(*) n FROM equipos')['n'] == 0: seed_demo()

def seed_demo():
    demo=[('MD-01','Maquinaria Pesada','Motoniveladora','CAT','140K','Motoniveladora CAT 140K','Q-459','HORAS',250,1850,1700,0,'OPERATIVO'),('MD-02','Maquinaria Pesada','Motoniveladora','CAT','120K','Motoniveladora CAT 120K','Faena Norte','HORAS',250,1920,1750,0,'OPERATIVO'),('MD-03','Maquinaria Pesada','Motoniveladora','CAT','140K','Motoniveladora CAT 140K','Taltal','HORAS',250,2150,1950,0,'OPERATIVO'),('MD-04','Maquinaria Pesada','Motoniveladora','CAT','160K','Motoniveladora CAT 160K','Q-459','HORAS',250,2100,1750,0,'OPERATIVO'),('MD-05','Maquinaria Pesada','Motoniveladora','CAT','140K','Motoniveladora CAT 140K','Faena Norte','HORAS',250,1980,1650,0,'OPERATIVO'),('CD-100','Camión','Excavadora','SANY','55T','Excavadora SANY 55T','Q-459','HORAS',250,2350,2000,0,'OPERATIVO'),('CD-101','Camión','Excavadora','SANY','75T','Excavadora SANY 75T','Taltal','HORAS',250,3200,3050,0,'OPERATIVO'),('CD-102','Camión','Tolva','MAN','40400','Camión Tolva MAN 40400','Q-459','KM',15000,250000,247500,0,'OPERATIVO'),('CD-110','Camión','Excavadora','SANY','75T','Excavadora SANY 75T','Q-459','HORAS',250,3950,3600,0,'OPERATIVO'),('VD-22','Compactación','Vibrocompactador','BOMAG','','Vibrocompactador BOMAG','Taltal','HORAS',250,2100,1750,0,'OPERATIVO')]
    for d in demo: guardar_equipo(dict(zip(['codigo','tipo_equipo','familia','marca','modelo','descripcion','ubicacion','control_base','frecuencia_base','lectura_actual','ultima_pm','costo_total_pm','estado_operacional'],d)))

def login_required(fn):
    @wraps(fn)
    def w(*a,**kw):
        if 'user' not in session: return redirect(url_for('login'))
        return fn(*a,**kw)
    return w

def equipos_list():
    return rows("SELECT * FROM equipos ORDER BY CASE WHEN codigo LIKE 'MD-%' THEN 1 WHEN codigo LIKE 'CD-%' THEN 2 WHEN codigo LIKE 'VD-%' THEN 3 ELSE 4 END, codigo")

def kpis(eqs, ots, compras):
    total=len(eqs); atras=sum(e.get('semaforo')=='red' for e in eqs); prox=sum(e.get('semaforo')=='orange' for e in eqs); fuera=sum(e.get('semaforo')=='gray' for e in eqs)
    return dict(total=total, atrasados=atras, proximos=prox, fuera=fuera, controlado=round(((total-atras-fuera)/total*100),1) if total else 0, ot_abiertas=sum(str(o.get('estado','')).upper()!='CERRADA' for o in ots), compras_proceso=sum('PROCESO' in str(c.get('estado','')).upper() for c in compras), compras_monto=int(sum(float(c.get('costo_total') or 0) for c in compras)), costo_total=int(sum(float(e.get('costo_total_pm') or 0) for e in eqs)))

def dash_context(page='dashboard'):
    eqs=equipos_list(); ots=rows('SELECT * FROM ot ORDER BY id DESC'); compras=rows('SELECT * FROM compras ORDER BY id DESC'); lecturas=rows('SELECT * FROM lecturas ORDER BY id DESC'); bodega=rows('SELECT * FROM bodega ORDER BY id DESC')
    kp=kpis(eqs,ots,compras); ubic={}
    for e in eqs:
        e['img']=tipo_img(e)
        if e.get('semaforo')=='red': ubic[e.get('ubicacion') or 'Sin ubicación']=ubic.get(e.get('ubicacion') or 'Sin ubicación',0)+1
    return dict(page=page, equipos=eqs, criticos=[e for e in eqs if e.get('semaforo') in ('red','orange')][:8], ots=ots, compras=compras, lecturas=lecturas, bodega=bodega, kpis=kp, ubicaciones=[{'ubicacion':k,'cantidad':v} for k,v in sorted(ubic.items(), key=lambda x:x[1], reverse=True)[:5]], current_user=session.get('user'), current_role=session.get('rol'), version_sistema='1.0.0', anio_actual=datetime.now().year)

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        u=one('SELECT * FROM usuarios WHERE username=:u AND activo=1', {'u':request.form.get('username','').strip()})
        if u and check_password_hash(u['password_hash'], request.form.get('password','')):
            session['user']=u['username']; session['rol']=u['rol']; return redirect(url_for('index'))
        flash('Usuario o contraseña incorrectos')
    return render_template('login.html')
@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))
@app.route('/')
@login_required
def index(): return render_template('index.html', **dash_context('dashboard'))
@app.route('/equipos')
@login_required
def equipos_page(): return render_template('equipos.html', **dash_context('equipos'))
@app.route('/lecturas')
@login_required
def lecturas_page(): return render_template('lecturas.html', **dash_context('lecturas'))
@app.route('/ot')
@login_required
def ot_page(): return render_template('ot.html', **dash_context('ot'))
@app.route('/compras')
@login_required
def compras_page(): return render_template('compras.html', **dash_context('compras'))
@app.route('/bodega')
@login_required
def bodega_page(): return render_template('bodega.html', **dash_context('bodega'))
@app.route('/reportes')
@login_required
def reportes_page(): return render_template('reportes.html', **dash_context('reportes'))
@app.route('/configuracion')
@login_required
def config_page(): return render_template('configuracion.html', **dash_context('configuracion'))

@app.route('/equipos/guardar', methods=['POST'])
@login_required
def equipos_guardar(): guardar_equipo(request.form); flash('Equipo guardado.'); return redirect(url_for('equipos_page'))
@app.route('/ot/guardar', methods=['POST'])
@login_required
def ot_guardar():
    n=one('SELECT COUNT(*) n FROM ot')['n']+1
    exec_sql("INSERT INTO ot(numero,codigo,tipo,prioridad,estado,fecha_creacion,lectura,descripcion,responsable,costo_estimado) VALUES(:numero,:codigo,:tipo,:prioridad,:estado,:fecha,:lectura,:descripcion,:responsable,:costo)", dict(numero=f'OT-{n:05d}', codigo=request.form.get('codigo'), tipo=request.form.get('tipo','Preventiva'), prioridad=request.form.get('prioridad','Media'), estado=request.form.get('estado','ABIERTA'), fecha=datetime.now().strftime('%Y-%m-%d %H:%M'), lectura=float(request.form.get('lectura') or 0), descripcion=request.form.get('descripcion',''), responsable=request.form.get('responsable',''), costo=float(request.form.get('costo_estimado') or 0)))
    flash('OT creada.'); return redirect(url_for('ot_page'))
@app.route('/lecturas/guardar', methods=['POST'])
@login_required
def lectura_guardar():
    codigo=request.form.get('codigo','').strip(); valor=float(request.form.get('valor') or 0); ubic=request.form.get('ubicacion','').strip()
    exec_sql('INSERT INTO lecturas(fecha,codigo,tipo_lectura,valor,ubicacion,responsable,observacion) VALUES(:fecha,:codigo,:tipo,:valor,:ubicacion,:responsable,:obs)', dict(fecha=datetime.now().strftime('%Y-%m-%d %H:%M'), codigo=codigo, tipo=request.form.get('tipo_lectura','HOROMETRO'), valor=valor, ubicacion=ubic, responsable=request.form.get('responsable',''), obs=request.form.get('observacion','')))
    eq=one('SELECT * FROM equipos WHERE codigo=:c', {'c':codigo})
    if eq:
        data=dict(eq); data['lectura_actual']=valor
        if ubic: data['ubicacion']=ubic
        guardar_equipo(data)
    flash('Lectura registrada.'); return redirect(url_for('lecturas_page'))
@app.route('/compras/guardar', methods=['POST'])
@login_required
def compra_guardar():
    exec_sql('INSERT INTO compras(fecha,codigo_equipo,oc,proveedor,item,cantidad,costo_total,estado,observacion) VALUES(:fecha,:codigo,:oc,:proveedor,:item,:cantidad,:costo,:estado,:obs)', dict(fecha=datetime.now().strftime('%Y-%m-%d %H:%M'), codigo=request.form.get('codigo_equipo',''), oc=request.form.get('oc',''), proveedor=request.form.get('proveedor',''), item=request.form.get('item',''), cantidad=float(request.form.get('cantidad') or 0), costo=float(request.form.get('costo_total') or 0), estado=request.form.get('estado','EN PROCESO'), obs=request.form.get('observacion','')))
    flash('Compra guardada.'); return redirect(url_for('compras_page'))
@app.route('/bodega/guardar', methods=['POST'])
@login_required
def bodega_guardar():
    exec_sql('INSERT INTO bodega(fecha,codigo_equipo,ot_numero,repuesto,cantidad,costo_unitario,movimiento,observacion) VALUES(:fecha,:codigo,:ot,:rep,:cant,:costo,:mov,:obs)', dict(fecha=datetime.now().strftime('%Y-%m-%d %H:%M'), codigo=request.form.get('codigo_equipo',''), ot=request.form.get('ot_numero',''), rep=request.form.get('repuesto',''), cant=float(request.form.get('cantidad') or 0), costo=float(request.form.get('costo_unitario') or 0), mov=request.form.get('movimiento','SALIDA'), obs=request.form.get('observacion','')))
    flash('Movimiento guardado.'); return redirect(url_for('bodega_page'))
@app.route('/seed')
@login_required
def seed(): seed_demo(); flash('Datos demo cargados.'); return redirect(url_for('index'))
@app.route('/health')
def health(): return jsonify({'database':'postgresql' if DATABASE_URL else 'sqlite','status':'ok'})

try: init_db()
except Exception as e: print('ERROR INIT DB:', e)
if __name__ == '__main__': app.run(host='0.0.0.0', port=int(os.environ.get('PORT',5000)))
