
document.addEventListener("DOMContentLoaded", () => {
  if (!window.EQUIPOS) return;
  const byCode = {};
  window.EQUIPOS.forEach(e => { byCode[String(e.codigo || "").toUpperCase()] = e; });
  const codigoInput = document.querySelector("input[name='codigo']");
  if (!codigoInput) return;
  codigoInput.addEventListener("change", () => {
    const e = byCode[String(codigoInput.value || "").toUpperCase()];
    if (!e) return;
    ["tipo_equipo","familia","marca","modelo","ano","ubicacion","responsable","lectura_actual","unidad","proxima_pm","estado"].forEach(name => {
      const el = document.querySelector(`[name='${name}']`);
      if (el && e[name] !== undefined) el.value = e[name] || "";
    });
  });
});
