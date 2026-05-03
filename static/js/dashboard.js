
const fmt = n => new Intl.NumberFormat("es-CL").format(Number(n||0));
function iconFor(e){
  const t = ((e.tipo_equipo||"") + " " + (e.descripcion||"") + " " + (e.modelo||"")).toLowerCase();
  if(t.includes("excav")) return "🚜";
  if(t.includes("moto")) return "🏗️";
  if(t.includes("tolva") || t.includes("camión") || t.includes("camion")) return "🚚";
  if(t.includes("cargador")) return "🚜";
  if(t.includes("veh") || t.includes("camioneta")) return "🚙";
  return "⚙️";
}
function badge(e){
  const s = (e||"").toUpperCase();
  if(s.includes("ATRAS")||s.includes("VENC")) return "badge bad";
  if(s.includes("PROX")) return "badge warn";
  return "badge";
}
function drawChart(id,type,items){
  const ctx=document.getElementById(id);
  if(!ctx)return;
  new Chart(ctx,{type,data:{labels:items.map(x=>x.label),datasets:[{data:items.map(x=>x.total),borderWidth:1}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:"right",labels:{boxWidth:10,font:{size:10}}}},scales:type==="bar"?{y:{beginAtZero:true,ticks:{font:{size:10}}},x:{ticks:{font:{size:10}}}}:{}}});
}
async function loadDash(){
  const r=await fetch("/api/dashboard");
  const d=await r.json();
  document.getElementById("kpi-atrasados").textContent=fmt(d.atrasados);
  document.getElementById("kpi-proximos").textContent=fmt(d.proximos);
  document.getElementById("kpi-controlados").textContent=fmt(d.controlados);
  document.getElementById("kpi-total").textContent=fmt(d.total_equipos)+" equipos";
  document.getElementById("kpi-ot").textContent=fmt(d.ot_abiertas);
  document.getElementById("kpi-compras").textContent=fmt(d.compras_proceso);
  document.getElementById("kpi-costo").textContent="$"+fmt(d.costo_mensual);
  drawChart("chartEstado","doughnut",d.por_estado||[]);
  drawChart("chartUbicacion","bar",d.por_ubicacion||[]);
  drawChart("chartTipo","bar",d.por_tipo||[]);
  const crit=document.getElementById("tablaCriticos");
  const equipos=d.equipos||[];
  crit.innerHTML=equipos.slice(0,8).map(e=>`<tr><td><b>${e.codigo||""}</b></td><td>${e.descripcion||e.tipo_equipo||""}</td><td>${e.ubicacion||""}</td><td><span class="${badge(e.estado)}">${e.estado||"CONTROLADO"}</span></td><td><button class="btn redbtn">Crear OT</button></td></tr>`).join("");
  document.getElementById("actividad").innerHTML=[
    ["▣","Base CMMS conectada a PostgreSQL"],
    ["▤",`Lecturas cargadas: ${fmt(d.total_lecturas)}`],
    ["✓",`Equipos cargados: ${fmt(d.total_equipos)}`],
    ["🛒","Compras PM disponibles"],
    ["⚙️","Importador Excel automático activo"]
  ].map(a=>`<div class="act"><div class="act-ico">${a[0]}</div><div>${a[1]}<br><small>Hoy</small></div></div>`).join("");
  document.getElementById("quickCards").innerHTML=equipos.slice(0,18).map(e=>`<div class="machine-card"><span class="dot ${badge(e.estado).includes("bad")?"red":badge(e.estado).includes("warn")?"yellow":"green"}"></span><h4>${e.codigo||""}</h4><div class="machine">${iconFor(e)}</div><p>${e.marca||""} ${e.modelo||""}</p><p>${e.ubicacion||""}</p><p>${e.estado||"CONTROLADO"}</p></div>`).join("");
}
loadDash();
