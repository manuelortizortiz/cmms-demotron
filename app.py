
import os
from datetime import datetime
from functools import wraps

from flask import Flask, request, redirect, url_for, session, jsonify, render_template_string
from sqlalchemy import create_engine, text, inspect
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "demotron-secret")

DEPLOY_VERSION = "DEMOTRON_PRO_ESTABLE_OT_HTML_GANTT_V3"

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


def safe(v):
    if v is None:
        return ""
    return str(v)


def table_exists(name):
    try:
        return engine is not None and name in inspect(engine).get_table_names()
    except Exception:
        return False


def columns(table):
    try:
        return [c["name"] for c in inspect(engine).get_columns(table)]
    except Exception:
        return []


def col_exists(table, col):
    return col in columns(table)


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
        codigo TEXT PRIMARY KEY,
        tipo_equipo TEXT,
        familia TEXT,
        marca TEXT,
        modelo TEXT,
        ano TEXT,
        ubicacion TEXT,
        responsable TEXT,
        lectura_actual TEXT,
        unidad TEXT,
        proxima_pm TEXT,
        estado TEXT
    )""", fetch=False)

    q("""CREATE TABLE IF NOT EXISTS lecturas (
        id SERIAL PRIMARY KEY,
        fecha DATE,
        codigo TEXT,
        horometro NUMERIC,
        kilometraje NUMERIC,
        obra_ubicacion TEXT,
        responsable TEXT,
        observacion TEXT
    )""", fetch=False)

    q("""CREATE TABLE IF NOT EXISTS mantenciones (
        id SERIAL PRIMARY KEY,
        fecha DATE,
        codigo TEXT,
        tipo_mantencion TEXT,
        lectura NUMERIC,
        espm TEXT,
        folio TEXT,
        lugar TEXT,
        proveedor TEXT,
        costo_mantencion_clp TEXT,
        estado TEXT
    )""", fetch=False)

    q("""CREATE TABLE IF NOT EXISTS ot (
        id SERIAL PRIMARY KEY,
        fecha DATE,
        ot TEXT,
        codigo TEXT,
        tipo TEXT,
        lectura TEXT,
        descripcion TEXT,
        responsable TEXT,
        estado TEXT,
        costo TEXT
    )""", fetch=False)

    q("""CREATE TABLE IF NOT EXISTS compras (
        id SERIAL PRIMARY KEY,
        fecha DATE,
        oc TEXT,
        codigo TEXT,
        descripcion TEXT,
        proveedor TEXT,
        costo_pm_clp TEXT,
        estado_oc TEXT
    )""", fetch=False)

    q("""CREATE TABLE IF NOT EXISTS bodega (
        id SERIAL PRIMARY KEY,
        folio TEXT,
        fecha DATE,
        equipo TEXT,
        envio TEXT,
        persona_que_retiro TEXT,
        destino TEXT,
        comentario TEXT,
        codigo TEXT
    )""", fetch=False)

    q("""CREATE TABLE IF NOT EXISTS plan_mantenciones (
        id SERIAL PRIMARY KEY,
        codigo TEXT,
        tipo_equipo TEXT,
        familia TEXT,
        control TEXT,
        lectura_actual TEXT,
        proxima_lectura_objetivo TEXT,
        promedio_diario TEXT,
        dias_estimados TEXT,
        fecha_estimada TEXT,
        estado_operativo TEXT,
        prioridad TEXT,
        accion_sugerida TEXT
    )""", fetch=False)

    q("""CREATE TABLE IF NOT EXISTS plan_90_dias (
        id SERIAL PRIMARY KEY,
        codigo TEXT,
        tipo_equipo TEXT,
        familia TEXT,
        control TEXT,
        lectura_actual TEXT,
        proxima_lectura_objetivo TEXT,
        promedio_diario TEXT,
        dias_estimados TEXT,
        fecha_estimada TEXT,
        estado_operativo TEXT,
        prioridad TEXT,
        accion_sugerida TEXT
    )""", fetch=False)


@app.before_request
def before_request():
    if request.endpoint != "static":
        try:
            ensure_schema()
        except Exception:
            pass


@app.errorhandler(404)
def not_found(e):
    return render_template_string("""
    <!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="stylesheet" href="/static/css/styles.css"></head><body>
    {{ nav|safe }}
    <main class="page"><section class="panel">
    <h2>Ruta no encontrada</h2>
    <p>La ruta solicitada no existe en esta versión.</p>
    <p><a class="btn" href="/">Volver al Dashboard</a> <a class="btn" href="/api/version">Ver versión</a></p>
    </section></main></body></html>
    """, nav=nav_html()), 200


@app.errorhandler(Exception)
def handle_error(e):
    return render_template_string("""
    <!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="stylesheet" href="/static/css/styles.css"></head><body>
    {{ nav|safe }}
    <main class="page"><section class="panel">
    <h2>Error controlado DEMOTRON</h2>
    <p>El sistema está activo, pero una consulta produjo error.</p>
    <pre>{{ error }}</pre>
    <p><a class="btn" href="/debug-dashboard">Ver debug</a> <a class="btn" href="/api/status">API Status</a></p>
    </section></main></body></html>
    """, nav=nav_html(), error=str(e)), 200


def nav_html():
    return """<header class="topbar">
      <a class="logo" href="/">DEMOTRON</a>
      <nav>
        <a href="/">Dashboard</a>
        <a href="/equipos">Equipos</a>
        <a href="/lecturas">Lecturas</a>
        <a href="/mantenciones">Mantención</a>
        <a href="/ot">OT</a>
        <a href="/compras">Compras</a>
        <a href="/bodega">Bodega</a>
        <a href="/planificacion">Plan Mantenciones</a>
        <a href="/plan-90-dias">Plan 90 días</a>
        <a href="/admin">Admin</a>
      </nav>
      <a class="logout" href="/logout">Salir</a>
    </header>"""


def page(title, body):
    return render_template_string(f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="/static/css/styles.css">
</head>
<body>
{nav_html()}
{body}
<footer>DEMOTRON CMMS ERP · {DEPLOY_VERSION}</footer>
</body>
</html>""")


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


