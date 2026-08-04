@dashboard_bp.route('/api/imprimir_registro/<codigo>', strict_slashes=False)
@login_required
def imprimir_registro(codigo):
    try:
        equipo = Equipo.query.filter_by(codigo=codigo).first()
        if not equipo:
            return "Error: Equipo no encontrado en el sistema.", 404

        # 1. Traer Mantenciones
        mants_prev = OrdenTrabajo.query.filter_by(codigo_equipo=codigo, tipo_ot='Preventiva').order_by(OrdenTrabajo.fecha.desc()).all()
        mants_corr = OrdenTrabajo.query.filter_by(codigo_equipo=codigo, tipo_ot='Correctiva').order_by(OrdenTrabajo.fecha.desc()).all()
        
        # 2. Traer Compras asociadas a este equipo
        compras = CompraRepuesto.query.filter_by(codigo_equipo=codigo).order_by(CompraRepuesto.fecha.desc()).all()
        
        # 3. Calcular Gastos Totales
        gasto_mants = sum(float(o.costo_mantencion_clp or 0) for o in mants_prev + mants_corr)
        gasto_compras = sum(float(c.costo_pm_clp or 0) for c in compras)
        gasto_total = gasto_mants + gasto_compras

        from utils.formatters import format_clp
        gasto_mants_str = format_clp(gasto_mants)
        gasto_compras_str = format_clp(gasto_compras)
        gasto_total_str = format_clp(gasto_total)

        # 4. Inteligencia Predictiva: Buscar averías en unidades "Gemelas"
        equipos_similares = Equipo.query.filter(
            Equipo.tipo_equipo == equipo.tipo_equipo,
            Equipo.marca == equipo.marca,
            Equipo.codigo != equipo.codigo # Excluimos el equipo actual
        ).all()
        
        codigos_similares = [e.codigo for e in equipos_similares]
        averias_similares = []
        if codigos_similares:
            averias_similares = OrdenTrabajo.query.filter(
                OrdenTrabajo.codigo_equipo.in_(codigos_similares),
                OrdenTrabajo.tipo_ot == 'Correctiva'
            ).order_by(OrdenTrabajo.fecha.desc()).limit(15).all()

        return render_template('imprimir_registro.html', 
                               equipo=equipo, 
                               mants_prev=mants_prev, 
                               mants_corr=mants_corr, 
                               compras=compras, 
                               gasto_mants_str=gasto_mants_str,
                               gasto_compras_str=gasto_compras_str,
                               gasto_total_str=gasto_total_str,
                               averias_similares=averias_similares,
                               hoy=datetime.now())
    except Exception as e:
        return f"Error al generar el historial clínico: {str(e)}"
