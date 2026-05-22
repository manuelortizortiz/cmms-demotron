vin_texto = equipo.vin if equipo.vin and str(equipo.vin).lower() not in ["none", "nan", ""] else "S/I"
    motor_texto = equipo.n_motor if equipo.n_motor and str(equipo.n_motor).lower() not in ["none", "nan", ""] else "S/I"
    patente_texto = equipo.patente if equipo.patente and str(equipo.patente).lower() not in ["none", "nan", ""] else "S/P"
    
    desc_tecnica = f"Unidad {equipo.tipo_equipo} marca {equipo.marca} {equipo.modelo}. Identificación de chasis (VIN): {vin_texto}. Número de Motor: {motor_texto}. Placa Patente: {patente_texto}."
    
    mants_db = OrdenTrabajo.query.filter_by(codigo_equipo=codigo).order_by(OrdenTrabajo.id.desc()).all()
    compras_db = CompraRepuesto.query.filter_by(codigo_equipo=codigo).order_by(CompraRepuesto.fecha.desc()).all()
    lecturas_db = HistorialLectura.query.filter_by(codigo_equipo=codigo).order_by(HistorialLectura.fecha.desc()).limit(5).all()

    mants = [{'fecha': m.fecha.strftime('%d/%m/%Y') if m.fecha else 'S/F', 'tipo': m.tipo_mantencion, 'costo_str': format_clp(m.costo_mantencion_clp), 'estado': m.estado, 'folio': m.folio} for m in mants_db]
    compras = [{'fecha': c.fecha.strftime('%d/%m/%Y'), 'oc': c.oc, 'descripcion': c.descripcion, 'costo_str': format_clp(c.costo_pm_clp), 'proveedor': c.proveedor} for c in compras_db]
    lecturas = [{'fecha': l.fecha.strftime('%d/%m/%Y %H:%M'), 'valor': format_num(l.horometro if l.horometro > 0 else l.kilometraje), 'tipo': 'HR' if l.horometro > 0 else 'KM', 'obs': l.observacion} for l in lecturas_db]

    return render_template('ficha_equipo.html', eq=equipo, desc_tecnica=desc_tecnica, foto_url=buscar_foto_por_tipo(equipo.tipo_equipo, equipo.marca), mants=mants, compras=compras, lecturas=lecturas)

@app.route('/imprimir_ot/<codigo>', strict_slashes=False)
def imprimir_ot(codigo):
    equipo = Equipo.query.filter_by(codigo=codigo).first_or_404()
    ot = OrdenTrabajo.query.filter_by(codigo_equipo=codigo).order_by(OrdenTrabajo.id.desc()).first()
    ot_data = {'folio': ot.folio if (ot and ot.folio and str(ot.folio).lower() != 'none') else f"OT-DMT-0{random.randint(2000, 9000)}", 'tipo_mantencion': ot.tipo_mantencion if ot else "MANTENIMIENTO PREVENTIVO"}
    return render_template('ot_print.html', equipo=equipo, ot=ot_data, fecha_actual=datetime.now().strftime("%d/%m/%Y"))

