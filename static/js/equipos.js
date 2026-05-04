
function badge(s){
  s=(s||"").toUpperCase();
  if(s.includes("ATRAS") || s.includes("VENC")) return "badge bad";
  if(s.includes("PROX") || s.includes("POR RECIBIR") || s.includes("PROCESO")) return "badge warn";
  return "badge";
}

fetch("/api/equipos")
  .then(r => r.json())
  .then(data => {
    const tbody = document.getElementById("tablaEquipos");
    if (!Array.isArray(data)) {
      tbody.innerHTML = `<tr><td colspan="12">${data.error || "Error cargando equipos"}</td></tr>`;
      return;
    }

    tbody.innerHTML = data.map(e => `
      <tr>
        <td><b>${e.codigo || ""}</b></td>
        <td>${e.tipo_equipo || ""}</td>
        <td>${e.familia || ""}</td>
        <td>${e.marca || ""}</td>
        <td>${e.modelo || ""}</td>
        <td>${e.anio || ""}</td>
        <td>${e.ubicacion || ""}</td>
        <td>${e.responsable || ""}</td>
        <td>${e.lectura_actual || ""}</td>
        <td>${e.unidad || ""}</td>
        <td>${e.proxima_pm || ""}</td>
        <td><span class="${badge(e.estado)}">${e.estado || ""}</span></td>
      </tr>
    `).join("");
  });
