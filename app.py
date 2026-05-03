from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from sqlalchemy import create_engine, text
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY','demotron-cmms-final')
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL and DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://','postgresql://',1)
if DATABASE_URL:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
else:
    os.makedirs('data', exist_ok=True)
    engine = create_engine('sqlite:///data/cmms_empresa.db', future=True)

def is_postgres(): return bool(DATABASE_URL)
def id_type(): return 'SERIAL PRIMARY KEY' if is_postgres() else 'INTEGER PRIMARY KEY AUTOINCREMENT'
def real_type(): return 'DOUBLE PRECISION' if is_postgres() else 'REAL'

DEFAULT_USERS=[('admin','admin123','Administrador'),('gerencia','gerencia123','Gerencia'),('mantencion','mantencion123','Mantención'),('bodega','bodega123','Bodega'),('lectura','lectura123','Lecturas')]
SAMPLE=[('MD-01','Maquinaria Pesada','Excavadora','SANY','SY215C','Q-459','HORAS',250,2350,2250,0,'OPERATIVO'),('MD-02','Maquinaria Pesada','Excavadora','CAT','320D','Faena Norte','HORAS',250,1410,1500,0,'OPERATIVO'),('CD-100','Camión','Camión Tolva','Mercedes Benz','Actros','Q-459','KM',15000,328900,315000,0,'OPERATIVO'),('CD-102','Camión','Camión Plano','MAN','40400','Taltal','KM',15000,302500,285000,0,'OPERATIVO'),('VD-01','Vehículo Liviano','Camioneta','Maxus','T60','Santiago','KM',10000,94800,90000,0,'OPERATIVO'),('EQP-01','Equipo Planta','Generador','Cummins','C220','Talca','HORAS',250,980,1000,0,'OPERATIVO')]

def init_db():
    idt, real = id_type(), real_type()
    with engine.begin() as c:
        c.execute(text(f"CREATE TABLE IF NOT EXISTS usuarios(id {idt}, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, rol TEXT NOT NULL, activo INTEGER DEFAULT 1)"))
        c.execute(text(f"CREATE TABLE IF NOT EXISTS equipos(id {idt}, codigo TEXT UNIQUE NOT NULL, tipo_equipo TEXT, familia TEXT, marca TEXT, modelo TEXT, ubicacion TEXT, control_base TEXT, frecuencia_base {real} DEFAULT 0, lectura_actual {real} DEFAULT 0, ultima_pm {real} DEFAULT 0, costo_total_pm {real} DEFAULT 0, estado_operacional TEXT DEFAULT 'OPERATIVO', fecha_actualizacion TEXT)"))
        c.execute(text(f"CREATE TABLE IF NOT EXISTS ot(id {idt}, numero TEXT UNIQUE, codigo TEXT, tipo TEXT, prioridad TEXT, estado TEXT, fecha_creacion TEXT, lectura {real} DEFAULT 0, descripcion TEXT, responsable TEXT, costo_estimado {real} DEFAULT 0, fecha_cierre TEXT, lectura_cierre {real} DEFAULT 0, comentario_cierre TEXT)"))
        c.execute(text(f"CREATE TABLE IF NOT EXISTS lecturas(id {idt}, fecha TEXT, codigo TEXT, tipo_lectura TEXT, valor {real} DEFAULT 0, ubicacion TEXT, responsable TEXT, observacion TEXT)"))
        c.execute(text(f"CREATE TABLE IF NOT EXISTS compras(id {idt}, fecha TEXT, codigo_equipo TEXT, oc TEXT, proveedor TEXT, item TEXT, cantidad {real} DEFAULT 0, costo_total {real} DEFAULT 0, estado TEXT, observacion TEXT)"))
        c.execute(text(f"CREATE TABLE IF NOT EXISTS bodega(id {idt}, fecha TEXT, codigo_equipo TEXT, ot_numero TEXT, repuesto TEXT, cantidad {real} DEFAULT 0, costo_unitario {real} DEFAULT 0, movimiento TEXT, observacion TEXT)"))
        if c.execute(text('SELECT COUNT(*) FROM usuarios')).scalar()==0:
            for u,p,r in DEFAULT_USERS:
                c.execute(text('INSERT INTO usuarios(username,password_hash,rol,activo) VALUES(:u,:p,:r,1)'), {'u':u,'p':generate_password_hash(p),'r':r})
        if c.execute(text('SELECT COUNT(*) FROM equipos')).scalar()==0:
            for e in SAMPLE:
                c.execute(text('INSERT INTO equipos(codigo,tipo_equipo,familia,marca,modelo,ubicacion,control_base,frecuencia_base,lectura_actual,ultima_pm,costo_total_pm,estado_operacional,fecha_actualizacion) VALUES(:codigo,:tipo,:familia,:marca,:modelo,:ubicacion,:control,:freq,:lectura,:pm,:costo,:estado,:fecha)'), {'codigo':e[0],'tipo':e[1],'familia':e[2],'marca':e[3],'modelo':e[4],'ubicacion':e[5],'control':e[6],'freq':e[7],'lectura':e[8],'pm':e[9],'costo':e[10],'estado':e[11],'fecha':datetime.now().strftime('%Y-%m-%d %H:%M')})

