from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from sqlalchemy import create_engine, text
from datetime import datetime
import os
import pandas as pd

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "demotron-cmms-final")

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if DATABASE_URL:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
else:
    os.makedirs("data", exist_ok=True)
    engine = create_engine("sqlite:///data/cmms_local.db", future=True)

def is_postgres():
    return bool(DATABASE_URL)

def id_col():
    return "SERIAL PRIMARY KEY" if is_postgres() else "INTEGER PRIMARY KEY AUTOINCREMENT"

def real_col():
    return "DOUBLE PRECISION" if is_postgres() else "REAL"

def exec_sql(sql, params=None):
    with engine.begin() as conn:
        conn.execute(text(sql), params or {})

def rows(sql, params=None):
    with engine.begin() as conn:
        return [dict(r._mapping) for r in conn.execute(text(sql), params or {})]

def one(sql, params=None):
    with engine.begin() as conn:
        return conn.execute(text(sql), params or {}).mappings().first()

def init_db():
    idt = id_col()
    real = real_col()

    exec_sql(f"""
    CREATE TABLE IF NOT EXISTS usuarios (
      id {idt},
      username TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL,
      rol TEXT NOT NULL,
      activo INTEGER DEFAULT 1
    )
    """)

    exec_sql(f"""
    CREATE TABLE IF NOT EXISTS equipos (
      id {idt},
      codigo TEXT UNIQUE NOT NULL,
      tipo_equipo TEXT,
      familia TEXT,
      marca TEXT,
      modelo TEXT,
      descripcion TEXT,
      ubicacion TEXT,
      control_base TEXT,
      frecuencia_base {real} DEFAULT 0,
      lectura_actual {real} DEFAULT 0,
      ultima_pm {real} DEFAULT 0,
      proxima_pm {real} DEFAULT 0,
      margen {real} DEFAULT 0,
      costo_total_pm {real} DEFAULT 0,
      estado_operacional TEXT DEFAULT 'OPERATIVO',
      estado_calculado TEXT,
      semaforo TEXT,
      fecha_actualizacion TEXT
    )
    """)

    exec_sql(f"""
    CREATE TABLE IF NOT EXISTS ot (
      id {idt},
      numero TEXT UNIQUE,
      codigo TEXT,
      tipo TEXT,
      prioridad TEXT,
      estado TEXT,
      fecha_creacion TEXT,
      lectura {real} DEFAULT 0,
      descripcion TEXT,
      responsable TEXT,
      costo_estimado {real} DEFAULT 0
    )
    """)

    exec_sql(f"""
    CREATE TABLE IF NOT EXISTS lecturas (
      id {idt},
      fecha TEXT,
      codigo TEXT,
      tipo_lectura TEXT,
      valor {real} DEFAULT 0,
      ubicacion TEXT,
      responsable TEXT,
      observacion TEXT
    )
    """)

    exec_sql(f"""
    CREATE TABLE IF NOT EXISTS compras (
      id {idt},
      fecha TEXT,
      codigo_equipo TEXT,
      oc TEXT,
      proveedor TEXT,
      item TEXT,
      cantidad {real} DEFAULT 0,
      costo_total {real} DEFAULT 0,
      estado TEXT,
      observacion TEXT
    )
    """)

    exec_sql(f"""
    CREATE TABLE IF NOT EXISTS bodega (
      id {idt},
      fecha TEXT,
      codigo_equipo TEXT,
      ot_numero TEXT,
      repuesto TEXT,
      cantidad {real} DEFAULT 0,
      costo_unitario {real} DEFAULT 0,
      movimiento TEXT,
      observacion TEXT
    )
    """)

    if one("SELECT COUNT(*) AS n FROM usuarios")["n"] == 0:
        users = [
            ("admin", "admin123", "Administrador"),
            ("gerencia", "gerencia123", "Gerencia"),
            ("mantencion", "mantencion123", "Mantención"),
            ("bodega", "bodega123", "Bodega"),
            ("lectura", "lectura123", "Lecturas"),
        ]
        for username, password, rol in users:
            exec_sql("""
            INSERT INTO usuarios(username,password_hash,rol,activo)
            VALUES(:u,:p,:r,1)
            """, {"u": username, "p": generate_password_hash(password), "r": rol})

    if one("SELECT COUNT(*) AS n FROM equipos")["n"] == 0:
        seed_demo()