def count_table(table):
    try:
        if table_exists(table):
            return q(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"]
    except Exception:
        pass
    return 0


def get_rows(table, limit=500):
    try:
        if table_exists(table):
            return q(f"SELECT * FROM {table} LIMIT {int(limit)}")
    except Exception:
        return []
    return []


def find_col(row, names):
    if not row:
        return ""
    for name in names:
        if name in row and row.get(name) is not None:
            return safe(row.get(name))
    for key, value in row.items():
        lk = str(key).lower()
        for name in names:
            if name.lower() in lk and value is not None:
                return safe(value)
    return ""


def estado(row):
    return find_col(row, ["estado_cmms", "estado_servicio", "estado_operativo", "estado"]) or "Sin estado"


def is_atrasado(row):
    s = estado(row).upper()
    return "ATRAS" in s or "VENC" in s


def is_proximo(row):
    s = estado(row).upper()
    return "PROX" in s or "RECIBIR" in s or "PROCESO" in s


def is_aldia(row):
    return "AL D" in estado(row).upper()


def badge(texto):
    s = safe(texto).upper()
    cls = "badge"
    if "ATRAS" in s or "VENC" in s:
        cls = "badge bad"
    elif "PROX" in s or "RECIBIR" in s or "PROCESO" in s:
        cls = "badge warn"
    elif "TALLER" in s or "FUERA" in s:
        cls = "badge off"
    return f"<span class='{cls}'>{safe(texto)}</span>"


def kpi(color, icon, title, value, sub=""):
    return f"""<div class="kpi-card {color}">
      <div class="kpi-icon">{icon}</div>
      <div><small>{title}</small><b>{value}</b><span>{sub}</span></div>
    </div>"""


def vertical_bars(items):
    if not items:
        items = [("Sin datos", 0)]
    maxv = max([v for _, v in items] + [1])
    html = ""
    for name, value in items:
        h = max(12, int((value / maxv) * 145)) if maxv else 12
        html += f"<div class='vbar-item'><strong>{value}</strong><div class='vbar' style='height:{h}px'></div><small>{safe(name)}</small></div>"
    return f"<div class='vertical-bars'>{html}</div>"


@app.route("/test-deploy-demotron")
def test_deploy():
    return f"OK NUEVO CODIGO {DEPLOY_VERSION}"


@app.route("/api/version")
def api_version():
    return jsonify({"status": "ok", "version": DEPLOY_VERSION})


@app.route("/api/status")
def api_status():
    return jsonify({
        "status": "ok",
        "version": DEPLOY_VERSION,
        "database": engine.dialect.name if engine else "sin database",
        "tables": inspect(engine).get_table_names() if engine else []
    })


@app.route("/debug-dashboard")
def debug_dashboard():
    info = {
        "version": DEPLOY_VERSION,
        "database": engine.dialect.name if engine else "sin database",
        "tables": inspect(engine).get_table_names() if engine else [],
        "counts": {
            "maestro_equipos": count_table("maestro_equipos"),
            "lecturas": count_table("lecturas"),
            "mantenciones": count_table("mantenciones"),
            "ot": count_table("ot"),
            "compras": count_table("compras"),
            "bodega": count_table("bodega"),
            "plan_mantenciones": count_table("plan_mantenciones"),
            "plan_90_dias": count_table("plan_90_dias"),
        }
    }
    return jsonify(info)


@app.route("/admin/reparar-usuarios")
@app.route("/admin/forzar-admin")
def reparar_usuarios():
    try:
        ensure_schema()
        q("DELETE FROM usuarios WHERE usuario=:u OR username=:u", {"u": "admin"}, fetch=False)
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
            row = q("SELECT * FROM usuarios WHERE usuario=:u OR username=:u LIMIT 1", {"u": usuario})
            if row and row[0].get("password_hash") and check_password_hash(row[0]["password_hash"], password):
                session["user"] = row[0].get("usuario") or row[0].get("username") or usuario
                session["rol"] = row[0].get("rol") or "usuario"
                return redirect(url_for("dashboard"))
            error = "Usuario o contraseña incorrectos"
        except Exception:
            error = "Use admin / admin123"

    return render_template_string(f"""<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
    <link rel="stylesheet" href="/static/css/styles.css"></head><body class="login">
    <form method="post" class="login-card">
    <h1>DEMOTRON</h1><p>CMMS ERP estable</p>
    <input name="usuario" value="admin" placeholder="Usuario">
    <input name="password" type="password" value="admin123" placeholder="Contraseña">
    {f'<div class="error">{error}</div>' if error else ''}
    <button>Entrar</button>
    <a href="/test-deploy-demotron">Probar deploy</a>
    </form></body></html>""")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))



