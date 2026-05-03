fetch('/api/dashboard').then(r=>r.json()).then(d=>{
 document.getElementById('kpi-atrasados').textContent=d.atrasados; document.getElementById('sub-atrasados').textContent=((d.atrasados/(d.total||1))*100).toFixed(1)+'% del total';
 document.getElementById('kpi-proximos').textContent=d.proximos; document.getElementById('sub-proximos').textContent=((d.proximos/(d.total||1))*100).toFixed(1)+'% del total';
 document.getElementById('kpi-control').textContent=d.control_pct+'%'; document.getElementById('sub-control').textContent=d.controlados+' de '+d.total+' equipos';
 document.getElementById('kpi-ot').textContent=d.ot_abiertas; document.getElementById('kpi-compras').textContent=d.compras_proceso; document.getElementById('kpi-costo').textContent=moneyCLP(d.costo_mensual);
 makeDoughnut('flotaChart', Object.keys(d.estado_flota), Object.values(d.estado_flota));
 document.getElementById('legendFlota').innerHTML=Object.entries(d.estado_flota).map(([k,v],i)=>`<li><span><i class="dot" style="background:${['#31b96b','#ffbf00','#ef3340','#9ca3af'][i]}"></i>${k}</span><b>${v} (${((v/(d.total||1))*100).toFixed(1)}%)</b></li>`).join('');
 makeBar('ubicChart', Object.keys(d.atrasados_ubicacion), Object.values(d.atrasados_ubicacion)); makeGrouped('gestionChart', d.gestion.labels, d.gestion.ot, d.gestion.compras);
 document.getElementById('tablaCriticos').innerHTML=d.equipos_atrasados.map(e=>{let m=margin(e);return `<tr><td class="code">${e.codigo}</td><td>${e.tipo}</td><td>${e.ubicacion}</td><td>${fmt.format(Number(e.horometro||0))}</td><td>${e.proxima_pm||''}</td><td class="neg">${m!==''?m:''}</td><td><span class="badge red">ATRASADA</span></td><td><button class="btn-red">Crear OT</button></td></tr>`}).join('') || '<tr><td colspan="8">No hay equipos críticos.</td></tr>';
 document.getElementById('actividad').innerHTML=d.actividad.map(a=>`<div class="item"><i class="fa-solid ${a.icon}"></i><div><b>${a.tipo}</b><p>${a.texto||'Registro actualizado'}</p></div><time>Reciente</time></div>`).join('');
 document.getElementById('cardsEquipos').innerHTML=d.equipos_rapidos.map(cardEquipo).join('');
});
