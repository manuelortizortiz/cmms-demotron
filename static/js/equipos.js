
function badge(e){const s=(e||"").toUpperCase(); if(s.includes("ATRAS")||s.includes("VENC"))return"badge bad"; if(s.includes("PROX"))return"badge warn"; return"badge";}
fetch("/api/equipos").then(r=>r.json()).then(data=>{
 const tbody=document.getElementById("tablaEquipos");
 tbody.innerHTML=(Array.isArray(data)?data:[]).map(e=>`<tr><td><b>${e.codigo||""}</b></td><td>${e.tipo_equipo||""}</td><td>${e.marca||""}</td><td>${e.modelo||""}</td><td>${e.ubicacion||""}</td><td><span class="${badge(e.estado)}">${e.estado||""}</span></td><td>${e.descripcion||""}</td></tr>`).join("");
});
