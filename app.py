
import os, re, unicodedata
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
USERS = {"admin":"admin123","gerencia":"gerencia123","mantencion":"mantencion123"}

def norm_col(v):
    v = "" if v is None else str(v)
    v = v.strip().lower()
    v = "".join(c for c in unicodedata.normalize("NFKD", v) if not unicodedata.combining(c))
    v = re.sub(r"[^a-z0-9]+","_",v)
    return re.sub(r"_+","_",v).strip("_") or "columna"

def key(v):
    if v is None: return ""
    v = str(v).strip().lower()
    v = "".join(c for c in unicodedata.normalize("NFKD", v) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+","_",v).strip("_")

def norm_ubic(v):
    if v is None: return ""
    raw = str(v).strip()
    if raw == "" or raw.lower() in ["nan","none","nat"]: return ""
    m = {
        "palmucho":"Palmucho","q_61":"Palmucho","q61":"Palmucho",
        "q_459":"Q-459","q459":"Q-459","quirihue":"Quirihue",
        "cobquecura":"Cobquecura","curico":"Curicó","san_carlos":"San Carlos",
        "oficina_central":"Oficina Central","san_nicolas":"San Nicolas",
        "taller":"Taller","villaseca":"Villaseca","pelluhue":"Pelluhue",
        "ninhue":"Ninhue","retiro":"Retiro","colbun":"Colbun",
        "taltal":"Taltal","talca":"Talca","santiago":"Santiago"
    }
    return m.get(key(raw), raw.title())

def safe(v):
    if v is None: return ""
    if isinstance(v,(datetime,date)): return v.strftime("%Y-%m-%d")
    s = str(v)
    if s.lower() in ["nan","none","nat"]: return ""
    return v

def num(v):
    try:
        if v is None or str(v).strip()=="": return 0
        return float(str(v).replace("$","").replace(" ","").replace(".","").replace(",","."))
    except Exception:
        try: return float(v)
        except Exception: return 0

def detect_header(file_path, sheet):
    raw = pd.read_excel(file_path, sheet_name=sheet, header=None)
    for i in range(min(len(raw), 30)):
        vals = [str(x).strip().lower() for x in raw.iloc[i].tolist() if pd.notna(x)]
        if "codigo" in vals or "fecha" in vals or "folio" in vals:
            return i
    return 0

def clean_sheet(file_path, sheet):
    hr = detect_header(file_path, sheet)
    df = pd.read_excel(file_path, sheet_name=sheet, header=hr)
    df = df.dropna(how="all").dropna(axis=1, how="all")
    df.columns = [norm_col(c) for c in df.columns]
    seen, cols = {}, []
    for c in df.columns:
        if c not in seen:
            seen[c]=0; cols.append(c)
        else:
            seen[c]+=1; cols.append(f"{c}_{seen[c]}")
    df.columns = cols
    for c in df.columns:
        if "fecha" in c:
            df[c] = pd.to_datetime(df[c], errors="coerce").dt.date
        if c in ["ubicacion","obra_ubicacion","destino","lugar"]:
            df[c] = df[c].apply(norm_ubic)
    return df

def import_excel():
    if engine is None:
        return {"ok":False,"error":"DATABASE_URL no configurada"}
    fp = os.path.join(os.path.dirname(__file__), "data", "cmms.xlsx")
    if not os.path.exists(fp):
        return {"ok":False,"error":"No existe data/cmms.xlsx"}

    sheets = {
        "Maestro_Equipos":"maestro_equipos",
        "Equipos":"equipos",
        "Lecturas":"lecturas",
        "Mantenciones":"mantenciones",
        "Compras PM":"compras",
        "Bodega":"bodega",
        "Plan_Mantenciones":"plan_mantenciones",
        "Plan_90_Dias":"plan_90_dias",
        "Planner_Semanal":"planner_semanal",
        "Dashboard":"dashboard_excel"
    }
    out={}
    for sh,tb in sheets.items():
        try:
            df = clean_sheet(fp, sh)
            df.to_sql(tb, engine, if_exists="replace", index=False)
            out[tb]=len(df)
        except Exception as e:
            out[tb]=f"ERROR: {e}"
    return {"ok":True,"imported":out}

def ensure_data():
    if engine is None: return
    try:
        insp = inspect(engine)
        if "maestro_equipos" not in insp.get_table_names():
            import_excel()
    except Exception:
        pass

def rows(sql, params=None):
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(text(sql), params or {}).mappings().all()]

def login_required(fn):
    @wraps(fn)
    def w(*a,**k):
        if not session.get("user"):
            return redirect(url_for("login"))
        return fn(*a,**k)
    return w

