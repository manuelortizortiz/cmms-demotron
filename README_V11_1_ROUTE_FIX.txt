DEMOTRON ERP CMMS V11.1 ROUTE FIX

Problema:
- V11 estaba instalada, pero /erp seguía mostrando un dashboard anterior.

Solución:
- Se neutralizan redirecciones antiguas.
- /erp redirige a /erp_v11_final.
- /equipos redirige a /equipos_v11_final.

Probar:
- /admin/v111/version
- /admin/v111/diagnostico
- /erp
- /erp_v11_final
- /equipos
- /equipos_v11_final
