
import os
import re
import unicodedata
from datetime import date, datetime
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

UBICACIONES_CANONICAS = {
    "palmucho": "PALMUCHO",
    "q_61": "PALMUCHO",
    "q61": "PALMUCHO",
    "quirihue": "QUIRIHUE",
    "cobquecura": "COBQUECURA",
    "taltal": "TALTAL",
    "santiago": "SANTIAGO",
    "talca": "TALCA",
    "faena_norte": "FAENA NORTE",
    "q_459": "Q-459",
    "q459": "Q-459",
    "q_459_": "Q-459",
}

def text_key(value):
    if value is None:
        return ""
    value = str(value).strip().lower()
    value = "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))
    value = re.sub(r"[^a-z0-9]+", "_", value).strip("_")
    return value

def normalize_ubicacion(value):
    if value is None:
        return "SIN UBICACION"
    raw = str(value).strip()
    if raw == "" or raw.lower() in ["nan", "none", "nat"]:
        return "SIN UBICACION"
    key = text_key(raw)
    if key in UBICACIONES_CANONICAS:
        return UBICACIONES_CANONICAS[key]
    return raw.upper().replace("_", " ")

def normalize_col(value):
    value = "" if value is None else str(value)
    value = value.strip().lower()
    value = "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "columna"

# FIX 2026-05-03: encabezado real solo por Codigo/Fecha, no por 'equipo' en titulo

def clean_sheet(file_path, sheet):
    raw = pd.read_excel(file_path, sheet_name=sheet, header=None)
    header_row = 0

    for i in range(min(len(raw), 25)):
        vals = " ".join([str(v).lower() for v in raw.iloc[i].tolist() if pd.notna(v)])
        if "codigo" in vals or "fecha" in vals:
            header_row = i
            break

    df = pd.read_excel(file_path, sheet_name=sheet, header=header_row)
    df = df.dropna(how="all")
    df = df.dropna(axis=1, how="all")
    df.columns = [normalize_col(c) for c in df.columns]

    seen = {}
    final_cols = []
    for c in df.columns:
        if c not in seen:
            seen[c] = 0
            final_cols.append(c)
        else:
            seen[c] += 1
            final_cols.append(f"{c}_{seen[c]}")
    df.columns = final_cols

    for c in df.columns:
        if "fecha" in c:
            df[c] = pd.to_datetime(df[c], errors="coerce").dt.date
        if any(x in c for x in ["ubicacion", "obra", "faena"]):
            df[c] = df[c].apply(normalize_ubicacion)

    return df

def import_excel():
    if engine is None:
        return {"ok": False, "error": "DATABASE_URL no configurada"}

    file_path = os.path.join(os.path.dirname(__file__), "data", "cmms.xlsx")
    if not os.path.exists(file_path):
        return {"ok": False, "error": "No existe data/cmms.xlsx"}

    sheets = {
        "Maestro_Equipos": "maestro_equipos",
        "Dashboard": "dashboard_excel",
        "Equipos": "equipos",
        "Lecturas": "lecturas",
        "Mantenciones": "mantenciones",
        "Compras PM": "compras",
        "Bodega": "bodega",
        "Plan_Mantenciones": "plan_mantenciones",
        "Plan_90_Dias": "plan_90_dias",
        "Planner_Semanal": "planner_semanal",
    }

    imported = {}
    for sheet, table in sheets.items():
        try:
            df = clean_sheet(file_path, sheet)
            df.to_sql(table, engine, if_exists="replace", index=False)
            imported[table] = len(df)
        except Exception as e:
            imported[table] = f"ERROR: {e}"

    return {"ok": True, "imported": imported}

def ensure_data():
    if engine is None:
        return
    try:
        tables = inspect(engine).get_table_names()
        if "maestro_equipos" not in tables:
            import_excel()
            return
        with engine.connect() as conn:
            total = conn.execute(text("SELECT COUNT(*) FROM maestro_equipos")).scalar() or 0
        if total <= 10:
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

def best(columns, candidates):
    lower = {c.lower(): c for c in columns}
    for cand in candidates:
        if cand in lower:
            return lower[cand]
    for c in columns:
        cl = c.lower()
        for cand in candidates:
            if cand in cl:
                return c
    return None

def safe(v):
    if v is None:
        return ""
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    if str(v).lower() in ["nan", "nat", "none"]:
        return ""
    return v

def json_rows(rows):
    out = []
    for r in rows:
        d = dict(r)
        out.append({k: safe(v) for k, v in d.items()})
    return out

