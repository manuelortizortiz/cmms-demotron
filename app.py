
import os
from datetime import datetime
from functools import wraps
from flask import Flask, request, redirect, url_for, session, jsonify, render_template_string
from sqlalchemy import create_engine, text, inspect
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "demotron-secret")
DEPLOY_VERSION = "DEMOTRON_VISUAL_ESTABLE_2026_05_05_V1"

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
    add_col("usuarios", "username", "TEXT")
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

        # La tabla existente puede venir con username NOT NULL.
        # Por eso escribimos ambos campos: usuario y username.
        add_col("usuarios", "usuario", "TEXT")
        add_col("usuarios", "username", "TEXT")
        add_col("usuarios", "nombre", "TEXT")
        add_col("usuarios", "password_hash", "TEXT")
        add_col("usuarios", "rol", "TEXT")
        add_col("usuarios", "activo", "INTEGER DEFAULT 1")
        add_col("usuarios", "creado", "TIMESTAMP")

        try:
            q("DELETE FROM usuarios WHERE usuario = :u OR username = :u", {"u": "admin"}, fetch=False)
        except Exception:
            try:
                q("DELETE FROM usuarios WHERE username = :u", {"u": "admin"}, fetch=False)
            except Exception:
                pass

        q("""INSERT INTO usuarios (usuario,username,nombre,password_hash,rol,activo,creado)
             VALUES (:usuario,:username,:nombre,:password_hash,:rol,:activo,:creado)""",
          {
              "usuario": "admin",
              "username": "admin",
              "nombre": "Administrador",
              "password_hash": generate_password_hash("admin123"),
              "rol": "admin",
              "activo": 1,
              "creado": datetime.now()
          }, fetch=False)
        return jsonify({"ok": True, "version": DEPLOY_VERSION, "usuario": "admin", "username": "admin", "password": "admin123"})
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
            row = q("SELECT * FROM usuarios WHERE usuario=:u OR username=:u LIMIT 1", {"u": usuario})
            if row and row[0].get("password_hash") and check_password_hash(row[0]["password_hash"], password):
                session["user"] = row[0].get("usuario") or row[0].get("username") or usuario
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
    return nav_html()