def rows(sql, params=None):
    with engine.begin() as c: return [dict(r._mapping) for r in c.execute(text(sql), params or {})]
def one(sql, params=None):
    with engine.begin() as c: return c.execute(text(sql), params or {}).mappings().first()
def exec_sql(sql, params=None):
    with engine.begin() as c: c.execute(text(sql), params or {})

def login_required(fn):
    @wraps(fn)
    def w(*a,**k):
        if 'user' not in session: return redirect(url_for('login'))
        return fn(*a,**k)
    return w

def role_required(*roles):
    def deco(fn):
        @wraps(fn)
        def w(*a,**k):
            if 'user' not in session: return redirect(url_for('login'))
            if session.get('rol') not in roles and session.get('rol')!='Administrador':
                flash('No tienes permiso para esta acción.'); return redirect(url_for('index'))
            return fn(*a,**k)
        return w
    return deco

def sort_key(code):
    c=str(code or '').upper(); order={'MD':1,'CD':2,'VD':3,'EQP':4}; prefix=c.split('-')[0] if '-' in c else c[:3]; nums=''.join(ch for ch in c if ch.isdigit()); return (order.get(prefix,9), int(nums) if nums else 999999, c)
def estado(e):
    op=str(e.get('estado_operacional') or '').upper(); pm=float(e.get('ultima_pm') or 0); lec=float(e.get('lectura_actual') or 0); freq=float(e.get('frecuencia_base') or 0)
    if 'FUERA' in op: return 'FUERA DE SERVICIO'
    if 'TALLER' in op: return 'EN TALLER'
    if pm<=0 or lec<=0 or freq<=0: return 'SIN HISTORIAL'
    margen=pm+freq-lec
    if margen<0: return 'ATRASADA'
    if margen<=max(15,freq*.10): return 'PRÓXIMA'
    return 'AL DÍA'
def color(est):
    e=str(est).upper()
    if 'ATRAS' in e: return 'red'
    if 'PRÓXIMA' in e or 'SIN' in e: return 'orange'
    if 'TALLER' in e or 'FUERA' in e: return 'gray'
    return 'green'
def equipos_calc():
    out=[]
    for e in rows('SELECT * FROM equipos'):
        est=estado(e); pm=float(e.get('ultima_pm') or 0); lec=float(e.get('lectura_actual') or 0); freq=float(e.get('frecuencia_base') or 0); prox=pm+freq if pm>0 else 0; margen=prox-lec if prox>0 and lec>0 else 0
        e.update({'estado_calculado':est,'semaforo':color(est),'proxima_pm':prox,'margen':margen,'descripcion':f"{e.get('marca','')} {e.get('modelo','')}".strip()})
        out.append(e)
    return sorted(out,key=lambda x:sort_key(x.get('codigo')))
def make_kpis(equipos,ots,compras,bodega,lecturas):
    total=len(equipos); atras=sum(1 for e in equipos if e['semaforo']=='red'); prox=sum(1 for e in equipos if e['semaforo']=='orange'); no=sum(1 for e in equipos if e['semaforo']=='gray'); control=max(total-atras-no,0)
    return {'total':total,'atrasados':atras,'proximos':prox,'controlado':round(control/total*100,1) if total else 0,'ot_abiertas':sum(1 for o in ots if o.get('estado')!='CERRADA'),'ot_cerradas':sum(1 for o in ots if o.get('estado')=='CERRADA'),'compras_proceso':sum(1 for c in compras if str(c.get('estado','')).upper()=='EN PROCESO'),'compras_monto':int(sum(float(c.get('costo_total') or 0) for c in compras)),'bodega_movimientos':len(bodega),'lecturas':len(lecturas),'costo_total':int(sum(float(e.get('costo_total_pm') or 0) for e in equipos))}
