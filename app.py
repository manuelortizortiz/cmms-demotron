
import os
from datetime import datetime
from functools import wraps
from flask import Flask, request, redirect, url_for, session, jsonify, render_template_string
from sqlalchemy import create_engine, text, inspect
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "demotron-secret")
DEPLOY_VERSION = "DEMOTRON_DEPLOY_GARANTIZADO_2026_05_05_V2_ACTIVO_FIX"

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True) if DATABASE_URL else None

def q(sql, params=None, fetch=True):
    if engine is None:
        return []
    with engine.begin() as conn:
        res = conn.execute(text(sql), params or {})
        if fetch:
            return [dict(r) for r in res.mappings().all()]
        return []

def table_exists(name):
    try:
        return engine is not None and name in inspect(engine).get_table_names()
    except Exception:
        return False

def col_exists(table, col):
    try:
        return col in [c["name"] for c in inspect(engine).get_columns(table)]
    except Exception:
        return False

def add_col(table, col, ddl):
    try:
        if table_exists(table) and not col_exists(table, col):
            q(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}", fetch=False)
    except Exception:
        pass

def ensure_schema():
    if engine is None:
        return
    q("CREATE TABLE IF NOT EXISTS usuarios (id SERIAL PRIMARY KEY)", fetch=False)
    add_col("usuarios", "usuario", "TEXT")
    add_col("usuarios", "nombre", "TEXT")
    add_col("usuarios", "password_hash", "TEXT")
    add_col("usuarios", "rol", "TEXT")
    add_col("usuarios", "activo", "INTEGER DEFAULT 1")
    add_col("usuarios", "creado", "TIMESTAMP")
    q("""CREATE TABLE IF NOT EXISTS maestro_equipos (
        codigo TEXT PRIMARY KEY, tipo_equipo TEXT, familia TEXT, marca TEXT,
        modelo TEXT, ano TEXT, ubicacion TEXT, responsable TEXT,
        lectura_actual TEXT, unidad TEXT, proxima_pm TEXT, estado TEXT
    )""", fetch=False)
    q("""CREATE TABLE IF NOT EXISTS lecturas (
        id SERIAL PRIMARY KEY, fecha DATE, codigo TEXT, horometro NUMERIC,
        kilometraje NUMERIC, obra_ubicacion TEXT, responsable TEXT, observacion TEXT
    )""", fetch=False)
    q("""CREATE TABLE IF NOT EXISTS mantenciones (
        id SERIAL PRIMARY KEY, fecha DATE, codigo TEXT, tipo_mantencion TEXT,
        lectura NUMERIC, espm TEXT, folio TEXT, lugar TEXT, proveedor TEXT,
        costo_mantencion_clp TEXT, estado TEXT
    )""", fetch=False)
    q("""CREATE TABLE IF NOT EXISTS ot (
        id SERIAL PRIMARY KEY, fecha DATE, ot TEXT, codigo TEXT, tipo TEXT,
        lectura TEXT, descripcion TEXT, responsable TEXT, estado TEXT, costo TEXT
    )""", fetch=False)
    q("""CREATE TABLE IF NOT EXISTS compras (
        id SERIAL PRIMARY KEY, fecha DATE, oc TEXT, codigo TEXT, descripcion TEXT,
        proveedor TEXT, costo_pm_clp TEXT, estado_oc TEXT
    )""", fetch=False)
    q("""CREATE TABLE IF NOT EXISTS bodega (
        id SERIAL PRIMARY KEY, folio TEXT, fecha DATE, equipo TEXT, envio TEXT,
        persona_que_retiro TEXT, destino TEXT, comentario TEXT, codigo TEXT
    )""", fetch=False)
    q("""CREATE TABLE IF NOT EXISTS plan_mantenciones (
        id SERIAL PRIMARY KEY, codigo TEXT, tipo_equipo TEXT, familia TEXT,
        control TEXT, lectura_actual TEXT, proxima_lectura_objetivo TEXT,
        promedio_diario TEXT, dias_estimados TEXT, fecha_estimada TEXT,
        estado_operativo TEXT, prioridad TEXT, accion_sugerida TEXT
    )""", fetch=False)
    q("""CREATE TABLE IF NOT EXISTS plan_90_dias (
        id SERIAL PRIMARY KEY, codigo TEXT, tipo_equipo TEXT, familia TEXT,
        control TEXT, lectura_actual TEXT, proxima_lectura_objetivo TEXT,
        promedio_diario TEXT, dias_estimados TEXT, fecha_estimada TEXT,
        estado_operativo TEXT, prioridad TEXT, accion_sugerida TEXT
    )""", fetch=False)

