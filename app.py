
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

def text_key(value):
    if value is None:
        return ""
    value = str(value).strip().lower()
    value = "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))
    value = re.sub(r"[^a-z0-9]+", "_", value).strip("_")
    return value

def normalize_ubicacion(value):
    if value is None:
        return ""
    raw = str(value).strip()
    if raw == "" or raw.lower() in ["nan", "none", "nat"]:
        return ""
    key = text_key(raw)
    mapa = {
        "palmucho": "Palmucho",
        "q_61": "Palmucho",
        "q61": "Palmucho",
        "q_459": "Q-459",
        "q459": "Q-459",
        "quirihue": "Quirihue",
        "cobquecura": "Cobquecura",
        "curico": "Curicó",
        "san_carlos": "San Carlos",
        "oficina_central": "Oficina Central",
        "san_nicolas": "San Nicolas",
        "taller": "Taller",
        "villaseca": "Villaseca",
        "pelluhue": "Pelluhue",
        "ninhue": "Ninhue",
        "retiro": "Retiro",
        "colbun": "Colbun",
    }
    return mapa.get(key, raw.title())

def normalize_col(value):
    value = "" if value is None else str(value)
    value = value.strip().lower()
    value = "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "columna"

def clean_sheet(file_path, sheet):
    raw = pd.read_excel(file_path, sheet_name=sheet, header=None)

    # IMPORTANTE:
    # El encabezado real del Maestro_Equipos es la fila donde existe una celda EXACTA "Codigo".
    # No usar la palabra "equipo", porque la fila 1 dice "Maestro de Equipos" y rompe columnas.
    header_row = 0
    for i in range(min(len(raw), 30)):
        vals = [str(v).strip().lower() for v in raw.iloc[i].tolist() if pd.notna(v)]
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
        if c in ["ubicacion", "faena", "obra"]:
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
    except Exception:
        pass

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

def safe(v):
    if v is None:
        return ""
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    s = str(v)
    if s.lower() in ["nan", "nat", "none"]:
        return ""
    return v

