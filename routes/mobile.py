from flask import Blueprint, render_template, request, redirect
from datetime import datetime
import os
from werkzeug.utils import secure_filename
from extensions import db
from models.equipo import Equipo
from models.checklist import ChecklistPreUso

mobile_bp = Blueprint('mobile', __name__, url_prefix='/mobile')

@mobile_bp.route('/checklist', methods=['GET', 'POST'])
def checklist():
    if request.method == 'POST':
        codigo = request.form.get('codigo_equipo')
        
        # Subida de foto tomada con el celular
        foto_url = None
        if 'foto' in request.files:
            file = request.files['foto']
            if file.filename != '':
                filename = secure_filename(f"CHK_{codigo}_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg")
                upload_folder = os.path.join('static', 'uploads', 'checklists')
                os.makedirs(upload_folder, exist_ok=True)
                file.save(os.path.join(upload_folder, filename))
                foto_url = f"/static/uploads/checklists/{filename}"

        check = ChecklistPreUso(
            codigo_equipo=codigo,
            operador=request.form.get('operador'),
            niveles_ok=request.form.get('niveles') == 'si',
            fugas_ok=request.form.get('fugas') == 'si',
            frenos_ok=request.form.get('frenos') == 'si',
            neumaticos_ok=request.form.get('neumaticos') == 'si',
            observaciones=request.form.get('observaciones'),
            foto_evidencia_url=foto_url,
            estado_equipo=request.form.get('estado_final')
        )
        db.session.add(check)
        
        # Si reportan el equipo detenido, actualizamos la matriz principal
        if request.form.get('estado_final') == 'Detenido':
            eq = Equipo.query.filter_by(codigo=codigo).first()
            if eq: eq.estado_base = 'Taller'
            
        db.session.commit()
        return redirect('/mobile/success')

    equipos = Equipo.query.filter(Equipo.estado_base != 'Fuera de Servicio').order_by(Equipo.codigo).all()
    return render_template('mobile_checklist.html', equipos=equipos)

@mobile_bp.route('/success')
def success():
    html = """<!DOCTYPE html><html lang="es"><head><meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no"><script src="https://cdn.tailwindcss.com"></script></head>
    <body class="bg-slate-900 h-screen flex flex-col items-center justify-center p-6 text-center">
        <div class="text-7xl mb-6">✅</div>
        <h1 class="text-3xl font-black text-white mb-2 tracking-tighter uppercase">Enviado</h1>
        <p class="text-slate-400 font-bold mb-10 text-sm uppercase tracking-widest">Registrado en la base de datos</p>
        <a href="/mobile/checklist" class="w-full max-w-xs bg-blue-600 text-white font-black py-4 rounded-xl text-lg uppercase tracking-widest shadow-lg">Nuevo Registro</a>
    </body></html>"""
    return html
