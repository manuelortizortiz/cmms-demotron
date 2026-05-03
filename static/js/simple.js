fetch('/api/'+window.ENDPOINT).then(r=>r.json()).then(d=>renderTable('head','body',d));