def to_number(value):
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return float(value)
        txt = str(value).strip()
        if txt == "" or txt.lower() in ["nan", "none", "nat"]:
            return None
        txt = txt.replace("$", "").replace("CLP", "").replace("clp", "").replace(" ", "")
        if "," in txt:
            txt = txt.replace(".", "").replace(",", ".")
        elif txt.count(".") > 1:
            txt = txt.replace(".", "")
        return float(txt)
    except Exception:
        return None


def fmt_num(value):
    n = to_number(value)
    if n is None:
        return ""
    if abs(n - int(n)) < 0.00001:
        return f"{int(n):,}".replace(",", ".")
    return f"{n:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_clp_pro(value):
    n = to_number(value) or 0
    return "$ " + format(int(n), ",").replace(",", ".")


def lectura_real_equipo(codigo):
    codigo = safe(codigo).strip().upper()
    result = {"horas": None, "km": None, "lectura": "", "unidad": "", "origen": ""}

    if table_exists("lecturas"):
        for r in get_rows("lecturas", 50000):
            c = find_col(r, ["codigo", "equipo", "cod_equipo"]).strip().upper()
            if c != codigo:
                continue
            h = to_number(find_col(r, ["horometro", "horometros", "horas"]))
            k = to_number(find_col(r, ["kilometraje", "kilometro", "odometro", "km"]))
            if h is not None:
                result["horas"] = h if result["horas"] is None else max(result["horas"], h)
            if k is not None:
                result["km"] = k if result["km"] is None else max(result["km"], k)

    if table_exists("mantenciones"):
        for r in get_rows("mantenciones", 50000):
            c = find_col(r, ["codigo", "equipo", "cod_equipo"]).strip().upper()
            if c != codigo:
                continue
            lectura = to_number(find_col(r, ["lectura", "horometro", "kilometraje", "km"]))
            if lectura is None:
                continue
            hint = (find_col(r, ["unidad", "control"]) + " " + find_col(r, ["tipo_mantencion", "tipo"]) + " " + find_col(r, ["espm", "descripcion", "detalle"])).upper()
            if "KM" in hint or "KIL" in hint or lectura > 50000:
                result["km"] = lectura if result["km"] is None else max(result["km"], lectura)
            else:
                result["horas"] = lectura if result["horas"] is None else max(result["horas"], lectura)

    for r in get_rows("maestro_equipos", 50000):
        if find_col(r, ["codigo", "equipo"]).strip().upper() != codigo:
            continue
        base = to_number(find_col(r, ["lectura_actual", "horometro", "kilometraje", "odometro"]))
        unidad_base = find_col(r, ["unidad", "control"]).upper()
        if base is not None:
            if "KM" in unidad_base or "KIL" in unidad_base or base > 50000:
                result["km"] = base if result["km"] is None else max(result["km"], base)
            else:
                result["horas"] = base if result["horas"] is None else max(result["horas"], base)
        break

    if result["km"] is not None:
        result["lectura"] = fmt_num(result["km"])
        result["unidad"] = "KM"
        result["origen"] = "Máxima lectura KM"
    elif result["horas"] is not None:
        result["lectura"] = fmt_num(result["horas"])
        result["unidad"] = "HORAS"
        result["origen"] = "Máxima lectura HORAS"
    return result