def select_alias(table, mapping, limit=None, order_col=None, desc=False):
    columns = cols(table)
    if not columns:
        return []

    parts = []
    for alias, candidates in mapping.items():
        col = best(columns, candidates)
        if col:
            parts.append(f'"{col}" AS {alias}')
        else:
            parts.append(f"'' AS {alias}")

    q = f"SELECT {', '.join(parts)} FROM {table}"
    if order_col:
        col = best(columns, order_col)
        if col:
            q += f' ORDER BY "{col}" {"DESC NULLS LAST" if desc else "ASC NULLS LAST"}'
    if limit:
        q += f" LIMIT {int(limit)}"

    with engine.connect() as conn:
        return json_rows(conn.execute(text(q)).mappings().all())

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        user = request.form.get("usuario", "")
        password = request.form.get("password", "")
        if USERS.get(user) == password:
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
def equipos_page():
    ensure_data()
    return render_template("equipos.html", user=session.get("user"))

@app.route("/lecturas")
@login_required
def lecturas_page():
    ensure_data()
    return render_template("lecturas.html", user=session.get("user"))

@app.route("/mantenciones")
@login_required
def mantenciones_page():
    ensure_data()
    return render_template("mantenciones.html", user=session.get("user"))

@app.route("/historial")
@login_required
def historial_page():
    ensure_data()
    return render_template("historial.html", user=session.get("user"))

@app.route("/proyeccion")
@login_required
def proyeccion_page():
    ensure_data()
    return render_template("proyeccion.html", user=session.get("user"))

@app.route("/admin/importar-cmms")
@login_required
def importar():
    return jsonify(import_excel())