def calc_estado(freq, lectura, ultima_pm, estado_operacional):
    op = str(estado_operacional or "").upper()
    if "FUERA" in op:
        return "FUERA DE SERVICIO", "gray", 0, 0
    if "TALLER" in op:
        return "EN TALLER", "gray", 0, 0

    freq = float(freq or 0)
    lectura = float(lectura or 0)
    ultima_pm = float(ultima_pm or 0)
    proxima = ultima_pm + freq if ultima_pm > 0 and freq > 0 else 0
    margen = proxima - lectura if proxima > 0 and lectura > 0 else 0

    if ultima_pm <= 0 or lectura <= 0 or freq <= 0:
        return "SIN HISTORIAL", "orange", proxima, margen
    if margen < 0:
        return "ATRASADA", "red", proxima, margen
    if margen <= max(15, freq * 0.10):
        return "PRÓXIMA", "orange", proxima, margen
    return "AL DÍA", "green", proxima, margen

def guardar_equipo(data):
    estado, semaforo, proxima, margen = calc_estado(
        data.get("frecuencia_base"),
        data.get("lectura_actual"),
        data.get("ultima_pm"),
        data.get("estado_operacional")
    )
    descripcion = data.get("descripcion") or f"{data.get('marca','')} {data.get('modelo','')}".strip()

    exec_sql("""
    INSERT INTO equipos(
      codigo,tipo_equipo,familia,marca,modelo,descripcion,ubicacion,control_base,
      frecuencia_base,lectura_actual,ultima_pm,proxima_pm,margen,costo_total_pm,
      estado_operacional,estado_calculado,semaforo,fecha_actualizacion
    )
    VALUES(
      :codigo,:tipo_equipo,:familia,:marca,:modelo,:descripcion,:ubicacion,:control_base,
      :frecuencia_base,:lectura_actual,:ultima_pm,:proxima_pm,:margen,:costo_total_pm,
      :estado_operacional,:estado_calculado,:semaforo,:fecha_actualizacion
    )
    ON CONFLICT (codigo) DO UPDATE SET
      tipo_equipo=EXCLUDED.tipo_equipo,
      familia=EXCLUDED.familia,
      marca=EXCLUDED.marca,
      modelo=EXCLUDED.modelo,
      descripcion=EXCLUDED.descripcion,
      ubicacion=EXCLUDED.ubicacion,
      control_base=EXCLUDED.control_base,
      frecuencia_base=EXCLUDED.frecuencia_base,
      lectura_actual=EXCLUDED.lectura_actual,
      ultima_pm=EXCLUDED.ultima_pm,
      proxima_pm=EXCLUDED.proxima_pm,
      margen=EXCLUDED.margen,
      costo_total_pm=EXCLUDED.costo_total_pm,
      estado_operacional=EXCLUDED.estado_operacional,
      estado_calculado=EXCLUDED.estado_calculado,
      semaforo=EXCLUDED.semaforo,
      fecha_actualizacion=EXCLUDED.fecha_actualizacion
    """, {
        "codigo": data.get("codigo","").strip(),
        "tipo_equipo": data.get("tipo_equipo",""),
        "familia": data.get("familia",""),
        "marca": data.get("marca",""),
        "modelo": data.get("modelo",""),
        "descripcion": descripcion,
        "ubicacion": data.get("ubicacion",""),
        "control_base": data.get("control_base","HORAS"),
        "frecuencia_base": float(data.get("frecuencia_base") or 0),
        "lectura_actual": float(data.get("lectura_actual") or 0),
        "ultima_pm": float(data.get("ultima_pm") or 0),
        "proxima_pm": proxima,
        "margen": margen,
        "costo_total_pm": float(data.get("costo_total_pm") or 0),
        "estado_operacional": data.get("estado_operacional","OPERATIVO"),
        "estado_calculado": estado,
        "semaforo": semaforo,
        "fecha_actualizacion": datetime.now().strftime("%Y-%m-%d %H:%M")
    })