def proxima_objetivo_equipo(row):
    for key in ["proxima_pm", "proxima_lectura_objetivo", "proxima", "umbral_proximo_servicio"]:
        n = to_number(find_col(row, [key]))
        if n is not None:
            return n
    return None


def estado_calculado(row):
    est = estado(row)
    s = est.upper()
    if "ATRAS" in s or "VENC" in s or "PROX" in s or "AL D" in s or "TALLER" in s or "FUERA" in s:
        return est
    codigo = find_col(row, ["codigo", "equipo"])
    lectura = lectura_real_equipo(codigo)
    actual = lectura.get("km") if lectura.get("km") is not None else lectura.get("horas")
    prox = proxima_objetivo_equipo(row)
    if actual is None or prox is None:
        return est or "Sin estado"
    margen = prox - actual
    if margen < 0:
        return "ATRASADA"
    if margen <= 250 or margen <= prox * 0.05:
        return "PRÓXIMA"
    return "AL DÍA"


def is_atrasado_calc(row):
    s = estado_calculado(row).upper()
    return "ATRAS" in s or "VENC" in s


def is_proximo_calc(row):
    s = estado_calculado(row).upper()
    return "PROX" in s or "PROCESO" in s or "RECIBIR" in s


def is_aldia_calc(row):
    return "AL D" in estado_calculado(row).upper()


def money_sum_pro():
    total = 0
    for table in ["compras", "mantenciones"]:
        if not table_exists(table):
            continue
        for r in get_rows(table, 50000):
            for key in ["costo_pm_clp", "costo_mantencion_clp", "monto", "valor", "total", "costo"]:
                n = to_number(find_col(r, [key]))
                if n is not None:
                    total += n
                    break
    return total


@app.route("/api/lectura-real/<codigo>")
def api_lectura_real(codigo):
    return jsonify(lectura_real_equipo(codigo))