@app.route('/admin/cargar_sql_final', strict_slashes=False)
def cargar_sql_final():
    archivo_excel = "CMMS DEMOTRON MANU ORTIZ.xlsx"
    if not os.path.exists(archivo_excel): return "Error: Falta Excel principal."
    
    try:
        with db.engine.connect() as conn:
            conn.execute(db.text("DROP TABLE IF EXISTS compra_repuesto"))
            conn.execute(db.text("DROP TABLE IF EXISTS orden_trabajo"))
            conn.execute(db.text("DROP TABLE IF EXISTS historial_lectura"))
            conn.execute(db.text("DROP TABLE IF EXISTS equipo"))
            conn.commit()
            
        db.create_all()

        df_eq = pd.read_excel(archivo_excel, sheet_name="Equipos", skiprows=2).replace({np.nan: None})
        operadores_excel = df_eq.iloc[:, 6].dropna().unique()
        for op in operadores_excel:
            op_str = str(op).strip()
            if op_str and str(op_str).lower() != 'none':
                if not Personal.query.filter_by(nombre=op_str).first():
                    nuevo_op = Personal(tipo="Conductor", nombre=op_str, cargo="Operador de Maquinaria", estado="Activo")
                    db.session.add(nuevo_op)

        for _, row in df_eq.iterrows():
            if not row.iloc[0]: continue
            eq = Equipo(codigo=str(row.iloc[0]).strip(), tipo_equipo=row.iloc[1], marca=row.iloc[2], modelo=str(row.iloc[3]).strip() if row.iloc[3] else None, ano=clean_int(row.iloc[4], None), ubicacion=row.iloc[5], responsable=row.iloc[6], estado_base=str(row.iloc[7]).strip() if row.iloc[7] else 'Operativo', control_base=str(row.iloc[8]).strip().upper() if row.iloc[8] else 'HORAS', frecuencia_base=clean_int(row.iloc[9], 250))
            db.session.add(eq)
        db.session.commit()

        archivo_detalles = "detalles de equipo.xlsx - Hoja1.csv"
        if os.path.exists(archivo_detalles):
            df_det = pd.read_csv(archivo_detalles)
            df_det.columns = [str(c).strip() for c in df_det.columns]
            for _, row in df_det.iterrows():
                cod = str(row.get('Código', row.get('Codigo', ''))).strip()
                eq = Equipo.query.filter_by(codigo=cod).first()
                if eq:
                    eq.patente = clean_string(row.get('Placa', ''))
                    eq.vin = clean_string(row.get('N° Chasis', ''))
                    eq.n_motor = clean_string(row.get('N° Motor', ''))
            db.session.commit()

        df_lec = pd.read_excel(archivo_excel, sheet_name="Lecturas", skiprows=2).replace({np.nan: None})
        for _, row in df_lec.iterrows():
            if not row.iloc[1]: continue
            f_val = str(row.iloc[0]).split()[0]
            try: fecha_dt = datetime.strptime(f_val, "%Y-%m-%d")
            except: fecha_dt = datetime.now()
            lec = HistorialLectura(fecha=fecha_dt, codigo_equipo=str(row.iloc[1]).strip(), horometro=clean_int(row.iloc[2], 0), kilometraje=clean_int(row.iloc[3], 0), obra_ubicacion=row.iloc[4], responsable=row.iloc[5], observacion=row.iloc[6])
            db.session.add(lec)

        df_man = pd.read_excel(archivo_excel, sheet_name="Mantenciones", skiprows=2).replace({np.nan: None})
        for _, row in df_man.iterrows():
            if not row.iloc[1]: continue
            f_val = str(row.iloc[0]).split()[0]
            try: fecha_dt = datetime.strptime(f_val, "%Y-%m-%d")
            except: fecha_dt = datetime.now()
            ot = OrdenTrabajo(fecha=fecha_dt, codigo_equipo=str(row.iloc[1]).strip(), tipo_mantencion=str(row.iloc[2]).strip(), lectura=clean_int(row.iloc[3], 0), es_pm=row.iloc[4], folio=str(row.iloc[5]), lugar=row.iloc[6], costo_mantencion_clp=clean_float(row.iloc[8], 0.0), estado=row.iloc[9] if row.iloc[9] else 'Finalizada')
            db.session.add(ot)

        df_com = pd.read_excel(archivo_excel, sheet_name="Compras PM", skiprows=2).replace({np.nan: None})
        for _, row in df_com.iterrows():
            if not row.iloc[2]: continue
            f_val = str(row.iloc[0]).split()[0]
            try: fecha_dt = datetime.strptime(f_val, "%Y-%m-%d")
            except: fecha_dt = datetime.now()
            comp = CompraRepuesto(fecha=fecha_dt, oc=str(row.iloc[1]), codigo_equipo=str(row.iloc[2]).strip(), descripcion=row.iloc[3], proveedor=row.iloc[4], costo_pm_clp=clean_float(row.iloc[5], 0.0), estado_oc=row.iloc[7])
            db.session.add(comp)
        
        db.session.commit()

        for eq in Equipo.query.all():
            u_lec = HistorialLectura.query.filter_by(codigo_equipo=eq.codigo).order_by(HistorialLectura.fecha.desc(), HistorialLectura.id.desc()).first()
            if u_lec: eq.lectura_actual = u_lec.horometro if eq.control_base == 'HORAS' else u_lec.kilometraje
            else: eq.lectura_actual = 0
            u_pm = OrdenTrabajo.query.filter_by(codigo_equipo=eq.codigo, es_pm='Sí', estado='Finalizada').order_by(OrdenTrabajo.fecha.desc()).first()
            if u_pm: eq.proxima_pm = u_pm.lectura + eq.frecuencia_base
            else: eq.proxima_pm = eq.lectura_actual + eq.frecuencia_base
        db.session.commit()

        return redirect(url_for('dashboard'))

    except Exception as e: return f"<h1 style='color:red;'>Error técnico al inyectar:</h1><p>{str(e)}</p>"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