def seed_demo():
    equipos = [
        {"codigo":"MD-01","tipo_equipo":"Maquinaria Pesada","familia":"Excavadora","marca":"SANY","modelo":"SY215C","ubicacion":"Q-459","control_base":"HORAS","frecuencia_base":250,"lectura_actual":2350,"ultima_pm":2250,"costo_total_pm":1850000,"estado_operacional":"OPERATIVO"},
        {"codigo":"MD-02","tipo_equipo":"Maquinaria Pesada","familia":"Excavadora","marca":"CAT","modelo":"320D","ubicacion":"Faena Norte","control_base":"HORAS","frecuencia_base":250,"lectura_actual":1510,"ultima_pm":1250,"costo_total_pm":2100000,"estado_operacional":"OPERATIVO"},
        {"codigo":"CD-100","tipo_equipo":"Camión","familia":"Camión Tolva","marca":"Mercedes Benz","modelo":"Actros","ubicacion":"Q-459","control_base":"KM","frecuencia_base":15000,"lectura_actual":328900,"ultima_pm":315000,"costo_total_pm":1250000,"estado_operacional":"OPERATIVO"},
        {"codigo":"CD-102","tipo_equipo":"Camión","familia":"Camión Plano","marca":"MAN","modelo":"40400","ubicacion":"Taltal","control_base":"KM","frecuencia_base":15000,"lectura_actual":302500,"ultima_pm":300000,"costo_total_pm":980000,"estado_operacional":"OPERATIVO"},
        {"codigo":"VD-01","tipo_equipo":"Vehículo Liviano","familia":"Camioneta","marca":"Maxus","modelo":"T60","ubicacion":"Santiago","control_base":"KM","frecuencia_base":10000,"lectura_actual":94800,"ultima_pm":90000,"costo_total_pm":350000,"estado_operacional":"OPERATIVO"},
        {"codigo":"EQP-01","tipo_equipo":"Equipo Planta","familia":"Generador","marca":"Cummins","modelo":"C220","ubicacion":"Talca","control_base":"HORAS","frecuencia_base":250,"lectura_actual":980,"ultima_pm":1000,"costo_total_pm":560000,"estado_operacional":"OPERATIVO"},
    ]
    for e in equipos:
        guardar_equipo(e)

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

def equipos_list():
    return rows("""
    SELECT * FROM equipos
    ORDER BY
      CASE
        WHEN codigo LIKE 'MD-%' THEN 1
        WHEN codigo LIKE 'CD-%' THEN 2
        WHEN codigo LIKE 'VD-%' THEN 3
        WHEN codigo LIKE 'EQP-%' THEN 4
        ELSE 9
      END,
      codigo
    """)

def build_kpis(equipos, ots, compras, lecturas, bodega):
    total = len(equipos)
    atrasados = sum(1 for e in equipos if e.get("semaforo") == "red")
    proximos = sum(1 for e in equipos if e.get("semaforo") == "orange")
    no_operativos = sum(1 for e in equipos if e.get("semaforo") == "gray")
    controlado = round(((total - atrasados - no_operativos) / total * 100), 1) if total else 0
    return {
        "total": total,
        "atrasados": atrasados,
        "proximos": proximos,
        "controlado": controlado,
        "ot_abiertas": sum(1 for o in ots if o.get("estado") != "CERRADA"),
        "compras_proceso": sum(1 for c in compras if str(c.get("estado","")).upper() == "EN PROCESO"),
        "compras_monto": int(sum(float(c.get("costo_total") or 0) for c in compras)),
        "lecturas": len(lecturas),
        "bodega_movimientos": len(bodega),
        "costo_total": int(sum(float(e.get("costo_total_pm") or 0) for e in equipos))
    }

def ubicaciones_chart(equipos):
    d = {}
    for e in equipos:
        if e.get("semaforo") == "red":
            u = e.get("ubicacion") or "Sin ubicación"
            d[u] = d.get(u, 0) + 1
    return [{"ubicacion": k, "cantidad": v} for k, v in sorted(d.items(), key=lambda x: x[1], reverse=True)]

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","")
        user = one("SELECT * FROM usuarios WHERE username=:u AND activo=1", {"u": username})
        if user and check_password_hash(user["password_hash"], password):
            session["user"] = user["username"]
            session["rol"] = user["rol"]
            return redirect(url_for("index"))
        flash("Usuario o contraseña incorrectos.")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