@app.route("/login", methods=["GET","POST"])
def login():
    err=None
    if request.method=="POST":
        u=request.form.get("usuario","")
        p=request.form.get("password","")
        if USERS.get(u)==p:
            session["user"]=u
            return redirect(url_for("index"))
        err="Usuario o contraseña incorrectos"
    return render_template("login.html", error=err)

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

@app.route("/ot")
@login_required
def ot_page():
    ensure_data()
    return render_template("ot.html", user=session.get("user"))

@app.route("/compras")
@login_required
def compras_page():
    ensure_data()
    return render_template("compras.html", user=session.get("user"))

@app.route("/bodega")
@login_required
def bodega_page():
    ensure_data()
    return render_template("bodega.html", user=session.get("user"))

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
        if not engine: return jsonify({"status":"error","message":"DATABASE_URL no configurada"}),500
        with engine.connect() as conn: conn.execute(text("SELECT 1"))
        return jsonify({"status":"ok","database":"postgresql"})
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}),500


@app.route("/api/equipos")
def api_equipos():
    ensure_data()
    try:
        inspector = inspect(engine)
        columns = [c["name"] for c in inspector.get_columns("maestro_equipos")]
        if not columns:
            return jsonify([])

        def find(*names):
            for n in names:
                for c in columns:
                    if c.lower() == n.lower():
                        return c
            for n in names:
                for c in columns:
                    if n.lower() in c.lower():
                        return c
            return None

        def alias(alias_name, col):
            if col:
                return f'"{col}" AS {alias_name}'
            return f"NULL AS {alias_name}"

        c_codigo = find("codigo")
        c_tipo = find("tipo_equipo", "tipo_de_equipo", "tipo")
        c_familia = find("familia")
        c_marca = find("marca")
        c_modelo = find("modelo")
        c_anio = find("ano", "anio", "a_o")
        c_ubicacion = find("ubicacion", "obra_ubicacion", "faena", "destino")
        c_responsable = find("responsable")
        c_lectura = find("lectura_actual", "ultimo_horometro", "ultimo_kilometraje", "horometro", "kilometraje")
        c_unidad = find("unidad", "control", "control_base")
        c_proxima = find("proxima_pm", "proxima_lectura_objetivo", "fecha_estimada", "proxima_mantencion")
        c_estado = find("estado", "estado_servicio", "estado_operativo", "control_base")

        if not c_codigo:
            return jsonify({"error": "No se encontró columna codigo en maestro_equipos", "columns": columns}), 500

        select_sql = ", ".join([
            alias("codigo", c_codigo),
            alias("tipo_equipo", c_tipo),
            alias("familia", c_familia),
            alias("marca", c_marca),
            alias("modelo", c_modelo),
            alias("anio", c_anio),
            alias("ubicacion", c_ubicacion),
            alias("responsable", c_responsable),
            alias("lectura_actual", c_lectura),
            alias("unidad", c_unidad),
            alias("proxima_pm", c_proxima),
            alias("estado", c_estado),
        ])

        q = f"""
            SELECT {select_sql}
            FROM maestro_equipos
            ORDER BY "{c_codigo}"
        """

        with engine.connect() as conn:
            result = conn.execute(text(q)).mappings().all()

        data = []
        for r in result:
            marca = safe(r.get("marca"))
            modelo = safe(r.get("modelo"))
            data.append({
                "codigo": safe(r.get("codigo")),
                "tipo_equipo": safe(r.get("tipo_equipo")),
                "familia": safe(r.get("familia")),
                "marca": marca,
                "modelo": modelo,
                "anio": safe(r.get("anio")),
                "ubicacion": norm_ubic(r.get("ubicacion")),
                "responsable": safe(r.get("responsable")),
                "lectura_actual": safe(r.get("lectura_actual")),
                "unidad": safe(r.get("unidad")),
                "proxima_pm": safe(r.get("proxima_pm")),
                "estado": safe(r.get("estado")),
                "descripcion": f"{marca} {modelo}".strip()
            })

        return jsonify(data)

    except Exception as e:
        try:
            inspector = inspect(engine)
            columns = [c["name"] for c in inspector.get_columns("maestro_equipos")]
        except Exception:
            columns = []
        return jsonify({"error": str(e), "columns": columns}), 500