def page(title, body):
    return render_template_string(f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><link rel="stylesheet" href="/static/css/styles.css"></head><body>{topbar()}{body}<footer><b>DEMOTRON</b> CMMS ERP · {DEPLOY_VERSION}</footer></body></html>""")

@app.route("/")
@login_required
def dashboard():
    equipos_rows = get_equipo_rows()
    total = len(equipos_rows)
    estados = [estado_equipo(e) for e in equipos_rows]
    atrasados_rows = [e for e in equipos_rows if is_bad_estado(estado_equipo(e))]
    atrasados = len(atrasados_rows)
    proximos = sum(1 for e in equipos_rows if is_warn_estado(estado_equipo(e)))
    al_dia = sum(1 for e in equipos_rows if is_ok_estado(estado_equipo(e)))
    fuera = sum(1 for e in equipos_rows if is_off_estado(estado_equipo(e)))
    control = round((al_dia / total) * 100) if total else 0

    ot = count_table("ot")
    compras = count_table("compras")
    bodega = count_table("bodega")
    mantenciones = count_table("mantenciones")
    total_compras = money_sum_compras()

    by_ubic = {}
    for e in atrasados_rows:
        u = ubicacion_equipo(e) or "Sin ubicación"
        by_ubic[u] = by_ubic.get(u, 0) + 1
    ubic_data = sorted(by_ubic.items(), key=lambda x: x[1], reverse=True)[:6] or [("Sin atrasos", 0)]

    gestion_data = [("OT", int(ot or 0)), ("Compras", int(compras or 0)), ("Bodega", int(bodega or 0)), ("Mant.", int(mantenciones or 0))]

    p_ok = int((al_dia / max(total,1)) * 100)
    p_warn = int((proximos / max(total,1)) * 100)
    p_bad = int((atrasados / max(total,1)) * 100)
    donut = f"background: conic-gradient(#2fbd66 0 {p_ok}%, #f6b712 {p_ok}% {p_ok+p_warn}%, #ef3d48 {p_ok+p_warn}% {p_ok+p_warn+p_bad}%, #9aa3b2 {p_ok+p_warn+p_bad}% 100%)"

    atrasados_html = "".join(
        f"<tr><td><a href='/equipos'><b>{codigo_equipo(e)}</b></a></td><td>{tipo_equipo(e)}</td><td>{ubicacion_equipo(e)}</td><td>{lectura_equipo(e)}</td><td>{badge_html(estado_equipo(e))}</td><td><a class='pillbtn' href='/ot'>Crear OT</a></td></tr>"
        for e in atrasados_rows[:10]
    ) or "<tr><td colspan='6'>No hay equipos atrasados.</td></tr>"

    cards = "".join(
        f"<a class='equip-card {'danger' if is_bad_estado(estado_equipo(e)) else ''}' href='/equipos'><span class='dot {'red' if is_bad_estado(estado_equipo(e)) else 'green' if is_ok_estado(estado_equipo(e)) else 'yellow'}'></span><div class='machine'>🚜</div><h4>{codigo_equipo(e)}</h4><p>{tipo_equipo(e)}<br>{marca_modelo(e)}</p><small>{lectura_equipo(e)}</small></a>"
        for e in atrasados_rows[:12]
    ) or "<p>No hay equipos atrasados para mostrar.</p>"

    body = f"""
    <main class="page">
      <section class="kpis">
        {kpi_card("red", "!", "ATRASADOS", atrasados, f"{round((atrasados/max(total,1))*100,1)}% del total")}
        {kpi_card("yellow", "◷", "PRÓXIMOS", proximos, "En proceso / próximos")}
        {kpi_card("green", "✓", "CONTROLADO REAL", f"{control}%", f"{al_dia} de {total} equipos")}
        {kpi_card("blue", "▣", "OT ABIERTAS", ot, "Órdenes de trabajo")}
        {kpi_card("purple", "🛒", "COMPRAS", compras, fmt_clp(total_compras))}
        {kpi_card("teal", "$", "BODEGA", bodega, "Registros")}
      </section>

      <section class="dashboard-grid">
        <div class="panel">
          <h3>ESTADO GENERAL DE LA FLOTA</h3>
          <div class="donut-wrap"><div class="donut" style="{donut}"><span>{total}<small>Equipos</small></span></div>
          <div class="legend"><p><i class="ok"></i>Controlados <b>{al_dia}</b></p><p><i class="warn"></i>Próximos <b>{proximos}</b></p><p><i class="bad"></i>Atrasados <b>{atrasados}</b></p><p><i class="off"></i>Fuera/Taller <b>{fuera}</b></p></div></div>
        </div>
        <div class="panel"><h3>ATRASADOS POR UBICACIÓN</h3>{vertical_bars(ubic_data)}</div>
        <div class="panel"><h3>GESTIÓN OPERACIONAL</h3>{vertical_bars(gestion_data)}</div>
      </section>

      <section class="lower-grid">
        <div class="panel wide"><div class="section-head"><h3>EQUIPOS ATRASADOS</h3><a href="/equipos">Ver todos</a></div><table><thead><tr><th>Equipo</th><th>Tipo</th><th>Ubicación</th><th>Lectura</th><th>Estado</th><th>Acción</th></tr></thead><tbody>{atrasados_html}</tbody></table></div>
        <div class="panel"><h3>ACTIVIDAD RECIENTE</h3><div class="activity"><p>🟩 Mantenciones: {mantenciones}</p><p>🟦 Lecturas: {count_table("lecturas")}</p><p>🛒 Compras: {compras}</p><p>📦 Bodega: {bodega}</p></div></div>
      </section>

      <section class="panel"><h3>VISTA RÁPIDA ATRASADOS</h3><div class="cards-scroll">{cards}</div></section>
    </main>
    """
    return page("Dashboard", body)


def generic_table(title, table):
    rows = []
    if table_exists(table):
        try:
            rows = q(f"SELECT * FROM {table} LIMIT 800")
        except Exception:
            rows = []
    if not rows:
        return page(title, f"<main class='page'><section class='panel'><h2>{title}</h2><p>Sin datos en {table}.</p></section></main>")
    cols = list(rows[0].keys())
    head = "".join(f"<th>{c}</th>" for c in cols)
    body = "".join("<tr>" + "".join(f"<td>{safe(r.get(c))}</td>" for c in cols) + "</tr>" for r in rows)
    return page(title, f"<main class='page'><section class='panel'><div class='section-head'><h2>{title}</h2><a href='/'>Dashboard</a></div><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></section></main>")

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
    body = """
    <main class="page">
      <section class="panel">
        <h2>Administración DEMOTRON</h2>
        <div class="admin-grid">
          <div class="admin-card">
            <h3>Usuarios</h3>
            <p>Reparar o crear usuario administrador.</p>
            <a class="pillbtn" href="/admin/reparar-usuarios">Reparar admin</a>
            <p><b>Usuario:</b> admin<br><b>Contraseña:</b> admin123</p>
          </div>
          <div class="admin-card">
            <h3>Subir Excel</h3>
            <p>Preparado para módulo de carga. La base actual ya está conectada a PostgreSQL.</p>
            <button disabled>Subir Excel próximamente</button>
          </div>
          <div class="admin-card">
            <h3>Estado del deploy</h3>
            <p><a href="/test-deploy-demotron">Probar deploy</a></p>
            <p><a href="/api/status">Ver tablas</a></p>
          </div>
        </div>
      </section>
    </main>
    """
    return page("Admin", body)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
