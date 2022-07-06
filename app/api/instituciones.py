from flask import jsonify, request, url_for, abort
from app import db
from app.models import Institucion, Titulo
from app.api import bp
from app.api.auth import token_auth
from app.api.errors import bad_request


@bp.route('/instituciones/<int:id>', methods=['GET'])
@token_auth.login_required
def get_institucion(id):
    return jsonify(Institucion.query.get_or_404(id).to_dict())


@bp.route('/instituciones', methods=['GET'])
@token_auth.login_required
def get_instituciones():
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 10, type=int), 100)
    # data = Institucion.to_collection_dict(Institucion.query, page, per_page, 'api.get_instituciones')
    data = Institucion.to_collection_dict(Institucion.query.order_by(Institucion.nombre), page, per_page, 'api.get_instituciones')
    return jsonify(data)


'''
@bp.route('/instituciones/<int:id>/followers', methods=['GET'])
@token_auth.login_required
def get_followers(id):
    titulo = Titulo.query.get_or_404(id)
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 10, type=int), 100)
    data = Titulo.to_collection_dict(Titulo.followers, page, per_page, 'api.get_followers', id=id)
    return jsonify(data)

@bp.route('/instituciones/<int:id>/followed', methods=['GET'])
@token_auth.login_required
def get_followed(id):
    titulo = Titulo.query.get_or_404(id)
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 10, type=int), 100)
    data = Titulo.to_collection_dict(Titulo.followed, page, per_page, 'api.get_followed', id=id)
    return jsonify(data)
'''

@bp.route('/instituciones', methods=['POST'])
def create_institucion():
    data = request.get_json() or {}
    if 'institucion' not in data or 'orientacion' not in data or 'carrera' not in data or 'resolucion' not in data or 'modalidad' not in data:
        return bad_request('must include institucion, orientacion, carrera, resolucion and modalidad fields')
    if Institucion.query.filter_by(institucion=data['institucion']).first():
        return bad_request('please use a different institucion')
    if Institucion.query.filter_by(orientacion=data['orientacion']).first():
        return bad_request('please use a different orientacion address')
    institucion = Institucion()
    Institucion.from_dict(data, new_institucion=True)
    db.session.add(institucion)
    db.session.commit()
    response = jsonify(Institucion.to_dict())
    response.status_code = 201
    response.headers['Location'] = url_for('api.get_institucion', id=Institucion.id)
    return response


# revisar 
@bp.route('/instituciones/<int:id>', methods=['PUT'])
@token_auth.login_required
def update_institucion(id):
    if token_auth.current_user().id != id:
        abort(403)
    institucion = Institucion.query.get_or_404(id)
    data = request.get_json() or {}
    if 'institucion' in data and data['institucion'] != Institucion.institucion and \
            Institucion.query.filter_by(institucion=data['institucion']).first():
        return bad_request('please use a different institucion')
    if 'orientacion' in data and data['orientacion'] != Institucion.orientacion and \
            Institucion.query.filter_by(orientacion=data['orientacion']).first():
        return bad_request('please use a different orientacion address')
    Institucion.from_dict(data, new_Institucion=False)
    db.session.commit()
    return jsonify(institucion.to_dict())
