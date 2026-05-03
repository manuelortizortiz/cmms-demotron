import os
from datetime import datetime
from functools import wraps
from flask import Flask, jsonify, render_template, request, redirect, session, url_for
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "demotron-ultra-pro-change-me")

DATABASE_URL = os.getenv("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://") and "+psycopg" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True) if DATABASE_URL else None

DEFAULT_USERS = {
    "admin": generate_password_hash("admin123"),
    "gerencia": generate_password_hash("gerencia123"),
    "mantencion": generate_password_hash("mantencion123"),
}

TABLES = {
    "equipos": ["equipos"],
    "lecturas": ["lecturas"],
    "mantenciones": ["mantenciones"],
    "bodega": ["bodega"],
    "compras": ["compras"],
    "pm": ["pm", "PM"],
}

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

def db_ready():
    return engine is not None

def q(sql, params=None):
    if not db_ready():
        return []
    with engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(text(sql), params or {})]

def table_exists(name):
    try:
        rows = q("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema='public' AND table_name=:name LIMIT 1
        """, {"name": name})
        return bool(rows)
    except Exception:
        return False

def resolve_table(key):
    for name in TABLES.get(key, [key]):
        if table_exists(name):
            return name
    return TABLES.get(key, [key])[0]

def columns(table):
    try:
        rows = q("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema='public' AND table_name=:table
        """, {"table": table})
        return {r["column_name"] for r in rows}
    except Exception:
        return set()

def safe_count(table):
    try:
        if not table_exists(table):
            return 0
        return q(f'SELECT COUNT(*) AS total FROM "{table}"')[0]["total"]
    except Exception:
        return 0

def normalize_equipo(row):
    codigo = row.get("codigo") or row.get("Código") or row.get("cod") or ""
    tipo = row.get("tipo") or row.get("descripcion") or row.get("equipo") or row.get("familia") or "Equipo"
    estado = row.get("estado") or row.get("estado_operacional") or row.get("status") or "Sin estado"
    ubicacion = row.get("ubicacion") or row.get("ubicación") or row.get("obra") or row.get("faena") or "Sin ubicación"
    horometro = row.get("horometro") or row.get("horómetro") or row.get("lectura_actual") or row.get("km") or row.get("kilometraje") or 0
    return {"codigo": codigo, "tipo": tipo, "estado": estado, "ubicacion": ubicacion, "horometro": horometro}

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        user = request.form.get("usuario", "").strip()
        pwd = request.form.get("password", "")
        if user in DEFAULT_USERS and check_password_hash(DEFAULT_USERS[user], pwd):
            session["user"] = user
            return redirect(url_for("dashboard"))
        error = "Usuario o clave incorrecta"
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
@login_required
def dashboard():
    return render_template("dashboard.html", user=session.get("user"))

@app.route("/equipos")
@login_required
def equipos_page():
    return render_template("equipos.html", user=session.get("user"))

@app.route("/lecturas")
@login_required
def lecturas_page():
    return render_template("lecturas.html", user=session.get("user"))

@app.route("/api/status")
def api_status():
    try:
        if not db_ready():
            return jsonify({"database":"missing DATABASE_URL", "status":"error"}), 500
        q("SELECT 1 AS ok")
        return jsonify({"database":"postgresql", "status":"ok"})
    except Exception as e:
        return jsonify({"database":"postgresql", "status":"error", "detail":str(e)}), 500

@app.route("/api/equipos")
@login_required
def api_equipos():
    table = resolve_table("equipos")
    if not table_exists(table):
        return jsonify([])
    cols = columns(table)
    wanted = [c for c in ["codigo", "tipo", "estado", "ubicacion", "horometro"] if c in cols]
    select = ", ".join([f'"{c}"' for c in wanted]) or "*"
    order = 'ORDER BY "codigo"' if "codigo" in cols else ""
    limit = int(request.args.get("limit", 500))
    rows = q(f'SELECT {select} FROM "{table}" {order} LIMIT :limit', {"limit": limit})
    return jsonify([normalize_equipo(r) for r in rows])

@app.route("/api/lecturas")
@login_required
def api_lecturas():
    table = resolve_table("lecturas")
    if not table_exists(table):
        return jsonify([])
    cols = columns(table)
    order_col = next((c for c in ["fecha", "created_at", "fecha_lectura", "Fecha"] if c in cols), None)
    order = f'ORDER BY "{order_col}" DESC' if order_col else ""
    rows = q(f'SELECT * FROM "{table}" {order} LIMIT 300')
    return jsonify(rows)

@app.route("/api/mantenciones")
@login_required
def api_mantenciones():
    table = resolve_table("mantenciones")
    if not table_exists(table):
        return jsonify([])
    rows = q(f'SELECT * FROM "{table}" LIMIT 300')
    return jsonify(rows)

@app.route("/api/dashboard")
@login_required
def api_dashboard():
    equipos_table = resolve_table("equipos")
    lecturas_table = resolve_table("lecturas")
    mant_table = resolve_table("mantenciones")
    bodega_table = resolve_table("bodega")
    compras_table = resolve_table("compras")
    pm_table = resolve_table("pm")

    equipos = []
    if table_exists(equipos_table):
        cols = columns(equipos_table)
        rows = q(f'SELECT * FROM "{equipos_table}" LIMIT 1000')
        equipos = [normalize_equipo(r) for r in rows]

    total = len(equipos)
    atrasados = sum(1 for e in equipos if "ATRAS" in str(e.get("estado","")).upper() or "VENC" in str(e.get("estado","")).upper())
    taller = sum(1 for e in equipos if "TALLER" in str(e.get("estado","")).upper() or "FUERA" in str(e.get("estado","")).upper())
    operativos = max(total - atrasados - taller, 0)
    proximos = sum(1 for e in equipos if "PROX" in str(e.get("estado","")).upper() or "PRÓX" in str(e.get("estado","")).upper())

    by_ubicacion = {}
    by_tipo = {}
    for e in equipos:
        by_ubicacion[e["ubicacion"]] = by_ubicacion.get(e["ubicacion"], 0) + 1
        by_tipo[e["tipo"]] = by_tipo.get(e["tipo"], 0) + 1

    data = {
        "kpis": {
            "equipos": total,
            "operativos": operativos,
            "atrasados": atrasados,
            "proximos": proximos,
            "taller": taller,
            "lecturas": safe_count(lecturas_table),
            "mantenciones": safe_count(mant_table),
            "bodega": safe_count(bodega_table),
            "compras": safe_count(compras_table),
            "pm": safe_count(pm_table),
        },
        "ubicaciones": sorted([{"name":k, "value":v} for k,v in by_ubicacion.items()], key=lambda x: x["value"], reverse=True)[:10],
        "tipos": sorted([{"name":k, "value":v} for k,v in by_tipo.items()], key=lambda x: x["value"], reverse=True)[:8],
        "equipos": equipos[:80],
        "updated_at": datetime.now().strftime("%d-%m-%Y %H:%M")
    }
    return jsonify(data)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)), debug=True)