def count_table(table):
    try:
        if table_exists(table):
            return q(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"]
    except Exception:
        pass
    return 0

def safe(v):
    return "" if v is None else str(v)

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

@app.before_request
def before():
    if request.endpoint != "static":
        try:
            ensure_schema()
        except Exception:
            pass

@app.route("/test-deploy-demotron")
def test_deploy():
    return f"OK NUEVO CODIGO {DEPLOY_VERSION}"

@app.route("/api/version")
def api_version():
    return jsonify({"status": "ok", "version": DEPLOY_VERSION})

@app.route("/api/status")
def api_status():
    return jsonify({"status": "ok", "version": DEPLOY_VERSION, "database": engine.dialect.name if engine else "sin database", "tables": inspect(engine).get_table_names() if engine else []})

@app.route("/admin/reparar-usuarios")
@app.route("/admin/forzar-admin")
def reparar_usuarios():
    try:
        ensure_schema()
        q("DELETE FROM usuarios WHERE usuario = :u", {"u": "admin"}, fetch=False)
        q("""INSERT INTO usuarios (usuario,nombre,password_hash,rol,activo,creado)
             VALUES (:usuario,:nombre,:password_hash,:rol,:activo,:creado)""",
          {"usuario": "admin", "nombre": "Administrador", "password_hash": generate_password_hash("admin123"), "rol": "admin", "activo": 1, "creado": datetime.now()}, fetch=False)
        return jsonify({"ok": True, "version": DEPLOY_VERSION, "usuario": "admin", "password": "admin123"})
    except Exception as e:
        return jsonify({"ok": False, "version": DEPLOY_VERSION, "error": str(e)}), 500

@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        usuario = (request.form.get("usuario") or "").strip()
        password = request.form.get("password") or ""
        if usuario == "admin" and password == "admin123":
            session["user"] = "admin"
            session["rol"] = "admin"
            return redirect(url_for("dashboard"))
        try:
            row = q("SELECT * FROM usuarios WHERE usuario=:u LIMIT 1", {"u": usuario})
            if row and row[0].get("password_hash") and check_password_hash(row[0]["password_hash"], password):
                session["user"] = row[0].get("usuario") or usuario
                session["rol"] = row[0].get("rol") or "usuario"
                return redirect(url_for("dashboard"))
            error = "Usuario o contraseña incorrectos"
        except Exception:
            error = "Use admin / admin123"
    return render_template_string("""<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/static/css/styles.css"></head><body class="login"><form method="post" class="login-card"><h1>DEMOTRON</h1><p>CMMS ERP · Deploy garantizado</p><input name="usuario" value="admin" placeholder="Usuario"><input name="password" type="password" value="admin123" placeholder="Contraseña">""" + (f'<div class="error">{error}</div>' if error else '') + """<button>Entrar</button><a href="/test-deploy-demotron">Probar deploy</a></form></body></html>""")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

def topbar():
    return """<header class="topbar"><a class="logo" href="/">DEMOTRON</a><nav><a href="/">Dashboard</a><a href="/equipos">Equipos</a><a href="/lecturas">Lecturas</a><a href="/mantenciones">Mantención</a><a href="/ot">OT</a><a href="/compras">Compras</a><a href="/bodega">Bodega</a><a href="/planificacion">Plan Mantenciones</a><a href="/plan-90-dias">Plan 90 días</a><a href="/admin">Admin</a></nav><a class="logout" href="/logout">Salir</a></header>"""

def page(title, body):
    return render_template_string(f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><link rel="stylesheet" href="/static/css/styles.css"></head><body>{topbar()}{body}<footer>DEMOTRON CMMS · {DEPLOY_VERSION}</footer></body></html>""")

@app.route("/")
@login_required
def dashboard():
    equipos = count_table("maestro_equipos")
    lecturas = count_table("lecturas")
    mantenciones = count_table("mantenciones")
    ot = count_table("ot")
    compras = count_table("compras")
    bodega = count_table("bodega")
    plan = count_table("plan_mantenciones")
    plan90 = count_table("plan_90_dias")
    body = f"""
    <main class="page">
      <section class="kpis">
        <div class="kpi red"><span>!</span><small>Equipos</small><b>{equipos}</b></div>
        <div class="kpi yellow"><span>◷</span><small>Lecturas</small><b>{lecturas}</b></div>
        <div class="kpi green"><span>✓</span><small>Mantenciones</small><b>{mantenciones}</b></div>
        <div class="kpi blue"><span>▣</span><small>OT</small><b>{ot}</b></div>
        <div class="kpi purple"><span>🛒</span><small>Compras</small><b>{compras}</b></div>
        <div class="kpi teal"><span>⌂</span><small>Bodega</small><b>{bodega}</b></div>
      </section>
      <section class="grid">
        <div class="panel"><h3>PLANES</h3><div class="bars"><div><b style="height:{max(20, int(plan or 0))}px"></b><small>Plan Mant.</small><strong>{plan}</strong></div><div><b style="height:{max(20, int(plan90 or 0))}px"></b><small>Plan 90</small><strong>{plan90}</strong></div></div></div>
        <div class="panel"><h3>ESTADO</h3><p>Versión activa:</p><code>{DEPLOY_VERSION}</code><p>Si ves esta versión, Railway sí tomó el código nuevo.</p></div>
      </section>
    </main>"""
    return page("Dashboard", body)

def generic_table(title, table):
    rows = []
    if table_exists(table):
        try:
            rows = q(f"SELECT * FROM {table} LIMIT 500")
        except Exception:
            rows = []
    if not rows:
        return page(title, f"<main class='page'><section class='panel'><h2>{title}</h2><p>Sin datos en {table}.</p></section></main>")
    cols = list(rows[0].keys())
    head = "".join(f"<th>{c}</th>" for c in cols)
    body = "".join("<tr>" + "".join(f"<td>{safe(r.get(c))}</td>" for c in cols) + "</tr>" for r in rows)
    return page(title, f"<main class='page'><section class='panel'><h2>{title}</h2><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></section></main>")

@app.route("/equipos")
@login_required
def equipos():
    return generic_table("Equipos", "maestro_equipos")

@app.route("/lecturas")
@login_required
def lecturas():
    return generic_table("Lecturas", "lecturas")

@app.route("/mantenciones")
@login_required
def mantenciones():
    return generic_table("Mantención", "mantenciones")

@app.route("/ot")
@login_required
def ot():
    return generic_table("Órdenes de Trabajo", "ot")

@app.route("/compras")
@login_required
def compras():
    return generic_table("Compras", "compras")

@app.route("/bodega")
@login_required
def bodega():
    return generic_table("Bodega", "bodega")

@app.route("/planificacion")
@login_required
def planificacion():
    return generic_table("Plan Mantenciones", "plan_mantenciones")

@app.route("/plan-90-dias")
@login_required
def plan90():
    return generic_table("Plan 90 días", "plan_90_dias")

@app.route("/admin")
@login_required
def admin():
    body = '<main class="page"><section class="panel"><h2>Administración</h2><p>Para reparar usuario administrador:</p><a class="btn" href="/admin/reparar-usuarios">Reparar admin</a><p>Usuario: <b>admin</b> · Contraseña: <b>admin123</b></p></section></main>'
    return page("Admin", body)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