@app.route("/")
@login_required
def dashboard():
    equipos = get_rows("maestro_equipos", 50000)
    total = len(equipos)

    atrasados_rows = [r for r in equipos if is_atrasado_calc(r)]
    atrasados = len(atrasados_rows)
    proximos = sum(1 for r in equipos if is_proximo_calc(r))
    al_dia = sum(1 for r in equipos if is_aldia_calc(r))
    en_taller = sum(1 for r in equipos if "TALLER" in estado_calculado(r).upper() or "FUERA" in estado_calculado(r).upper())
    control = round((al_dia / max(total, 1)) * 100)

    by_ubic = {}
    for r in atrasados_rows:
        u = find_col(r, ["ubicacion", "obra", "faena", "destino"]) or "Sin ubicación"
        by_ubic[u] = by_ubic.get(u, 0) + 1
    ubic_items = sorted(by_ubic.items(), key=lambda x: x[1], reverse=True)[:8]

    gestion_items = [
        ("OT", count_table("ot")),
        ("Compras", count_table("compras")),
        ("Bodega", count_table("bodega")),
        ("Mant.", count_table("mantenciones")),
    ]

    rows = ""
    for r in atrasados_rows[:10]:
        codigo = find_col(r, ["codigo", "equipo"])
        lectura = lectura_real_equipo(codigo)
        prox = proxima_objetivo_equipo(r)
        prox_txt = fmt_num(prox) if prox is not None else find_col(r, ["proxima_pm", "proxima"])
        rows += f"<tr><td>{codigo}</td><td>{find_col(r, ['tipo_equipo', 'tipo', 'familia'])}</td><td>{find_col(r, ['ubicacion', 'obra', 'faena'])}</td><td>{lectura['lectura']} {lectura['unidad']}</td><td>{prox_txt}</td><td>{badge(estado_calculado(r))}</td></tr>"
    if not rows:
        rows = "<tr><td colspan='6'>No hay equipos atrasados.</td></tr>"

    body = f"""
    <main class="page">
      <section class="kpis">
        {kpi("red", "!", "ATRASADOS", atrasados, "Equipos críticos")}
        {kpi("yellow", "◷", "PRÓXIMOS", proximos, "Proceso / próximos")}
        {kpi("green", "✓", "CONTROLADO REAL", f"{control}%", f"{al_dia} de {total}")}
        {kpi("blue", "▣", "EN TALLER / FS", en_taller, "No operativos")}
        {kpi("purple", "🛒", "COMPRAS", count_table("compras"), fmt_clp_pro(money_sum_pro()))}
        {kpi("teal", "$", "OT", count_table("ot"), "Órdenes")}
      </section>
      <section class="dashboard-grid">
        <div class="panel"><h3>Estado general de la flota</h3>{vertical_bars([('Al día', al_dia), ('Próx.', proximos), ('Atras.', atrasados), ('Taller', en_taller)])}</div>
        <div class="panel"><h3>Atrasados por ubicación</h3>{vertical_bars(ubic_items)}</div>
        <div class="panel"><h3>Gestión operacional</h3>{vertical_bars(gestion_items)}</div>
      </section>
      <section class="panel"><h3>Top 10 equipos atrasados</h3><table><thead><tr><th>Equipo</th><th>Tipo</th><th>Ubicación</th><th>Lectura real</th><th>Próxima PM</th><th>Estado</th></tr></thead><tbody>{rows}</tbody></table></section>
    </main>
    """
    return page("Dashboard PRO", body)



def equipo_by_codigo(codigo):
    codigo = safe(codigo).strip().upper()
    for r in get_rows("maestro_equipos", 50000):
        if find_col(r, ["codigo", "equipo", "cod_equipo"]).strip().upper() == codigo:
            return r
    return None


def equipo_historial(codigo):
    codigo = safe(codigo).strip().upper()
    eventos = []
    for tabla, origen in [("lecturas","Lectura"),("mantenciones","Mantención"),("ot","OT"),("compras","Compra"),("bodega","Bodega")]:
        if not table_exists(tabla):
            continue
        for r in get_rows(tabla, 50000):
            if find_col(r, ["codigo", "equipo", "cod_equipo"]).strip().upper() != codigo:
                continue
            eventos.append({
                "fecha": find_col(r, ["fecha", "fecha_de_combustible", "creado"]),
                "origen": origen,
                "detalle": find_col(r, ["descripcion", "detalle", "espm", "comentario", "tipo_mantencion", "tipo", "proveedor", "destino"]),
                "folio": find_col(r, ["ot", "folio", "orden", "oc", "lectura", "horometro", "kilometraje"]),
                "estado": find_col(r, ["estado", "estado_oc"])
            })
    return sorted(eventos, key=lambda x: safe(x.get("fecha")), reverse=True)


def equipo_icon(row):
    txt = (find_col(row, ["tipo_equipo", "tipo", "familia"]) + " " + find_col(row, ["marca"]) + " " + find_col(row, ["modelo"])).lower()
    if "camioneta" in txt or "maxus" in txt:
        return "🛻"
    if "camion" in txt or "tolva" in txt or "tracto" in txt:
        return "🚚"
    if "excav" in txt:
        return "🚜"
    if "cargador" in txt:
        return "🚧"
    if "moto" in txt or "niveladora" in txt:
        return "🏗️"
    return "⚙️"


def next_ot_code():
    return f"OT-{datetime.now().strftime('%Y%m%d')}-{count_table('ot')+1:04d}"


