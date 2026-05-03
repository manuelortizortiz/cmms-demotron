import os
import re
import unicodedata
from functools import wraps

import pandas as pd
from flask import Flask, jsonify, render_template, request, redirect, url_for, session
from sqlalchemy import create_engine, text, inspect

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "demotron-secret")

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if DATABASE_URL:
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
    elif DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True) if DATABASE_URL else None

USERS = {
    "admin": "admin123",
    "gerencia": "gerencia123",
    "mantencion": "mantencion123",
}

def normalize_col(value):
    value = "" if value is None else str(value)
    value = value.strip().lower()
    value = "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "columna"

def clean_sheet(file_path, sheet):
    raw = pd.read_excel(file_path, sheet_name=sheet, header=None)
    header_row = 0
    for i in range(min(len(raw), 20)):
        vals = " ".join([str(v).lower() for v in raw.iloc[i].tolist() if pd.notna(v)])
        if "codigo" in vals or "fecha" in vals:
            header_row = i
            break
    df = pd.read_excel(file_path, sheet_name=sheet, header=header_row)
    df = df.dropna(how="all")
    df = df.dropna(axis=1, how="all")
    df.columns = [normalize_col(c) for c in df.columns]
    seen = {}
    cols = []
    for c in df.columns:
        if c not in seen:
            seen[c] = 0
            cols.append(c)
        else:
            seen[c] += 1
            cols.append(f"{c}_{seen[c]}")
    df.columns = cols
    return df

def import_excel():
    if engine is None:
        return {"ok": False, "error": "DATABASE_URL no configurada"}
    file_path = os.path.join(os.path.dirname(__file__), "data", "cmms.xlsx")
    if not os.path.exists(file_path):
        return {"ok": False, "error": "No existe data/cmms.xlsx"}
    sheets = {
        "Equipos": "equipos",
        "Lecturas": "lecturas",
        "Mantenciones": "mantenciones",
        "Compras PM": "compras",
        "Bodega": "bodega",
        "Plan_Mantenciones": "pm",
    }
    out = {}
    for sheet, table in sheets.items():
        try:
            df = clean_sheet(file_path, sheet)
            df.to_sql(table, engine, if_exists="replace", index=False)
            out[table] = len(df)
        except Exception as e:
            out[table] = f"ERROR: {e}"
    return {"ok": True, "imported": out}

def ensure_data():
    if engine is None:
        return
    try:
        insp = inspect(engine)
        tables = insp.get_table_names()
        if "equipos" not in tables:
            import_excel()
            return
        with engine.connect() as conn:
            total = conn.execute(text("SELECT COUNT(*) FROM equipos")).scalar() or 0
        if total <= 6:
            import_excel()
    except Exception:
        pass

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

def cols(table):
    try:
        return [c["name"] for c in inspect(engine).get_columns(table)]
    except Exception:
        return []

def best(columns, names):
    lower = {c.lower(): c for c in columns}
    for n in names:
        if n in lower:
            return lower[n]
    for c in columns:
        cl = c.lower()
        for n in names:
            if n in cl:
                return c
    return None

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        user = request.form.get("usuario", "")
        pw = request.form.get("password", "")
        if USERS.get(user) == pw:
            session["user"] = user
            return redirect(url_for("index"))
        error = "Usuario o contraseña incorrectos"
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
@login_required
def index():
    ensure_data()
    return render_template("index.html", user=session.get("user"))

@app.route("/equipos")
@login_required
def equipos():
    ensure_data()
    return render_template("equipos.html", user=session.get("user"))

@app.route("/lecturas")
@login_required
def lecturas():
    ensure_data()
    return render_template("lecturas.html", user=session.get("user"))

@app.route("/admin/importar-cmms")
@login_required
def importar():
    return jsonify(import_excel())

@app.route("/api/status")
def status():
    try:
        if engine is None:
            return jsonify({"status":"error","message":"DATABASE_URL no configurada"}), 500
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return jsonify({"status":"ok","database":"postgresql"})
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}), 500