def ubicaciones_chart(equipos):
    d={}
    for e in equipos:
        if e['semaforo']=='red': d[e.get('ubicacion') or 'Sin ubicación']=d.get(e.get('ubicacion') or 'Sin ubicación',0)+1
    return [{'ubicacion':k,'cantidad':v} for k,v in sorted(d.items(),key=lambda x:x[1],reverse=True)]

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        u=request.form.get('username','').strip(); p=request.form.get('password',''); user=one('SELECT * FROM usuarios WHERE username=:u AND activo=1', {'u':u})
        if user and check_password_hash(user['password_hash'], p): session['user']=user['username']; session['rol']=user['rol']; return redirect(url_for('index'))
        flash('Usuario o contraseña incorrectos.')
    return render_template('login.html')
@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))
@app.route('/')
@login_required
def index():
    equipos=equipos_calc(); ots=rows('SELECT * FROM ot ORDER BY id DESC'); compras=rows('SELECT * FROM compras ORDER BY id DESC'); bodega=rows('SELECT * FROM bodega ORDER BY id DESC'); lecturas=rows('SELECT * FROM lecturas ORDER BY id DESC'); kk=make_kpis(equipos,ots,compras,bodega,lecturas); crit=[e for e in equipos if e['semaforo'] in ['red','orange']][:20]
    actividad=[{'icon':'fa-regular fa-file-lines','color':'blue','titulo':'OT abiertas','detalle':f"{kk['ot_abiertas']} trabajos activos"},{'icon':'fa-solid fa-cart-shopping','color':'purple','titulo':'Compras en proceso','detalle':f"{kk['compras_proceso']} compras registradas"},{'icon':'fa-solid fa-gauge-high','color':'green','titulo':'Lecturas registradas','detalle':f"{kk['lecturas']} lecturas en base de datos"}]
    return render_template('index.html', equipos=equipos, criticos=crit, ots=ots, compras=compras, bodega=bodega, lecturas=lecturas, kpis=kk, ubicaciones=ubicaciones_chart(equipos), actividad=actividad, current_user=session.get('user'), current_role=session.get('rol'), anio_actual=datetime.now().year, version_sistema='1.0.0')
@app.route('/equipos/nuevo', methods=['POST'])
@login_required
@role_required('Administrador','Mantención')
def nuevo_equipo():
    exec_sql('INSERT INTO equipos(codigo,tipo_equipo,familia,marca,modelo,ubicacion,control_base,frecuencia_base,lectura_actual,ultima_pm,costo_total_pm,estado_operacional,fecha_actualizacion) VALUES(:codigo,:tipo,:familia,:marca,:modelo,:ubicacion,:control,:freq,:lectura,:pm,:costo,:estado,:fecha) ON CONFLICT (codigo) DO UPDATE SET tipo_equipo=EXCLUDED.tipo_equipo,familia=EXCLUDED.familia,marca=EXCLUDED.marca,modelo=EXCLUDED.modelo,ubicacion=EXCLUDED.ubicacion,control_base=EXCLUDED.control_base,frecuencia_base=EXCLUDED.frecuencia_base,lectura_actual=EXCLUDED.lectura_actual,ultima_pm=EXCLUDED.ultima_pm,costo_total_pm=EXCLUDED.costo_total_pm,estado_operacional=EXCLUDED.estado_operacional,fecha_actualizacion=EXCLUDED.fecha_actualizacion', {'codigo':request.form.get('codigo','').strip(),'tipo':request.form.get('tipo_equipo',''),'familia':request.form.get('familia',''),'marca':request.form.get('marca',''),'modelo':request.form.get('modelo',''),'ubicacion':request.form.get('ubicacion',''),'control':request.form.get('control_base','HORAS'),'freq':float(request.form.get('frecuencia_base') or 0),'lectura':float(request.form.get('lectura_actual') or 0),'pm':float(request.form.get('ultima_pm') or 0),'costo':float(request.form.get('costo_total_pm') or 0),'estado':request.form.get('estado_operacional','OPERATIVO'),'fecha':datetime.now().strftime('%Y-%m-%d %H:%M')}); flash('Equipo guardado.'); return redirect(url_for('index'))