def ensure_ot_columns():
    ensure_schema()
    for col, ddl in [("fecha","DATE"),("ot","TEXT"),("codigo","TEXT"),("tipo","TEXT"),("lectura","TEXT"),("descripcion","TEXT"),("responsable","TEXT"),("estado","TEXT"),("costo","TEXT")]:
        add_col("ot", col, ddl)


def plan_rows_pro():
    table = "plan_mantenciones" if table_exists("plan_mantenciones") else "maestro_equipos"
    data = []
    for r in get_rows(table, 50000):
        codigo = find_col(r, ["codigo", "equipo", "cod_equipo"])
        if not codigo:
            continue
        eq = equipo_by_codigo(codigo) or r
        lectura = lectura_real_equipo(codigo)
        dias = to_number(find_col(r, ["dias_estimados", "dias", "dias_restantes"]))
        if dias is None:
            est = estado_calculado(eq).upper()
            dias = -5 if ("ATRAS" in est or "VENC" in est) else 10 if "PROX" in est else 45
        data.append({
            "codigo": codigo,
            "tipo": find_col(eq, ["tipo_equipo", "tipo", "familia"]),
            "ubicacion": find_col(eq, ["ubicacion", "obra", "faena"]),
            "lectura": f"{lectura.get('lectura','')} {lectura.get('unidad','')}",
            "proxima": find_col(r, ["proxima_lectura_objetivo", "proxima_pm", "proxima"]),
            "dias": int(dias),
            "fecha": find_col(r, ["fecha_estimada", "fecha", "fecha_planificada"]),
            "estado": find_col(r, ["estado_operativo", "estado"]) or estado_calculado(eq),
            "accion": find_col(r, ["accion_sugerida", "accion", "descripcion"]) or "Programar PM"
        })
    return sorted(data, key=lambda x: (x["dias"], x["codigo"]))


def gantt_class(dias, estado):
    s = safe(estado).upper()
    if dias < 0 or "ATRAS" in s or "VENC" in s:
        return "bad"
    if dias <= 15 or "PROX" in s or "PROCESO" in s:
        return "warn"
    if "TALLER" in s or "FUERA" in s:
        return "off"
    return "ok"



def generic_table(title, table):
    rows = get_rows(table, 800)
    if not rows:
        return page(title, f"<main class='page'><section class='panel'><h2>{title}</h2><p>Sin datos en {table}.</p></section></main>")
    cols = list(rows[0].keys())
    head = "".join(f"<th>{c}</th>" for c in cols)
    if table == "ot":
        head += "<th>Imprimir</th>"
    body = ""
    for r in rows:
        body += "<tr>"
        for c in cols:
            v = safe(r.get(c))
            if table == "maestro_equipos" and c.lower() in ["codigo", "equipo"]:
                v = f"<a href='/equipo/{v}'><b>{v}</b></a>"
            body += f"<td>{v}</td>"
        if table == "ot":
            body += f"<td><a class='pillbtn' href='/ot/{r.get('id')}/imprimir'>Imprimir</a></td>"
        body += "</tr>"
    button = "<a class='btn' href='/ot/nueva'>Nueva OT</a>" if table == "ot" else ""
    return page(title, f"<main class='page'><section class='panel'><div class='section-head'><h2>{title}</h2>{button}</div><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></section></main>")


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
def plan_90_dias():
    return generic_table("Plan 90 días", "plan_90_dias")


@app.route("/admin")
@login_required
def admin():
    body = """
    <main class="page">
      <section class="panel">
        <h2>Administración</h2>
        <p><a class="btn" href="/admin/reparar-usuarios">Reparar usuario admin</a></p>
        <p><b>Usuario:</b> admin · <b>Contraseña:</b> admin123</p>
        <p><a class="btn" href="/api/status">Ver tablas PostgreSQL</a></p>
      </section>
    </main>
    """
    return page("Admin", body)