@login_required
def index():
    equipos = equipos_list()
    ots = rows("SELECT * FROM ot ORDER BY id DESC")
    compras = rows("SELECT * FROM compras ORDER BY id DESC")
    lecturas = rows("SELECT * FROM lecturas ORDER BY id DESC")
    bodega = rows("SELECT * FROM bodega ORDER BY id DESC")
    kpis = build_kpis(equipos, ots, compras, lecturas, bodega)
    criticos = [e for e in equipos if e.get("semaforo") in ("red","orange")][:20]
    actividad = [
        {"icon":"fa-regular fa-file-lines","color":"blue","titulo":"OT abiertas","detalle":f"{kpis['ot_abiertas']} trabajos activos"},
        {"icon":"fa-solid fa-cart-shopping","color":"purple","titulo":"Compras en proceso","detalle":f"{kpis['compras_proceso']} compras registradas"},
        {"icon":"fa-solid fa-gauge-high","color":"green","titulo":"Lecturas registradas","detalle":f"{kpis['lecturas']} lecturas en base de datos"},
    ]
    return render_template(
        "index.html",
        equipos=equipos,
        criticos=criticos,
        ots=ots,
        compras=compras,
        lecturas=lecturas,
        bodega=bodega,
        kpis=kpis,
        ubicaciones=ubicaciones_chart(equipos),
        actividad=actividad,
        current_user=session.get("user"),
        current_role=session.get("rol"),
        anio_actual=datetime.now().year,
        version_sistema="1.0.0"
    )

@app.route("/equipos/nuevo", methods=["POST"])
@login_required
def nuevo_equipo():
    guardar_equipo(request.form)
    flash("Equipo guardado correctamente.")
    return redirect(url_for("index"))

@app.route("/crear_ot", methods=["POST"])
@login_required
def crear_ot():
    count = one("SELECT COUNT(*) AS n FROM ot")["n"] + 1
    numero = f"OT-WEB-{count:05d}"
    exec_sql("""
    INSERT INTO ot(numero,codigo,tipo,prioridad,estado,fecha_creacion,lectura,descripcion,responsable,costo_estimado)
    VALUES(:numero,:codigo,:tipo,:prioridad,'ABIERTA',:fecha,:lectura,:descripcion,:responsable,:costo)
    """, {
        "numero": numero,
        "codigo": request.form.get("codigo",""),
        "tipo": request.form.get("tipo","Preventiva"),
        "prioridad": request.form.get("prioridad","Media"),
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "lectura": float(request.form.get("lectura") or 0),
        "descripcion": request.form.get("descripcion",""),
        "responsable": request.form.get("responsable",""),
        "costo": float(request.form.get("costo_estimado") or 0)
    })
    flash(f"OT creada: {numero}")
    return redirect(url_for("index"))

@app.route("/lecturas", methods=["POST"])
@login_required
def registrar_lectura():
    codigo = request.form.get("codigo","").strip()
    valor = float(request.form.get("valor") or 0)
    ubicacion = request.form.get("ubicacion","").strip()
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
    exec_sql("""
    INSERT INTO lecturas(fecha,codigo,tipo_lectura,valor,ubicacion,responsable,observacion)
    VALUES(:fecha,:codigo,:tipo,:valor,:ubicacion,:responsable,:obs)
    """, {
        "fecha": fecha,
        "codigo": codigo,
        "tipo": request.form.get("tipo_lectura","HOROMETRO"),
        "valor": valor,
        "ubicacion": ubicacion,
        "responsable": request.form.get("responsable",""),
        "obs": request.form.get("observacion","")
    })
    if codigo:
        eq = one("SELECT * FROM equipos WHERE codigo=:c", {"c": codigo})
        if eq:
            data = dict(eq)
            data["lectura_actual"] = valor
            if ubicacion:
                data["ubicacion"] = ubicacion
            guardar_equipo(data)
    flash("Lectura registrada.")
    return redirect(url_for("index"))