@app.route("/api/lecturas")
def api_lecturas():
    ensure_data()
    try:
        q = """
        SELECT fecha,codigo,horometro,kilometraje,obra_ubicacion,responsable,observacion
        FROM lecturas
        ORDER BY fecha DESC NULLS LAST
        LIMIT 5000
        """
        data=[]
        for r in rows(q):
            hor=safe(r.get("horometro"))
            km=safe(r.get("kilometraje"))
            data.append({
                "fecha":safe(r.get("fecha")),
                "codigo":safe(r.get("codigo")),
                "horometro":hor,
                "kilometraje":km,
                "tipo_lectura":"HORAS" if hor not in ["",None] else "KM",
                "valor": hor if hor not in ["",None] else km,
                "ubicacion":norm_ubic(r.get("obra_ubicacion")),
                "responsable":safe(r.get("responsable")),
                "observacion":safe(r.get("observacion"))
            })
        return jsonify(data)
    except Exception as e:
        return jsonify({"error":str(e)}),500

@app.route("/api/mantenciones")
def api_mantenciones():
    ensure_data()
    try:
        q = """
        SELECT fecha,codigo,tipo_mantencion,lectura,espm,folio,lugar,proveedor,
               costo_mantencion_clp,estado
        FROM mantenciones
        ORDER BY fecha DESC NULLS LAST
        LIMIT 5000
        """
        data=[]
        for r in rows(q):
            data.append({
                "fecha":safe(r.get("fecha")),
                "codigo":safe(r.get("codigo")),
                "tipo":safe(r.get("tipo_mantencion")),
                "lectura":safe(r.get("lectura")),
                "espm":safe(r.get("espm")),
                "folio":safe(r.get("folio")),
                "lugar":norm_ubic(r.get("lugar")),
                "proveedor":safe(r.get("proveedor")),
                "costo":safe(r.get("costo_mantencion_clp")),
                "estado":safe(r.get("estado")),
                "descripcion":safe(r.get("tipo_mantencion"))
            })
        return jsonify(data)
    except Exception as e:
        return jsonify({"error":str(e)}),500

@app.route("/api/ot")
def api_ot():
    # OT se arma desde mantenciones reales: folio = OT/folio
    ensure_data()
    try:
        mant = api_mantenciones().get_json()
        if not isinstance(mant,list): return jsonify([])
        data=[]
        for i,m in enumerate(mant):
            data.append({
                "ot": m.get("folio") or f"OT-AUTO-{i+1:04d}",
                "fecha": m.get("fecha"),
                "codigo": m.get("codigo"),
                "tipo": m.get("tipo"),
                "lectura": m.get("lectura"),
                "estado": m.get("estado"),
                "costo": m.get("costo"),
                "proveedor": m.get("proveedor")
            })
        return jsonify(data)
    except Exception as e:
        return jsonify({"error":str(e)}),500

@app.route("/api/compras")
def api_compras():
    ensure_data()
    try:
        q = """
        SELECT fecha,oc,codigo,descripcion,proveedor,costo_pm_clp,regla,estado_oc
        FROM compras
        ORDER BY fecha DESC NULLS LAST
        LIMIT 5000
        """
        data=[]
        for r in rows(q):
            data.append({
                "fecha":safe(r.get("fecha")),
                "oc":safe(r.get("oc")),
                "codigo":safe(r.get("codigo")),
                "descripcion":safe(r.get("descripcion")),
                "proveedor":safe(r.get("proveedor")),
                "monto":safe(r.get("costo_pm_clp")),
                "regla":safe(r.get("regla")),
                "estado":safe(r.get("estado_oc"))
            })
        return jsonify(data)
    except Exception as e:
        return jsonify({"error":str(e)}),500

@app.route("/api/bodega")
def api_bodega():
    ensure_data()
    try:
        q = """
        SELECT folio,fecha,equipo,envio,persona_que_retiro,destino,comentario,codigo
        FROM bodega
        ORDER BY fecha DESC NULLS LAST
        LIMIT 5000
        """
        data=[]
        for r in rows(q):
            data.append({
                "folio":safe(r.get("folio")),
                "fecha":safe(r.get("fecha")),
                "equipo":safe(r.get("equipo")),
                "envio":safe(r.get("envio")),
                "persona":safe(r.get("persona_que_retiro")),
                "destino":norm_ubic(r.get("destino")),
                "comentario":safe(r.get("comentario")),
                "codigo":safe(r.get("codigo")),
            })
        return jsonify(data)
    except Exception as e:
        return jsonify({"error":str(e)}),500