@app.route('/crear_ot', methods=['POST'])
@login_required
@role_required('Administrador','Mantención')
def crear_ot():
    fecha=datetime.now().strftime('%Y-%m-%d %H:%M')
    with engine.begin() as c:
        count=c.execute(text('SELECT COUNT(*) FROM ot')).scalar()+1; numero=f'OT-WEB-{count:05d}'
        c.execute(text("INSERT INTO ot(numero,codigo,tipo,prioridad,estado,fecha_creacion,lectura,descripcion,responsable,costo_estimado) VALUES(:numero,:codigo,:tipo,:prioridad,'ABIERTA',:fecha,:lectura,:descripcion,:responsable,:costo)"), {'numero':numero,'codigo':request.form.get('codigo',''),'tipo':request.form.get('tipo','Preventiva'),'prioridad':request.form.get('prioridad','Media'),'fecha':fecha,'lectura':float(request.form.get('lectura') or 0),'descripcion':request.form.get('descripcion',''),'responsable':request.form.get('responsable',''),'costo':float(request.form.get('costo_estimado') or 0)})
    flash(f'OT creada: {numero}'); return redirect(url_for('index'))
@app.route('/lecturas', methods=['POST'])
@login_required
@role_required('Administrador','Mantención','Lecturas')
def registrar_lectura():
    fecha=datetime.now().strftime('%Y-%m-%d %H:%M'); codigo=request.form.get('codigo','').strip(); valor=float(request.form.get('valor') or 0); ubic=request.form.get('ubicacion','').strip()
    exec_sql('INSERT INTO lecturas(fecha,codigo,tipo_lectura,valor,ubicacion,responsable,observacion) VALUES(:fecha,:codigo,:tipo,:valor,:ubicacion,:responsable,:obs)', {'fecha':fecha,'codigo':codigo,'tipo':request.form.get('tipo_lectura','HOROMETRO'),'valor':valor,'ubicacion':ubic,'responsable':request.form.get('responsable',''),'obs':request.form.get('observacion','')})
    exec_sql("UPDATE equipos SET lectura_actual=:valor, ubicacion=COALESCE(NULLIF(:ubicacion,''),ubicacion), fecha_actualizacion=:fecha WHERE codigo=:codigo", {'valor':valor,'ubicacion':ubic,'fecha':fecha,'codigo':codigo}); flash('Lectura registrada.'); return redirect(url_for('index'))
@app.route('/compras', methods=['POST'])
@login_required
@role_required('Administrador','Bodega','Mantención')
def registrar_compra():
    exec_sql('INSERT INTO compras(fecha,codigo_equipo,oc,proveedor,item,cantidad,costo_total,estado,observacion) VALUES(:fecha,:codigo,:oc,:proveedor,:item,:cantidad,:costo,:estado,:obs)', {'fecha':datetime.now().strftime('%Y-%m-%d %H:%M'),'codigo':request.form.get('codigo_equipo',''),'oc':request.form.get('oc',''),'proveedor':request.form.get('proveedor',''),'item':request.form.get('item',''),'cantidad':float(request.form.get('cantidad') or 0),'costo':float(request.form.get('costo_total') or 0),'estado':request.form.get('estado','EN PROCESO'),'obs':request.form.get('observacion','')}); flash('Compra registrada.'); return redirect(url_for('index'))
@app.route('/bodega', methods=['POST'])
@login_required
@role_required('Administrador','Bodega')
def registrar_bodega():
    exec_sql('INSERT INTO bodega(fecha,codigo_equipo,ot_numero,repuesto,cantidad,costo_unitario,movimiento,observacion) VALUES(:fecha,:codigo,:ot,:repuesto,:cantidad,:costo,:movimiento,:obs)', {'fecha':datetime.now().strftime('%Y-%m-%d %H:%M'),'codigo':request.form.get('codigo_equipo',''),'ot':request.form.get('ot_numero',''),'repuesto':request.form.get('repuesto',''),'cantidad':float(request.form.get('cantidad') or 0),'costo':float(request.form.get('costo_unitario') or 0),'movimiento':request.form.get('movimiento','SALIDA'),'obs':request.form.get('observacion','')}); flash('Movimiento de bodega registrado.'); return redirect(url_for('index'))
@app.route('/health')
def health(): return jsonify({'status':'ok','database':'postgresql' if DATABASE_URL else 'sqlite'})
try: init_db(); print('DB inicializada correctamente')
except Exception as e: print('ERROR INIT DB:', e)
if __name__=='__main__': app.run(host='0.0.0.0', port=int(os.environ.get('PORT',5000)), debug=False)