@app.route("/api/equipos")
def api_equipos():
    ensure_data()
    try:
        columns = cols("equipos")
        if not columns:
            return jsonify([])
        c_codigo = best(columns, ["codigo", "equipo"])
        c_tipo = best(columns, ["tipo_equipo", "tipo"])
        c_marca = best(columns, ["marca"])
        c_modelo = best(columns, ["modelo"])
        c_ubic = best(columns, ["ubicacion", "obra", "faena"])
        c_estado = best(columns, ["estado_base", "estado", "control_base", "control"])
        c_desc = best(columns, ["descripcion", "detalle"])

        pairs = {
            "codigo": c_codigo,
            "tipo_equipo": c_tipo,
            "marca": c_marca,
            "modelo": c_modelo,
            "ubicacion": c_ubic,
            "estado": c_estado,
            "descripcion": c_desc,
        }
        select = []
        for alias, col in pairs.items():
            select.append(f'"{col}" AS {alias}' if col else f"'' AS {alias}")
        q = "SELECT " + ", ".join(select) + " FROM equipos"
        if c_codigo:
            q += f' ORDER BY "{c_codigo}"'
        with engine.connect() as conn:
            rows = conn.execute(text(q)).mappings().all()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({"error":str(e)}), 500

@app.route("/api/lecturas")
def api_lecturas():
    ensure_data()
    try:
        columns = cols("lecturas")
        if not columns:
            return jsonify([])
        c_fecha = best(columns, ["fecha"])
        c_codigo = best(columns, ["codigo", "equipo"])
        c_tipo = best(columns, ["tipo_lectura", "tipo"])
        c_valor = best(columns, ["valor", "lectura", "horometro", "odometro"])
        c_ubic = best(columns, ["ubicacion", "obra", "faena"])
        pairs = {"fecha":c_fecha,"codigo":c_codigo,"tipo_lectura":c_tipo,"valor":c_valor,"ubicacion":c_ubic}
        select = [f'"{col}" AS {alias}' if col else f"'' AS {alias}" for alias,col in pairs.items()]
        q = "SELECT " + ", ".join(select) + " FROM lecturas LIMIT 500"
        with engine.connect() as conn:
            rows = conn.execute(text(q)).mappings().all()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({"error":str(e)}), 500

@app.route("/api/dashboard")
def api_dashboard():
    ensure_data()
    equipos = api_equipos().get_json()
    lecturas = api_lecturas().get_json()
    if not isinstance(equipos, list):
        return jsonify(equipos), 500

    total = len(equipos)
    estado_counts = {}
    ubic_counts = {}
    tipo_counts = {}
    marca_counts = {}

    for e in equipos:
        estado = str(e.get("estado") or "SIN ESTADO").upper()
        ubic = str(e.get("ubicacion") or "SIN UBICACION")
        tipo = str(e.get("tipo_equipo") or "SIN TIPO")
        marca = str(e.get("marca") or "SIN MARCA")
        estado_counts[estado] = estado_counts.get(estado,0)+1
        ubic_counts[ubic] = ubic_counts.get(ubic,0)+1
        tipo_counts[tipo] = tipo_counts.get(tipo,0)+1
        marca_counts[marca] = marca_counts.get(marca,0)+1

    atrasados = sum(v for k,v in estado_counts.items() if "ATRAS" in k or "VENC" in k)
    proximos = sum(v for k,v in estado_counts.items() if "PROX" in k)
    controlados = max(total - atrasados - proximos, 0)

    return jsonify({
        "total_equipos": total,
        "total_lecturas": len(lecturas) if isinstance(lecturas, list) else 0,
        "atrasados": atrasados,
        "proximos": proximos,
        "controlados": controlados,
        "ot_abiertas": 0,
        "compras_proceso": 0,
        "costo_mensual": 0,
        "por_estado": [{"label":k,"total":v} for k,v in sorted(estado_counts.items(), key=lambda x:x[1], reverse=True)[:8]],
        "por_ubicacion": [{"label":k,"total":v} for k,v in sorted(ubic_counts.items(), key=lambda x:x[1], reverse=True)[:8]],
        "por_tipo": [{"label":k,"total":v} for k,v in sorted(tipo_counts.items(), key=lambda x:x[1], reverse=True)[:8]],
        "por_marca": [{"label":k,"total":v} for k,v in sorted(marca_counts.items(), key=lambda x:x[1], reverse=True)[:8]],
        "equipos": equipos[:80]
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
