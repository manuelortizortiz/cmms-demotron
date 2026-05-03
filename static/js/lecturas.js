
fetch("/api/lecturas").then(r=>r.json()).then(data=>{
 const tbody=document.getElementById("tablaLecturas");
 tbody.innerHTML=(Array.isArray(data)?data:[]).map(e=>`<tr><td>${e.fecha||""}</td><td><b>${e.codigo||""}</b></td><td>${e.tipo_lectura||""}</td><td>${e.valor||""}</td><td>${e.ubicacion||""}</td></tr>`).join("");
});
