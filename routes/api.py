import pandas as pd
from flask import request

# =========================================================
# CARGA MASIVA DEL EXCEL "MAESTRO DE FILTROS"
# =========================================================
@api_bp.route('/cargar_maestro_filtros', methods=['GET', 'POST'])
def cargar_maestro_filtros():
    # Protegemos la ruta con un token por seguridad (puedes pasarlo por la URL)
    token = request.args.get('token')
    if token != 'DemotronFiltros2026':
        return "Acceso denegado. Token inválido.", 403

    if request.method == 'GET':
        # Un pequeño formulario rápido para subir el Excel
        return '''
        <h2>Subir Maestro de Filtros (Excel)</h2>
        <form method="POST" enctype="multipart/form-data">
            <input type="file" name="file" accept=".xlsx, .xls">
            <button type="submit">Subir e Importar</button>
        </form>
        '''
    
    file = request.files.get('file')
    if not file:
        return "No se subió ningún archivo", 400
        
    try:
        from models.equipo import FiltroEquipo
        
        # Leemos el Excel
        df = pd.read_excel(file)
        
        # Limpiamos la tabla antigua de filtros para que no se dupliquen
        db.session.query(FiltroEquipo).delete()
        
        registros_agregados = 0
        
        for index, row in df.iterrows():
            codigo_eq = str(row.get('Equipo') or row.get('codigo_equipo') or '').strip()
            
            if not codigo_eq or codigo_eq == 'nan':
                continue
                
            # Mapeo Inteligente: Busca el nombre antiguo del Excel y lo guarda en el nuevo formato
            nuevo_filtro = FiltroEquipo(
                codigo_equipo=codigo_eq,
                sistema=str(row.get('Filtro') or row.get('Sistema') or '-'),
                cant=str(row.get('Cantidad') or row.get('Cant') or '1'),
                originales=str(row.get('Codigo') or row.get('Originales') or '-'),
                fleetguard='-',
                donaldson='-',
                baldwind='-'
            )
            
            db.session.add(nuevo_filtro)
            registros_agregados += 1
            
        db.session.commit()
        return f"¡Éxito! Se importaron {registros_agregados} filtros correctamente a la base de datos corporativa."
        
    except Exception as e:
        db.session.rollback()
        return f"Error al procesar el Excel: {str(e)}"