def parse_num(v):
    try:
        if v is None or str(v).strip() == "":
            return None
        s = str(v).replace(".", "").replace(",", ".")
        return float(s)
    except Exception:
        return None

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
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT
                    codigo,
                    tipo_equipo,
                    familia,
                    marca,
                    modelo,
                    ano,
                    ubicacion,
                    responsable,
                    lectura_actual,
                    unidad,
                    proxima_pm,
                    estado
                FROM maestro_equipos
                ORDER BY codigo
            """)).mappings().all()

        data = []
        for r in rows:
            data.append({
                "codigo": safe(r.get("codigo")),
                "tipo_equipo": safe(r.get("tipo_equipo")),
                "familia": safe(r.get("familia")),
                "marca": safe(r.get("marca")),
                "modelo": safe(r.get("modelo")),
                "anio": safe(r.get("ano")),
                "ubicacion": normalize_ubicacion(r.get("ubicacion")),
                "responsable": safe(r.get("responsable")),
                "lectura_actual": safe(r.get("lectura_actual")),
                "unidad": safe(r.get("unidad")),
                "proxima_pm": safe(r.get("proxima_pm")),
                "estado": safe(r.get("estado")),
                "descripcion": f"{safe(r.get('marca'))} {safe(r.get('modelo'))}".strip()
            })

        return jsonify(data)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/lecturas")
def api_lecturas():
    ensure_data()
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT
                    fecha,
                    codigo,
                    tipo_lectura,
                    valor,
                    ubicacion,
                    responsable,
                    observacion
                FROM lecturas
                ORDER BY fecha DESC NULLS LAST
                LIMIT 3000
            """)).mappings().all()

        data = []
        for r in rows:
            data.append({
                "fecha": safe(r.get("fecha")),
                "codigo": safe(r.get("codigo")),
                "tipo_lectura": safe(r.get("tipo_lectura")),
                "valor": safe(r.get("valor")),
                "ubicacion": normalize_ubicacion(r.get("ubicacion")),
                "responsable": safe(r.get("responsable")),
                "observacion": safe(r.get("observacion")),
            })
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/mantenciones")
def api_mantenciones():
    ensure_data()
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT *
                FROM mantenciones
                ORDER BY fecha DESC NULLS LAST
                LIMIT 3000
            """)).mappings().all()

        data = []
        for r in rows:
            d = {k: safe(v) for k, v in dict(r).items()}
            data.append({
                "fecha": d.get("fecha", ""),
                "codigo": d.get("codigo", ""),
                "tipo": d.get("tipo", d.get("tipo_mantencion", "")),
                "estado": d.get("estado", ""),
                "lectura": d.get("lectura", ""),
                "descripcion": d.get("descripcion", d.get("observacion", "")),
                "costo": d.get("costo_mantencion_clp", d.get("costo", "")),
                "oc": d.get("oc", ""),
                "responsable": d.get("responsable", ""),
            })
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/compras")
def api_compras():
    ensure_data()
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT *
                FROM compras
                LIMIT 1000
            """)).mappings().all()

        data = []
        for r in rows:
            d = {k: safe(v) for k, v in dict(r).items()}
            data.append({
                "fecha": d.get("fecha", ""),
                "codigo": d.get("codigo", ""),
                "oc": d.get("oc", d.get("orden_compra", "")),
                "proveedor": d.get("proveedor", ""),
                "descripcion": d.get("descripcion", ""),
                "estado": d.get("estado", ""),
                "monto": d.get("monto", d.get("total", d.get("valor", ""))),
            })
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
            # proxima_pm en tu maestro a veces viene como fecha; por eso no la fuerzo si no es número.
            proxima = parse_num(e.get("proxima_pm"))
            margen = ""
            dias = ""
            estado_calc = e.get("estado") or ""
            if lectura is not None and proxima is not None:
                margen = round(proxima - lectura, 1)
                if margen < 0:
                    estado_calc = "ATRASADA"
                elif margen <= 100:
                    estado_calc = "PRÓXIMA"
                else:
                    estado_calc = "AL DÍA"
            out.append({
                **e,
                "margen": margen,
                "dias_estimados": dias,
                "estado_calculado": estado_calc,
            })
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
    atrasados = sum(1 for e in equipos if "ATRAS" in str(e.get("estado", "")).upper())
    proximos = sum(1 for e in equipos if "PROX" in str(e.get("estado", "")).upper() or "POR RECIBIR" in str(e.get("estado", "")).upper())
    fuera = sum(1 for e in equipos if "FUERA" in str(e.get("estado", "")).upper())
    controlados = sum(1 for e in equipos if "AL D" in str(e.get("estado", "")).upper())

    ubic = {}
    tipo = {}
    marca = {}
    for e in equipos:
        u = normalize_ubicacion(e.get("ubicacion")) or "Sin ubicación"
        t = str(e.get("tipo_equipo") or "Sin tipo")
        m = str(e.get("marca") or "Sin marca")
        ubic[u] = ubic.get(u, 0) + 1
        tipo[t] = tipo.get(t, 0) + 1
        marca[m] = marca.get(m, 0) + 1

    usage = {}
    if isinstance(lecturas, list):
        by_code = {}
        for r in lecturas:
            code = str(r.get("codigo") or "").strip()
            val = parse_num(r.get("valor"))
            if code and val is not None:
                by_code.setdefault(code, []).append(val)
        for code, vals in by_code.items():
            if len(vals) >= 2:
                usage[code] = max(vals) - min(vals)

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
        "fuera_servicio": fuera,
        "por_estado": [
            {"label": "Al día", "total": controlados},
            {"label": "Próximos / por recibir", "total": proximos},
            {"label": "Atrasados", "total": atrasados},
            {"label": "Fuera de servicio", "total": fuera},
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
