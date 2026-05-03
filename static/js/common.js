const fmt = new Intl.NumberFormat('es-CL');
function moneyCLP(n){ return '$ ' + fmt.format(Math.round(Number(n||0))); }
function machineImg(e){
 const t=((e.tipo||'')+' '+(e.codigo||'')).toLowerCase();
 if(t.includes('motonivel')||t.startsWith('md')) return '/static/img/motoniveladora.svg';
 if(t.includes('cargador')||t.includes('loader')) return '/static/img/cargador.svg';
 if(t.includes('tolva')||t.includes('camion')||t.includes('camión')||t.startsWith('cd')) return '/static/img/tolva.svg';
 if(t.includes('excav')||t.includes('sany')) return '/static/img/excavadora.svg';
 return '/static/img/equipo.svg';
}
function statusClass(e){ const s=(e.estado||'').toLowerCase(); if(s.includes('atras')||s.includes('venc')||s.includes('crit')) return 'bad'; if(s.includes('prox')||s.includes('próx')) return 'prox'; return ''; }
function margin(e){ const h=Number(e.horometro||0), p=Number(e.proxima_pm||0); if(!p) return ''; return p-h; }
function cardEquipo(e){ const m=margin(e); const sc=statusClass(e); return `<div class="equipment-card ${sc==='bad'?'danger':''}"><span class="status-dot ${sc}"></span><h4>${e.codigo||'S/C'}</h4><p>${e.tipo||'Equipo'}<br>${e.ubicacion||'Sin ubicación'}</p><img src="${machineImg(e)}" alt="equipo"><div class="meta">Lectura: ${fmt.format(Number(e.horometro||0))}<br>${m!==''?`Margen: <span class="${m<0?'neg':'pos'}">${m>0?'+':''}${fmt.format(m)}</span>`:''}</div></div>` }
function makeDoughnut(id, labels, data){ return new Chart(document.getElementById(id),{type:'doughnut',data:{labels,datasets:[{data,backgroundColor:['#31b96b','#ffbf00','#ef3340','#9ca3af'],borderWidth:0}]},options:{responsive:true,plugins:{legend:{display:false}},cutout:'62%'}}); }
function makeBar(id, labels, data, label='Equipos atrasados'){ return new Chart(document.getElementById(id),{type:'bar',data:{labels,datasets:[{label,data,backgroundColor:'#ef3340',borderRadius:2}]},options:{responsive:true,plugins:{legend:{position:'bottom',labels:{boxWidth:10,font:{size:11}}}},scales:{x:{ticks:{font:{size:11}},grid:{display:false}},y:{beginAtZero:true,ticks:{font:{size:11}}}}}}); }
function makeGrouped(id, labels, ot, compras){ return new Chart(document.getElementById(id),{type:'bar',data:{labels,datasets:[{label:'OT Creadas',data:ot,backgroundColor:'#1f6fe5',borderRadius:2},{label:'Compras',data:compras,backgroundColor:'#7b3fe4',borderRadius:2}]},options:{responsive:true,plugins:{legend:{position:'bottom',labels:{boxWidth:10,font:{size:11}}}},scales:{x:{ticks:{font:{size:11}},grid:{display:false}},y:{beginAtZero:true,ticks:{font:{size:11}}}}}}); }
function renderTable(targetHead,targetBody, data){ const head=document.getElementById(targetHead), body=document.getElementById(targetBody); if(!data||!data.length){body.innerHTML='<tr><td>Sin datos en la tabla.</td></tr>';return} const cols=Object.keys(data[0]).slice(0,9); head.innerHTML='<tr>'+cols.map(c=>`<th>${c}</th>`).join('')+'</tr>'; body.innerHTML=data.slice(0,200).map(r=>'<tr>'+cols.map(c=>`<td>${r[c]??''}</td>`).join('')+'</tr>').join(''); }
