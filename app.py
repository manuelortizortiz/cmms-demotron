import os
from datetime import datetime
from flask import Flask, jsonify, render_template_string, request, redirect, url_for, session
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "demotron-cmms-secret")

DATABASE_URL = os.getenv("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True) if DATABASE_URL else None

USERS = {
    "admin": generate_password_hash(os.getenv("ADMIN_PASSWORD", "admin123")),
    "gerencia": generate_password_hash(os.getenv("GERENCIA_PASSWORD", "gerencia123")),
}

EQUIPOS_COLS = ["codigo", "tipo_equipo", "familia", "marca", "modelo", "descripcion"]

def require_login():
    return bool(session.get("user"))

def table_exists(name):
    if not engine: return False
    try:
        return inspect(engine).has_table(name)
    except Exception:
        return False

def cols(table):
    try:
        return [c["name"] for c in inspect(engine).get_columns(table)]
    except Exception:
        return []

def safe_count(table):
    if not table_exists(table): return 0
    with engine.connect() as c:
        return c.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar() or 0

def fetch(sql, params=None):
    if not engine: return []
    with engine.connect() as c:
        return [dict(r._mapping) for r in c.execute(text(sql), params or {})]

def equipo_image(familia="", tipo="", descripcion=""):
    s = f"{familia} {tipo} {descripcion}".lower()
    if "motonivel" in s: return "/static/img/motoniveladora.svg"
    if "tolva" in s or "camión" in s or "camion" in s: return "/static/img/tolva.svg"
    if "cargador" in s: return "/static/img/cargador.svg"
    if "vehículo" in s or "vehiculo" in s or "camioneta" in s: return "/static/img/camioneta.svg"
    return "/static/img/excavadora.svg"

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        u = request.form.get("username", "")
        p = request.form.get("password", "")
        if u in USERS and check_password_hash(USERS[u], p):
            session["user"] = u
            return redirect(url_for("index"))
        error = "Usuario o contraseña incorrectos"
    return render_template_string(LOGIN_HTML, error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
def index():
    if not require_login(): return redirect(url_for("login"))
    return render_template_string(INDEX_HTML, user=session.get("user"))

@app.route("/api/equipos")
def api_equipos():
    if not require_login(): return jsonify({"error":"unauthorized"}), 401
    try:
        if not table_exists("equipos"):
            return jsonify([])
        available = cols("equipos")
        select_cols = [c for c in EQUIPOS_COLS if c in available]
        sql = f'SELECT {", ".join(select_cols)} FROM equipos ORDER BY codigo LIMIT 500' if select_cols else 'SELECT * FROM equipos LIMIT 500'
        data = fetch(sql)
        for e in data:
            e["estado_calculado"] = "Controlado"
            fam = e.get("familia","")
            cod = e.get("codigo","")
            if str(cod).startswith("CD"):
                e["estado_calculado"] = "Atrasado"
            elif str(cod).startswith("VD"):
                e["estado_calculado"] = "Próximo"
            e["ubicacion_calculada"] = "Sin ubicación"
            e["lectura_calculada"] = ""
            e["imagen"] = equipo_image(e.get("familia",""), e.get("tipo_equipo",""), e.get("descripcion",""))
        return jsonify(data)
    except SQLAlchemyError as ex:
        return jsonify({"error": str(ex)}), 500

@app.route("/api/dashboard")
def api_dashboard():
    if not require_login(): return jsonify({"error":"unauthorized"}), 401
    try:
        total = safe_count("equipos")
        lecturas = safe_count("lecturas")
        mantenciones = safe_count("mantenciones")
        bodega = safe_count("bodega")
        compras = safe_count("compras")
        pm = safe_count("PM") if table_exists("PM") else safe_count("pm")
        equipos = fetch('SELECT codigo, tipo_equipo, familia, marca, modelo, descripcion FROM equipos ORDER BY codigo LIMIT 500') if table_exists("equipos") else []
        atrasados = sum(1 for e in equipos if str(e.get("codigo","")).startswith("CD"))
        proximos = sum(1 for e in equipos if str(e.get("codigo","")).startswith("VD"))
        controlados = max(total - atrasados - proximos, 0)
        by_family = {}
        for e in equipos:
            f = e.get("familia") or e.get("tipo_equipo") or "Sin familia"
            by_family[f] = by_family.get(f, 0) + 1
        criticos = []
        for e in equipos[:12]:
            if str(e.get("codigo","")).startswith(("CD","MD")):
                criticos.append({**e, "imagen": equipo_image(e.get("familia",""), e.get("tipo_equipo",""), e.get("descripcion",""))})
        return jsonify({
            "total": total, "lecturas": lecturas, "mantenciones": mantenciones, "bodega": bodega,
            "compras": compras, "pm": pm, "atrasados": atrasados, "proximos": proximos,
            "controlados": controlados, "control_pct": round((controlados / total * 100), 1) if total else 0,
            "familias": [{"name": k, "value": v} for k,v in by_family.items()],
            "criticos": criticos[:8],
            "recent": [
              {"t":"Datos PostgreSQL conectados", "d": f"{total} equipos cargados desde tabla equipos"},
              {"t":"Lecturas disponibles", "d": f"{lecturas} registros en tabla lecturas"},
              {"t":"Compras/Bodega", "d": f"{compras} compras y {bodega} items de bodega"},
            ]
        })
    except SQLAlchemyError as ex:
        return jsonify({"error": str(ex)}), 500

@app.route("/api/<table>")
def api_table(table):
    if not require_login(): return jsonify({"error":"unauthorized"}), 401
    allowed = {"lecturas", "mantenciones", "bodega", "compras", "PM", "pm"}
    if table not in allowed: return jsonify({"error":"not allowed"}), 400
    if not table_exists(table): return jsonify([])
    return jsonify(fetch(f'SELECT * FROM "{table}" LIMIT 300'))

LOGIN_HTML = '''<!doctype html><html><head><title>Login DEMOTRON</title><style>body{margin:0;font-family:Arial;background:#f5f7fb;color:#0b214a}.box{width:330px;margin:12vh auto;background:white;padding:28px;border-radius:18px;box-shadow:0 10px 30px #d9dfeb}.logo{font-size:28px;letter-spacing:8px;font-weight:700;margin-bottom:20px}input,button{width:100%;padding:12px;margin:8px 0;border-radius:10px;border:1px solid #d8deea}button{background:#082657;color:white;border:0;cursor:pointer}.err{color:#d9303a;font-size:13px}</style></head><body><div class=box><div class=logo>DEMOTRON</div><form method=post><input name=username placeholder=Usuario value=admin><input name=password type=password placeholder=Contraseña value=admin123><button>Entrar</button></form>{% if error %}<div class=err>{{error}}</div>{% endif %}</div></body></html>'''

INDEX_HTML = '''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DEMOTRON CMMS</title><script src="https://cdn.jsdelivr.net/npm/chart.js"></script><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.2/css/all.min.css"><style>
*{box-sizing:border-box}body{margin:0;background:#f7f8fb;color:#14213d;font-family:Inter,Arial,sans-serif;font-size:12px;font-weight:400}.top{height:54px;background:white;display:flex;align-items:center;gap:22px;padding:0 20px;box-shadow:0 1px 8px #e6eaf1;position:sticky;top:0;z-index:5}.logo{font-size:26px;letter-spacing:8px;color:#0b2c60;font-weight:700}.nav{display:flex;gap:20px;flex:1}.nav a{color:#334; text-decoration:none}.nav a.active{color:#0b52c8;border-bottom:2px solid #0b52c8;padding:19px 0}.search{border:1px solid #e1e5ee;border-radius:8px;padding:9px 14px;color:#777}.user{font-size:12px}.wrap{padding:18px 20px 12px}.kpis{display:grid;grid-template-columns:repeat(6,1fr);gap:12px}.card{background:white;border-radius:8px;box-shadow:0 2px 10px #e7ebf2;padding:14px}.kpi{display:flex;align-items:center;gap:14px;min-height:92px}.circle{width:58px;height:58px;border-radius:50%;display:grid;place-items:center;color:white;font-size:25px}.red{background:#ee3c45}.yellow{background:#ffbd13}.green{background:#2fc469}.blue{background:#1f73dd}.purple{background:#7a3ddb}.teal{background:#049999}.kpi h3{margin:0;font-size:10px;letter-spacing:.5px;font-weight:600;text-transform:uppercase}.kpi .num{font-size:24px;font-weight:600;margin:6px 0;color:#111}.kpi small{color:#64748b}.grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-top:12px}.grid2{display:grid;grid-template-columns:2fr 1.2fr;gap:12px;margin-top:12px}.title{font-size:13px;font-weight:650;margin-bottom:10px;color:#0c1f42}.chartbox{height:210px}.table{width:100%;border-collapse:collapse;font-size:12px}.table th{text-align:left;font-weight:600;border-bottom:1px solid #e9edf5;padding:8px}.table td{border-bottom:1px solid #eef1f6;padding:8px}.badge{border-radius:15px;background:#ffe1e5;color:#e33642;padding:5px 10px;font-size:10px;font-weight:600}.btn{background:#0b2c60;color:white;border:0;border-radius:5px;padding:7px 12px;font-size:11px}.quick{margin-top:12px;display:flex;gap:12px;overflow:auto;padding-bottom:8px}.eq{background:white;border:1px solid #e4e8f0;border-radius:8px;width:150px;min-width:150px;padding:12px;box-shadow:0 2px 8px #e8ecf4}.eq img{height:45px;width:60px;object-fit:contain}.eq b{font-size:13px;font-weight:650}.dot{width:10px;height:10px;border-radius:50%;display:inline-block;margin-right:8px}.foot{background:#082657;color:white;padding:15px 20px;margin-top:12px;display:flex;justify-content:space-between}.page{display:none}.page.active{display:block}.data-grid{overflow:auto;max-height:70vh}@media(max-width:1100px){.kpis{grid-template-columns:repeat(3,1fr)}.grid,.grid2{grid-template-columns:1fr}.nav{display:none}}@media(max-width:650px){.kpis{grid-template-columns:1fr}.logo{font-size:18px}.search{display:none}}
</style></head><body><div class=top><div class=logo>DEMOTRON</div><div class=nav><a class=active onclick="show('dashboard',this)"><i class="fa-solid fa-table-cells-large"></i> Dashboard</a><a onclick="show('equipos',this)"><i class="fa-solid fa-truck-monster"></i> Equipos</a><a onclick="show('lecturas',this)"><i class="fa-regular fa-file-lines"></i> Lecturas</a><a onclick="show('compras',this)"><i class="fa-solid fa-cart-shopping"></i> Compras</a><a onclick="show('bodega',this)"><i class="fa-solid fa-warehouse"></i> Bodega</a></div><div class=search><i class="fa fa-search"></i> Buscar...</div><div class=user><i class="fa fa-user-circle"></i> {{user}} · <a href=/logout>Salir</a></div></div><div class=wrap>
<section id=dashboard class="page active"><div class=kpis><div class="card kpi"><div class="circle red"><i class="fa fa-exclamation"></i></div><div><h3>Atrasados</h3><div class=num id=k_atrasados>0</div><small id=p_atrasados></small></div></div><div class="card kpi"><div class="circle yellow"><i class="fa fa-clock"></i></div><div><h3>Próximos</h3><div class=num id=k_proximos>0</div><small>Vehículos/PM próximos</small></div></div><div class="card kpi"><div class="circle green"><i class="fa fa-check"></i></div><div><h3>Controlado Real</h3><div class=num id=k_control>0%</div><small id=k_total>0 equipos</small></div></div><div class="card kpi"><div class="circle blue"><i class="fa fa-clipboard-list"></i></div><div><h3>Mantenciones</h3><div class=num id=k_mant>0</div><small>Registros reales</small></div></div><div class="card kpi"><div class="circle purple"><i class="fa fa-cart-shopping"></i></div><div><h3>Compras</h3><div class=num id=k_compras>0</div><small>Tabla compras</small></div></div><div class="card kpi"><div class="circle teal"><i class="fa fa-warehouse"></i></div><div><h3>Bodega</h3><div class=num id=k_bodega>0</div><small>Items bodega</small></div></div></div><div class=grid><div class=card><div class=title>ESTADO GENERAL DE LA FLOTA</div><div class=chartbox><canvas id=donut></canvas></div></div><div class=card><div class=title>EQUIPOS POR FAMILIA</div><div class=chartbox><canvas id=barFamily></canvas></div></div><div class=card><div class=title>GESTIÓN REAL</div><div class=chartbox><canvas id=gestion></canvas></div></div></div><div class=grid2><div class=card><div class=title>EQUIPOS CRÍTICOS / PRINCIPALES</div><table class=table><thead><tr><th>Equipo</th><th>Descripción</th><th>Familia</th><th>Marca</th><th>Modelo</th><th>Acción</th></tr></thead><tbody id=criticos></tbody></table></div><div class=card><div class=title>ACTIVIDAD RECIENTE</div><div id=recent></div></div></div><div class=card><div class=title>EQUIPOS (VISTA RÁPIDA)</div><div class=quick id=quick></div></div></section>
<section id=equipos class=page><div class=card><div class=title>EQUIPOS</div><div class=data-grid><table class=table id=tablaEquipos></table></div></div></section>
<section id=lecturas class=page><div class=card><div class=title>LECTURAS</div><div class=data-grid><table class=table id=tablaLecturas></table></div></div></section>
<section id=compras class=page><div class=card><div class=title>COMPRAS</div><div class=data-grid><table class=table id=tablaCompras></table></div></div></section>
<section id=bodega class=page><div class=card><div class=title>BODEGA</div><div class=data-grid><table class=table id=tablaBodega></table></div></div></section></div><div class=foot><b>DEMOTRON CMMS</b><span>© 2026 Demotron Maquinarias</span><span>Versión Ultra Pro</span></div><script>
let charts=[];function show(id,el){document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));document.getElementById(id).classList.add('active');document.querySelectorAll('.nav a').forEach(a=>a.classList.remove('active'));el.classList.add('active'); if(id==='equipos')loadTable('/api/equipos','tablaEquipos'); if(id==='lecturas')loadTable('/api/lecturas','tablaLecturas'); if(id==='compras')loadTable('/api/compras','tablaCompras'); if(id==='bodega')loadTable('/api/bodega','tablaBodega')}
function pct(n,t){return t?((n/t)*100).toFixed(1)+'%':'0%'}
function renderChart(id,type,labels,data){let ctx=document.getElementById(id); let ch=new Chart(ctx,{type,data:{labels,datasets:[{data,label:'Registros'}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'bottom',labels:{boxWidth:10,font:{size:11}}}},scales:type==='doughnut'?{}:{y:{beginAtZero:true}}}});charts.push(ch)}
async function init(){let d=await fetch('/api/dashboard').then(r=>r.json());document.getElementById('k_atrasados').textContent=d.atrasados;document.getElementById('k_proximos').textContent=d.proximos;document.getElementById('k_control').textContent=d.control_pct+'%';document.getElementById('k_total').textContent=d.total+' equipos';document.getElementById('k_mant').textContent=d.mantenciones;document.getElementById('k_compras').textContent=d.compras;document.getElementById('k_bodega').textContent=d.bodega;document.getElementById('p_atrasados').textContent=pct(d.atrasados,d.total)+' del total';renderChart('donut','doughnut',['Controlados','Próximos','Atrasados'],[d.controlados,d.proximos,d.atrasados]);renderChart('barFamily','bar',d.familias.map(x=>x.name),d.familias.map(x=>x.value));renderChart('gestion','bar',['Lecturas','Mantenciones','Compras','Bodega','PM'],[d.lecturas,d.mantenciones,d.compras,d.bodega,d.pm]);document.getElementById('criticos').innerHTML=d.criticos.map(e=>`<tr><td><b>${e.codigo||''}</b></td><td>${e.descripcion||''}</td><td>${e.familia||''}</td><td>${e.marca||''}</td><td>${e.modelo||''}</td><td><button class=btn>Crear OT</button></td></tr>`).join('');document.getElementById('recent').innerHTML=d.recent.map(x=>`<p><i class="fa fa-circle-check" style="color:#13a36f"></i> <b>${x.t}</b><br><small>${x.d}</small></p>`).join('');let eq=await fetch('/api/equipos').then(r=>r.json());document.getElementById('quick').innerHTML=eq.slice(0,30).map(e=>`<div class=eq><span class="dot ${e.estado_calculado==='Atrasado'?'red':e.estado_calculado==='Próximo'?'yellow':'green'}"></span><b>${e.codigo||''}</b><br><img src="${e.imagen}"><div>${e.familia||e.tipo_equipo||''}</div><div>${e.marca||''} ${e.modelo||''}</div><small>${e.descripcion||''}</small></div>`).join('')}
function loadTable(url,id){fetch(url).then(r=>r.json()).then(rows=>{let t=document.getElementById(id); if(!rows.length){t.innerHTML='<tr><td>Sin datos</td></tr>';return} let keys=Object.keys(rows[0]).filter(k=>k!=='imagen'); t.innerHTML='<thead><tr>'+keys.map(k=>`<th>${k}</th>`).join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+keys.map(k=>`<td>${r[k]??''}</td>`).join('')+'</tr>').join('')+'</tbody>'})}
init();
</script></body></html>'''

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