@app.route("/equipo/<codigo>")
@login_required
def ficha_equipo(codigo):
    eq = equipo_by_codigo(codigo)
    if not eq:
        return page("Equipo no encontrado", f"<main class='page'><section class='panel'><h2>Equipo {safe(codigo)}</h2><p>No se encontró.</p></section></main>")
    lectura = lectura_real_equipo(codigo)
    hist_rows = ""
    for h in equipo_historial(codigo)[:80]:
        hist_rows += f"<tr><td>{safe(h['fecha'])}</td><td>{safe(h['origen'])}</td><td>{safe(h['detalle'])}</td><td>{safe(h['folio'])}</td><td>{badge(h['estado']) if h['estado'] else ''}</td></tr>"
    if not hist_rows:
        hist_rows = "<tr><td colspan='5'>Sin historial registrado.</td></tr>"
    body = f"""
    <main class="page">
      <section class="ficha-hero"><div class="equipo-photo">{equipo_icon(eq)}</div><div><h1>{find_col(eq, ['codigo','equipo'])}</h1><p>{find_col(eq, ['tipo_equipo','tipo','familia'])} · {find_col(eq, ['marca'])} {find_col(eq, ['modelo'])}</p><p>{find_col(eq, ['ubicacion','obra','faena'])} · {badge(estado_calculado(eq))}</p></div><div class="ficha-actions"><a class="btn" href="/ot/nueva?codigo={safe(codigo)}">Crear OT</a><a class="btn" href="/lecturas">Agregar lectura</a></div></section>
      <section class="dashboard-grid"><div class="panel"><h3>Lectura real</h3><div class="big-number">{lectura.get('lectura','')}</div><p>{lectura.get('unidad','')} · {lectura.get('origen','')}</p></div><div class="panel"><h3>Próxima PM</h3><div class="big-number">{find_col(eq, ['proxima_pm','proxima']) or '-'}</div><p>Objetivo mantenimiento</p></div><div class="panel"><h3>Estado</h3><div class="big-number small">{estado_calculado(eq)}</div><p>Calculado por CMMS</p></div></section>
      <section class="panel"><h3>Historial del equipo</h3><table><thead><tr><th>Fecha</th><th>Origen</th><th>Detalle</th><th>Folio/Lectura</th><th>Estado</th></tr></thead><tbody>{hist_rows}</tbody></table></section>
    </main>"""
    return page(f"Ficha {safe(codigo)}", body)


@app.route("/ot/nueva", methods=["GET", "POST"])
@login_required
def ot_nueva():
    ensure_ot_columns()
    codigo = request.args.get("codigo", "")
    if request.method == "POST":
        data = {"fecha": request.form.get("fecha") or datetime.now().date().isoformat(), "ot": request.form.get("ot") or next_ot_code(), "codigo": (request.form.get("codigo") or "").upper(), "tipo": request.form.get("tipo") or "PM", "lectura": request.form.get("lectura") or "", "descripcion": request.form.get("descripcion") or "", "responsable": request.form.get("responsable") or session.get("user","admin"), "estado": request.form.get("estado") or "EN PROCESO", "costo": request.form.get("costo") or ""}
        q("INSERT INTO ot (fecha,ot,codigo,tipo,lectura,descripcion,responsable,estado,costo) VALUES (:fecha,:ot,:codigo,:tipo,:lectura,:descripcion,:responsable,:estado,:costo)", data, fetch=False)
        return redirect(url_for("ot"))
    lectura = lectura_real_equipo(codigo) if codigo else {"lectura":"", "unidad":""}
    body = f"""<main class="page"><section class="panel"><h2>Nueva Orden de Trabajo</h2><form class="form-grid" method="post"><input type="date" name="fecha" value="{datetime.now().date().isoformat()}"><input name="ot" value="{next_ot_code()}" placeholder="N° OT"><input name="codigo" value="{safe(codigo)}" placeholder="Código equipo"><select name="tipo"><option>PM1</option><option>PM2</option><option>PM3</option><option>PM4</option><option>PM5</option><option>CORRECTIVA</option></select><input name="lectura" value="{lectura.get('lectura','')} {lectura.get('unidad','')}" placeholder="Lectura"><input name="responsable" placeholder="Responsable" value="{session.get('user','admin')}"><select name="estado"><option>EN PROCESO</option><option>PROGRAMADO</option><option>EJECUTADA</option><option>PENDIENTE</option></select><input name="costo" placeholder="Costo CLP"><textarea name="descripcion" placeholder="Descripción del trabajo solicitado"></textarea><button>Crear OT</button></form></section></main>"""
    return page("Nueva OT", body)