@app.route("/api/status")
def api_status():
    try:
        if engine is None:
            return jsonify({"status": "error", "message": "DATABASE_URL no configurada"}), 500
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return jsonify({"status": "ok", "database": "postgresql"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/equipos")
def api_equipos():
    ensure_data()
    try:
        data = select_alias("maestro_equipos", {
            "codigo": ["codigo", "equipo"],
            "tipo_equipo": ["tipo_equipo", "tipo"],
            "familia": ["familia", "tipo_familia"],
            "marca": ["marca"],
            "modelo": ["modelo"],
            "anio": ["ano", "a_o", "year"],
            "ubicacion": ["ubicacion", "faena", "obra"],
            "responsable": ["responsable"],
            "estado": ["estado_servicio", "estado_base", "estado", "control_base", "control"],
            "lectura_actual": ["lectura_actual", "ultima_lectura", "horometro", "odometro", "valor"],
            "unidad": ["unidad", "tipo_lectura"],
            "proxima_pm": ["proxima_pm", "proxima_mantencion", "umbral_proximo_servicio"],
            "promedio_diario": ["promedio_diario"],
            "descripcion": ["descripcion", "detalle"],
        }, limit=2000)

        for e in data:
            e["ubicacion"] = normalize_ubicacion(e.get("ubicacion"))
            if not e.get("descripcion"):
                e["descripcion"] = f"{e.get('marca','')} {e.get('modelo','')}".strip()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/lecturas")
def api_lecturas():
    ensure_data()
    try:
        data = select_alias("lecturas", {
            "fecha": ["fecha", "fecha_lectura", "fecha_de_combustible"],
            "codigo": ["codigo", "equipo"],
            "tipo_lectura": ["tipo_lectura", "tipo"],
            "valor": ["valor", "lectura", "horometro", "odometro", "kilometro", "kilometros"],
            "ubicacion": ["ubicacion", "faena", "obra"],
            "responsable": ["responsable"],
            "observacion": ["observacion", "detalle"],
        }, limit=3000, order_col=["fecha"], desc=True)
        for r in data:
            r["ubicacion"] = normalize_ubicacion(r.get("ubicacion"))
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/mantenciones")
def api_mantenciones():
    ensure_data()
    try:
        data = select_alias("mantenciones", {
            "fecha": ["fecha", "fecha_mantencion"],
            "codigo": ["codigo", "equipo"],
            "tipo": ["tipo_mantencion", "tipo"],
            "estado": ["estado"],
            "lectura": ["lectura", "horometro", "odometro", "valor"],
            "descripcion": ["descripcion", "detalle", "observacion", "trabajo_realizado"],
            "costo": ["costo_mantencion_clp", "costo", "monto"],
            "oc": ["oc", "orden_compra"],
            "responsable": ["responsable"],
        }, limit=3000, order_col=["fecha"], desc=True)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/compras")
def api_compras():
    ensure_data()
    try:
        data = select_alias("compras", {
            "fecha": ["fecha"],
            "codigo": ["codigo", "equipo"],
            "oc": ["oc", "orden_compra"],
            "proveedor": ["proveedor"],
            "descripcion": ["descripcion", "detalle"],
            "estado": ["estado"],
            "monto": ["monto", "costo", "total", "valor"],
        }, limit=1000, order_col=["fecha"], desc=True)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/proyeccion")
def api_proyeccion():
    ensure_data()
    try:
        equipos = api_equipos().get_json()
        out = []
        for e in equipos:
            lectura = parse_num(e.get("lectura_actual"))
            proxima = parse_num(e.get("proxima_pm"))
            prom = parse_num(e.get("promedio_diario"))
            margen = None
            dias = None
            estado_calc = e.get("estado") or "SIN ESTADO"
            if lectura is not None and proxima is not None:
                margen = proxima - lectura
                if margen < 0:
                    estado_calc = "ATRASADA"
                elif margen <= 100:
                    estado_calc = "PROXIMA"
                else:
                    estado_calc = "CONTROLADA"
                if prom and prom > 0:
                    dias = round(margen / prom, 1)
            out.append({
                **e,
                "margen": margen if margen is not None else "",
                "dias_estimados": dias if dias is not None else "",
                "estado_calculado": estado_calc,
            })
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def parse_num(v):
    try:
        if v is None or str(v).strip() == "":
            return None
        s = str(v).replace(".", "").replace(",", ".")
        return float(s)
    except Exception:
        try:
            return float(v)
        except Exception:
            return None

@app.route("/api/dashboard")
def api_dashboard():
    ensure_data()
    equipos = api_equipos().get_json()
    lecturas = api_lecturas().get_json()
    mantenciones = api_mantenciones().get_json()
    compras = api_compras().get_json()
    proyeccion = api_proyeccion().get_json()

    if not isinstance(equipos, list):
        return jsonify(equipos), 500

    total = len(equipos)
    atrasados = sum(1 for e in proyeccion if "ATRAS" in str(e.get("estado_calculado", "")).upper()) if isinstance(proyeccion, list) else 0
    proximos = sum(1 for e in proyeccion if "PROX" in str(e.get("estado_calculado", "")).upper()) if isinstance(proyeccion, list) else 0
    controlados = max(total - atrasados - proximos, 0)

    ubic = {}
    tipo = {}
    marca = {}
    for e in equipos:
        u = normalize_ubicacion(e.get("ubicacion"))
        t = str(e.get("tipo_equipo") or e.get("familia") or "SIN TIPO").upper()
        m = str(e.get("marca") or "SIN MARCA").upper()
        ubic[u] = ubic.get(u, 0) + 1
        tipo[t] = tipo.get(t, 0) + 1
        marca[m] = marca.get(m, 0) + 1

    # Uso mensual: diferencia max-min por equipo usando lecturas con fecha
    usage = {}
    if isinstance(lecturas, list):
        by_code = {}
        for r in lecturas:
            code = str(r.get("codigo") or "").strip()
            val = parse_num(r.get("valor"))
            if not code or val is None:
                continue
            by_code.setdefault(code, []).append(val)
        for code, vals in by_code.items():
            if len(vals) >= 2:
                usage[code] = max(vals) - min(vals)

    # Costos por mantención/equipo
    cost_by_code = {}
    total_compras = 0
    if isinstance(compras, list):
        for c in compras:
            amount = parse_num(c.get("monto")) or 0
            total_compras += amount
            code = str(c.get("codigo") or "SIN CODIGO")
            cost_by_code[code] = cost_by_code.get(code, 0) + amount

    if isinstance(mantenciones, list):
        for m in mantenciones:
            amount = parse_num(m.get("costo")) or 0
            code = str(m.get("codigo") or "SIN CODIGO")
            cost_by_code[code] = cost_by_code.get(code, 0) + amount

    return jsonify({
        "total_equipos": total,
        "total_lecturas": len(lecturas) if isinstance(lecturas, list) else 0,
        "total_mantenciones": len(mantenciones) if isinstance(mantenciones, list) else 0,
        "total_compras": total_compras,
        "atrasados": atrasados,
        "proximos": proximos,
        "controlados": controlados,
        "por_estado": [
            {"label": "Controlados", "total": controlados},
            {"label": "Próximos", "total": proximos},
            {"label": "Atrasados", "total": atrasados},
        ],
        "por_ubicacion": [{"label": k, "total": v} for k, v in sorted(ubic.items(), key=lambda x: x[1], reverse=True)[:10]],
        "por_tipo": [{"label": k, "total": v} for k, v in sorted(tipo.items(), key=lambda x: x[1], reverse=True)[:10]],
        "por_marca": [{"label": k, "total": v} for k, v in sorted(marca.items(), key=lambda x: x[1], reverse=True)[:10]],
        "uso_mensual": [{"label": k, "total": round(v, 1)} for k, v in sorted(usage.items(), key=lambda x: x[1], reverse=True)[:10]],
        "costos_altos": [{"label": k, "total": round(v, 0)} for k, v in sorted(cost_by_code.items(), key=lambda x: x[1], reverse=True)[:10]],
        "compras_recientes": compras[:10] if isinstance(compras, list) else [],
        "mantenciones": mantenciones[:10] if isinstance(mantenciones, list) else [],
        "equipos": equipos[:120],
        "proyeccion": proyeccion[:120] if isinstance(proyeccion, list) else [],
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
