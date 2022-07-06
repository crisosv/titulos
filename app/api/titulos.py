from flask import jsonify, request, url_for, abort
from app import db
from app.models import Titulo
from app.api import bp
from app.api.auth import token_auth
from app.api.errors import bad_request


@bp.route('/titulos/<int:id>', methods=['GET'])
@token_auth.login_required
def get_titulo(id):
    return jsonify(Titulo.query.get_or_404(id).to_dict())


@bp.route('/titulos', methods=['GET'])
@token_auth.login_required
def get_titulos():
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 10, type=int), 100)
    data = Titulo.to_collection_dict(Titulo.query, page, per_page, 'api.get_titulos')
    return jsonify(data)


'''
@bp.route('/titulos/<int:id>/followers', methods=['GET'])
@token_auth.login_required
def get_followers(id):
    titulo = Titulo.query.get_or_404(id)
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 10, type=int), 100)
    data = Titulo.to_collection_dict(Titulo.followers, page, per_page, 'api.get_followers', id=id)
    return jsonify(data)

@bp.route('/titulos/<int:id>/followed', methods=['GET'])
@token_auth.login_required
def get_followed(id):
    titulo = Titulo.query.get_or_404(id)
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 10, type=int), 100)
    data = Titulo.to_collection_dict(Titulo.followed, page, per_page, 'api.get_followed', id=id)
    return jsonify(data)
'''

@bp.route('/titulos', methods=['POST'])
def create_titulo():
    data = request.get_json() or {}
    if 'titulo' not in data or 'orientacion' not in data or 'carrera' not in data or 'resolucion' not in data or 'modalidad' not in data:
        return bad_request('must include titulo, orientacion, carrera, resolucion and modalidad fields')
    if Titulo.query.filter_by(titulo=data['titulo']).first():
        return bad_request('please use a different titulo')
    if Titulo.query.filter_by(orientacion=data['orientacion']).first():
        return bad_request('please use a different orientacion address')
    titulo = titulo()
    Titulo.from_dict(data, new_titulo=True)
    db.session.add(titulo)
    db.session.commit()
    response = jsonify(Titulo.to_dict())
    response.status_code = 201
    response.headers['Location'] = url_for('api.get_titulo', id=titulo.id)
    return response


# revisar 
@bp.route('/titulos/<int:id>', methods=['PUT'])
@token_auth.login_required
def update_titulo(id):
    if token_auth.current_user().id != id:
        abort(403)
    titulo = Titulo.query.get_or_404(id)
    data = request.get_json() or {}
    if 'titulo' in data and data['titulo'] != Titulo.titulo and \
            Titulo.query.filter_by(titulo=data['titulo']).first():
        return bad_request('please use a different titulo')
    if 'orientacion' in data and data['orientacion'] != Titulo.orientacion and \
            Titulo.query.filter_by(orientacion=data['orientacion']).first():
        return bad_request('please use a different orientacion address')
    Titulo.from_dict(data, new_titulo=False)
    db.session.commit()
    return jsonify(Titulo.to_dict())