@app.route("/api/proyeccion")
def api_proyeccion():
    ensure_data()
    try:
        q = """
        SELECT codigo,tipo_equipo,familia,control,lectura_actual,proxima_lectura_objetivo,
               promedio_diario,dias_estimados,fecha_estimada,estado_operativo,
               costo_total_pm,prioridad,accion_sugerida
        FROM plan_mantenciones
        ORDER BY prioridad ASC NULLS LAST, dias_estimados ASC NULLS LAST
        LIMIT 5000
        """
        data=[]
        for r in rows(q):
            data.append({
                "codigo":safe(r.get("codigo")),
                "tipo_equipo":safe(r.get("tipo_equipo")),
                "familia":safe(r.get("familia")),
                "control":safe(r.get("control")),
                "lectura_actual":safe(r.get("lectura_actual")),
                "proxima_pm":safe(r.get("proxima_lectura_objetivo")),
                "promedio_diario":safe(r.get("promedio_diario")),
                "dias_estimados":safe(r.get("dias_estimados")),
                "fecha_estimada":safe(r.get("fecha_estimada")),
                "estado":safe(r.get("estado_operativo")),
                "costo_total_pm":safe(r.get("costo_total_pm")),
                "prioridad":safe(r.get("prioridad")),
                "accion":safe(r.get("accion_sugerida")),
            })
        return jsonify(data)
    except Exception as e:
        return jsonify({"error":str(e)}),500

@app.route("/api/dashboard")
def api_dashboard():
    ensure_data()
    equipos = api_equipos().get_json()
    lecturas = api_lecturas().get_json()
    mant = api_mantenciones().get_json()
    compras = api_compras().get_json()
    bodega = api_bodega().get_json()
    proy = api_proyeccion().get_json()
    if not isinstance(equipos,list): return jsonify(equipos),500

    atrasados=sum(1 for e in equipos if "ATRAS" in str(e.get("estado","")).upper())
    al_dia=sum(1 for e in equipos if "AL D" in str(e.get("estado","")).upper())
    prox=sum(1 for e in equipos if any(x in str(e.get("estado","")).upper() for x in ["PROX","RECIBIR","PROCESO"]))
    fuera=sum(1 for e in equipos if "FUERA" in str(e.get("estado","")).upper())

    ubic,tipo,marca={}, {}, {}
    for e in equipos:
        for dic,val in [(ubic,e.get("ubicacion") or "Sin ubicación"),(tipo,e.get("tipo_equipo") or "Sin tipo"),(marca,e.get("marca") or "Sin marca")]:
            dic[val]=dic.get(val,0)+1

    use={}
    by={}
    if isinstance(lecturas,list):
        for r in lecturas:
            code=str(r.get("codigo") or "")
            val=num(r.get("valor"))
            if code and val: by.setdefault(code,[]).append(val)
        for c,vals in by.items():
            if len(vals)>=2: use[c]=max(vals)-min(vals)

    costs={}
    total_compras=0
    if isinstance(compras,list):
        for c in compras:
            m=num(c.get("monto")); total_compras+=m
            code=str(c.get("codigo") or "Sin código")
            costs[code]=costs.get(code,0)+m
    if isinstance(mant,list):
        for m in mant:
            cost=num(m.get("costo"))
            code=str(m.get("codigo") or "Sin código")
            costs[code]=costs.get(code,0)+cost

    def top(d,n=10): return [{"label":k,"total":v} for k,v in sorted(d.items(),key=lambda x:x[1],reverse=True)[:n]]

    return jsonify({
        "total_equipos":len(equipos),
        "total_lecturas":len(lecturas) if isinstance(lecturas,list) else 0,
        "total_mantenciones":len(mant) if isinstance(mant,list) else 0,
        "total_compras":total_compras,
        "total_bodega":len(bodega) if isinstance(bodega,list) else 0,
        "atrasados":atrasados,
        "proximos":prox,
        "controlados":al_dia,
        "fuera_servicio":fuera,
        "por_estado":[{"label":"Al día","total":al_dia},{"label":"Próx/Proceso/Recibir","total":prox},{"label":"Atrasados","total":atrasados},{"label":"Fuera de servicio","total":fuera}],
        "por_ubicacion":top(ubic),
        "por_tipo":top(tipo),
        "por_marca":top(marca),
        "uso_mensual":top(use),
        "costos_altos":top(costs),
        "compras_recientes":compras[:10] if isinstance(compras,list) else [],
        "mantenciones":mant[:10] if isinstance(mant,list) else [],
        "equipos":equipos[:120],
        "proyeccion":proy[:120] if isinstance(proy,list) else []
    })


@app.route("/api/debug/maestro-columnas")
def api_debug_maestro_columnas():
    try:
        inspector = inspect(engine)
        columns = [c["name"] for c in inspector.get_columns("maestro_equipos")]
        total = rows("SELECT COUNT(*) AS total FROM maestro_equipos")[0]["total"]
        return jsonify({"total": total, "columns": columns})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/debug/tablas")
def api_debug_tablas():
    try:
        inspector = inspect(engine)
        return jsonify({"tables": inspector.get_table_names()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",8080)))