@app.route("/compras", methods=["POST"])
@login_required
def registrar_compra():
    exec_sql("""
    INSERT INTO compras(fecha,codigo_equipo,oc,proveedor,item,cantidad,costo_total,estado,observacion)
    VALUES(:fecha,:codigo,:oc,:proveedor,:item,:cantidad,:costo,:estado,:obs)
    """, {
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "codigo": request.form.get("codigo_equipo",""),
        "oc": request.form.get("oc",""),
        "proveedor": request.form.get("proveedor",""),
        "item": request.form.get("item",""),
        "cantidad": float(request.form.get("cantidad") or 0),
        "costo": float(request.form.get("costo_total") or 0),
        "estado": request.form.get("estado","EN PROCESO"),
        "obs": request.form.get("observacion","")
    })
    flash("Compra registrada.")
    return redirect(url_for("index"))

@app.route("/bodega", methods=["POST"])
@login_required
def registrar_bodega():
    exec_sql("""
    INSERT INTO bodega(fecha,codigo_equipo,ot_numero,repuesto,cantidad,costo_unitario,movimiento,observacion)
    VALUES(:fecha,:codigo,:ot,:repuesto,:cantidad,:costo,:movimiento,:obs)
    """, {
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "codigo": request.form.get("codigo_equipo",""),
        "ot": request.form.get("ot_numero",""),
        "repuesto": request.form.get("repuesto",""),
        "cantidad": float(request.form.get("cantidad") or 0),
        "costo": float(request.form.get("costo_unitario") or 0),
        "movimiento": request.form.get("movimiento","SALIDA"),
        "obs": request.form.get("observacion","")
    })
    flash("Movimiento de bodega registrado.")
    return redirect(url_for("index"))

@app.route("/importar_excel", methods=["POST"])
@login_required
def importar_excel():
    file = request.files.get("excel")
    if not file:
        flash("No se recibió archivo Excel.")
        return redirect(url_for("index"))
    try:
        df = pd.read_excel(file, sheet_name="Maestro_Equipos", header=2).dropna(how="all")
        df.columns = [str(c).strip() for c in df.columns]
        count = 0
        for _, r in df.iterrows():
            codigo = str(r.get("Codigo","")).strip()
            if not codigo or codigo.lower() == "nan":
                continue
            data = {
                "codigo": codigo,
                "tipo_equipo": str(r.get("Tipo Equipo","") if pd.notna(r.get("Tipo Equipo","")) else ""),
                "familia": str(r.get("Familia","") if pd.notna(r.get("Familia","")) else ""),
                "marca": str(r.get("Marca","") if pd.notna(r.get("Marca","")) else ""),
                "modelo": str(r.get("Modelo","") if pd.notna(r.get("Modelo","")) else ""),
                "ubicacion": str(r.get("Ubicacion","") if pd.notna(r.get("Ubicacion","")) else ""),
                "control_base": str(r.get("Control Base","") if pd.notna(r.get("Control Base","")) else ""),
                "frecuencia_base": pd.to_numeric(r.get("Frecuencia Base",0), errors="coerce") or 0,
                "lectura_actual": pd.to_numeric(r.get("Lectura Actual",0), errors="coerce") or 0,
                "ultima_pm": pd.to_numeric(r.get("Ultima PM",0), errors="coerce") or 0,
                "costo_total_pm": pd.to_numeric(r.get("Costo Total PM CLP",0), errors="coerce") or 0,
                "estado_operacional": str(r.get("Estado Operacional","OPERATIVO") if pd.notna(r.get("Estado Operacional","")) else "OPERATIVO"),
            }
            guardar_equipo(data)
            count += 1
        flash(f"Excel importado a PostgreSQL: {count} equipos.")
    except Exception as e:
        flash(f"Error importando Excel: {e}")
    return redirect(url_for("index"))

@app.route("/seed")
@login_required
def seed():
    seed_demo()
    flash("Datos DEMO cargados.")
    return redirect(url_for("index"))

@app.route("/health")
def health():
    return jsonify({"status":"ok", "database":"postgresql" if DATABASE_URL else "sqlite"})

try:
    init_db()
except Exception as e:
    print("ERROR INIT DB:", e)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