@app.route("/ot/<int:ot_id>/imprimir")
@login_required
def ot_imprimir(ot_id):
    rows = q("SELECT * FROM ot WHERE id=:id LIMIT 1", {"id": ot_id}) if table_exists("ot") else []
    if not rows:
        return page("OT no encontrada", "<main class='page'><section class='panel'><h2>OT no encontrada</h2></section></main>")
    r = rows[0]
    eq = equipo_by_codigo(find_col(r, ["codigo"])) or {}
    body = f"""
    <main class="print-page">
      <section class="ot-print">
        <div class="ot-head"><div><h1>DEMOTRON</h1><p>Orden de Trabajo</p></div><div><b>{find_col(r, ['ot']) or 'OT'}</b><br>{find_col(r, ['fecha'])}</div></div>
        <h2>Datos del equipo</h2>
        <div class="ot-grid">
          <p><b>Equipo:</b> {find_col(r, ['codigo'])}</p>
          <p><b>Tipo OT:</b> {find_col(r, ['tipo'])}</p>
          <p><b>Marca/Modelo:</b> {find_col(eq, ['marca'])} {find_col(eq, ['modelo'])}</p>
          <p><b>Ubicación:</b> {find_col(eq, ['ubicacion','obra','faena'])}</p>
          <p><b>Lectura:</b> {find_col(r, ['lectura'])}</p>
          <p><b>Responsable:</b> {find_col(r, ['responsable'])}</p>
          <p><b>Estado:</b> {find_col(r, ['estado'])}</p>
          <p><b>Costo:</b> {find_col(r, ['costo'])}</p>
        </div>
        <h2>Descripción del trabajo</h2>
        <div class="ot-box">{find_col(r, ['descripcion'])}</div>
        <h2>Checklist de ejecución</h2>
        <div class="checklist">
          <p>☐ Bloqueo y seguridad del equipo</p><p>☐ Inspección visual general</p><p>☐ Revisión de niveles</p><p>☐ Revisión de filtros</p><p>☐ Prueba operacional</p><p>☐ Registro lectura final</p>
        </div>
        <div class="firmas"><div>Ejecutor</div><div>Supervisor</div></div>
        <button class="print-btn" onclick="window.print()">Imprimir / Guardar PDF</button>
      </section>
    </main>
    """
    return page("Imprimir OT", body)


@app.route("/planificacion/gantt")
@app.route("/gantt")
@login_required
def planificacion_gantt():
    data = plan_rows_pro()
    quick = "<form class='form-grid' method='get' action='/ot/nueva'><input name='codigo' placeholder='Equipo'><input type='date' name='fecha'><select name='tipo'><option>PM1</option><option>PM2</option><option>PM3</option><option>PM4</option><option>PM5</option></select><button>Crear OT rápida</button></form>"
    gantt = ""; rows = ""
    for r in data[:200]:
        cls = gantt_class(r["dias"], r["estado"]); width = 95 if cls == "bad" else 75 if cls == "warn" else 45
        gantt += f"<a class='gantt-row gantt-{cls}' href='/equipo/{r['codigo']}'><div><b>{r['codigo']}</b><small>{r['tipo']}</small></div><div>{r['ubicacion']}</div><div>{r['accion']}</div><div class='gantt-track'><span class='{cls}' style='width:{width}%'></span></div><div>{r['fecha'] or 'Sin fecha'}<br><small>{r['dias']} días</small></div><div>{badge(r['estado'])}</div></a>"
        rows += f"<tr><td>{r['codigo']}</td><td>{r['tipo']}</td><td>{r['ubicacion']}</td><td>{r['lectura']}</td><td>{r['proxima']}</td><td>{r['dias']}</td><td>{r['fecha']}</td><td>{badge(r['estado'])}</td></tr>"
    body = f"<main class='page'><section class='panel'><h2>Planificación PM tipo Gantt</h2>{quick}</section><section class='panel'><h3>Carta Gantt</h3><div class='gantt'>{gantt}</div></section><section class='panel'><h3>Tabla detallada</h3><table><thead><tr><th>Equipo</th><th>Tipo</th><th>Ubicación</th><th>Lectura</th><th>Próxima</th><th>Días</th><th>Fecha</th><th>Estado</th></tr></thead><tbody>{rows}</tbody></table></section></main>"
    return page("Planificación Gantt", body)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
