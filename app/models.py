import base64
from datetime import datetime, timedelta
from hashlib import md5
import json
import os
from time import time
from flask import current_app, url_for
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import jwt
import redis
import rq
from app import db, login
from app.search import add_to_index, remove_from_index, query_index


class SearchableMixin(object):
    @classmethod
    def search(cls, expression, page, per_page):
        ids, total = query_index(cls.__tablename__, expression, page, per_page)
        if total == 0:
            return cls.query.filter_by(id=0), 0
        when = []
        for i in range(len(ids)):
            when.append((ids[i], i))
        return cls.query.filter(cls.id.in_(ids)).order_by(
            db.case(when, value=cls.id)), total

    @classmethod
    def before_commit(cls, session):
        session._changes = {
            'add': list(session.new),
            'update': list(session.dirty),
            'delete': list(session.deleted)
        }

    @classmethod
    def after_commit(cls, session):
        for obj in session._changes['add']:
            if isinstance(obj, SearchableMixin):
                add_to_index(obj.__tablename__, obj)
        for obj in session._changes['update']:
            if isinstance(obj, SearchableMixin):
                add_to_index(obj.__tablename__, obj)
        for obj in session._changes['delete']:
            if isinstance(obj, SearchableMixin):
                remove_from_index(obj.__tablename__, obj)
        session._changes = None

    @classmethod
    def reindex(cls):
        for obj in cls.query:
            add_to_index(cls.__tablename__, obj)


db.event.listen(db.session, 'before_commit', SearchableMixin.before_commit)
db.event.listen(db.session, 'after_commit', SearchableMixin.after_commit)


class PaginatedAPIMixin(object):
    @staticmethod
    def to_collection_dict(query, page, per_page, endpoint, **kwargs):
        resources = query.paginate(page, per_page, False)
        # resources = query.paginate(page, per_page, False)
        data = {
            'items': [item.to_dict() for item in resources.items],
            '_meta': {
                'page': page,
                'per_page': per_page,
                'total_pages': resources.pages,
                'total_items': resources.total
            },
            '_links': {
                'self': url_for(endpoint, page=page, per_page=per_page,
                                **kwargs),
                'next': url_for(endpoint, page=page + 1, per_page=per_page,
                                **kwargs) if resources.has_next else None,
                'prev': url_for(endpoint, page=page - 1, per_page=per_page,
                                **kwargs) if resources.has_prev else None
            }
        }
        return data


followers = db.Table('followers',
    db.Column('follower_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('followed_id', db.Integer, db.ForeignKey('user.id'))
)



class Permission:
    DIRECTIVO = 0
    FOLLOW = 1
    COMMENT = 2
    WRITE = 4
    MODERATE = 8
    ADMIN = 16


# relacion muchos a muchos titulos y user
titulosuser = db.Table(
    'titulo_user',
    # 'tituloes',
    db.Column('titulo_id', db.Integer, db.ForeignKey('titulo.id')),
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'))
)



class Role(db.Model):
    # __tablename__ = 'roles'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True)
    default = db.Column(db.Boolean, default=False, index=True)
    permissions = db.Column(db.Integer)
    # relacion uno a muchos con user
    users = db.relationship('User', backref='role', lazy='dynamic')

    def __init__(self, **kwargs):
        super(Role, self).__init__(**kwargs)
        if self.permissions is None:
            self.permissions = 0

    @staticmethod
    def insert_roles():
        roles = {
            'User': [Permission.FOLLOW, Permission.COMMENT, Permission.WRITE],
            'Moderator': [Permission.FOLLOW, Permission.COMMENT,
                          Permission.WRITE, Permission.MODERATE],
            'Administrator': [Permission.FOLLOW, Permission.COMMENT,
                              Permission.WRITE, Permission.MODERATE,
                              Permission.ADMIN],
            'Directivo' : [Permission.DIRECTIVO]
        }
        default_role = 'User'
        for r in roles:
            role = Role.query.filter_by(name=r).first()
            if role is None:
                role = Role(name=r)
            role.reset_permissions()
            for perm in roles[r]:
                role.add_permission(perm)
            role.default = (role.name == default_role)
            db.session.add(role)
        db.session.commit()

    def add_permission(self, perm):
        if not self.has_permission(perm):
            self.permissions += perm

    def remove_permission(self, perm):
        if self.has_permission(perm):
            self.permissions -= perm

    def reset_permissions(self):
        self.permissions = 0

    def has_permission(self, perm):
        return self.permissions & perm == perm

    def __repr__(self):
        return '<Role %r>' % self.name



class User(UserMixin, PaginatedAPIMixin, db.Model):    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), index=True, unique=True)
    email = db.Column(db.String(120), index=True, unique=True)
    password_hash = db.Column(db.String(128))
    posts = db.relationship('Post', backref='author', lazy='dynamic')
    about_me = db.Column(db.String(140))
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    token = db.Column(db.String(32), index=True, unique=True)
    token_expiration = db.Column(db.DateTime)
    #relacion uno a muchos con roles
    role_id = db.Column(db.Integer, db.ForeignKey('role.id'))
    followed = db.relationship(
        'User', secondary=followers,
        primaryjoin=(followers.c.follower_id == id),
        secondaryjoin=(followers.c.followed_id == id),
        backref=db.backref('followers', lazy='dynamic'), lazy='dynamic')
    messages_sent = db.relationship('Message',
                                    foreign_keys='Message.sender_id',
                                    backref='author', lazy='dynamic')
    messages_received = db.relationship('Message',
                                        foreign_keys='Message.recipient_id',
                                        backref='recipient', lazy='dynamic')
    last_message_read_time = db.Column(db.DateTime)
    notifications = db.relationship('Notification', backref='user',
                                    lazy='dynamic')
    tasks = db.relationship('Task', backref='user', lazy='dynamic')


    def __repr__(self):
        return '<User {}>'.format(self.username)


    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def avatar(self, size):
        digest = md5(self.email.lower().encode('utf-8')).hexdigest()
        return 'https://www.gravatar.com/avatar/{}?d=identicon&s={}'.format(
            digest, size)
        

    def follow(self, user):
        if not self.is_following(user):
            self.followed.append(user)

    def unfollow(self, user):
        if self.is_following(user):
            self.followed.remove(user)

    def is_following(self, user):
        return self.followed.filter(
            followers.c.followed_id == user.id).count() > 0

    def followed_posts(self):
        followed = Post.query.join(
            followers, (followers.c.followed_id == Post.user_id)).filter(
                followers.c.follower_id == self.id)
        own = Post.query.filter_by(user_id=self.id)
        return followed.union(own).order_by(Post.timestamp.desc())

    def get_reset_password_token(self, expires_in=600):
        return jwt.encode(
            {'reset_password': self.id, 'exp': time() + expires_in},
            current_app.config['SECRET_KEY'], algorithm='HS256')

    @staticmethod
    def verify_reset_password_token(token):
        try:
            id = jwt.decode(token, current_app.config['SECRET_KEY'],
                            algorithms=['HS256'])['reset_password']
        except:
            return
        return User.query.get(id)

    def new_messages(self):
        last_read_time = self.last_message_read_time or datetime(1900, 1, 1)
        return Message.query.filter_by(recipient=self).filter(
            Message.timestamp > last_read_time).count()

    def add_notification(self, name, data):
        self.notifications.filter_by(name=name).delete()
        n = Notification(name=name, payload_json=json.dumps(data), user=self)
        db.session.add(n)
        return n

    def launch_task(self, name, description, *args, **kwargs):
        rq_job = current_app.task_queue.enqueue('app.tasks.' + name, self.id,
                                                *args, **kwargs)
        task = Task(id=rq_job.get_id(), name=name, description=description,
                    user=self)
        db.session.add(task)
        return task

    def get_tasks_in_progress(self):
        return Task.query.filter_by(user=self, complete=False).all()

    def get_task_in_progress(self, name):
        return Task.query.filter_by(name=name, user=self, complete=False).first()
    

    def to_dict(self, include_email=False):
        data = {
            'id': self.id,
            'username': self.username,
            'last_seen': self.last_seen.isoformat() + 'Z',
            'about_me': self.about_me,
            'post_count': self.posts.count(),
            'follower_count': self.followers.count(),
            'followed_count': self.followed.count(),
            '_links': {
                'self': url_for('api.get_user', id=self.id),
                'followers': url_for('api.get_followers', id=self.id),
                'followed': url_for('api.get_followed', id=self.id),
                'avatar': self.avatar(128)
            }
        }
        if include_email:
            data['email'] = self.email
        return data

    
    def from_dict(self, data, new_user=False):
        for field in ['username', 'email', 'about_me']:
            if field in data:
                setattr(self, field, data[field])
        if new_user and 'password' in data:
            self.set_password(data['password'])

    
    def get_token(self, expires_in=3600):
        now = datetime.utcnow()
        if self.token and self.token_expiration > now + timedelta(seconds=60):
            return self.token
        self.token = base64.b64encode(os.urandom(24)).decode('utf-8')
        self.token_expiration = now + timedelta(seconds=expires_in)
        db.session.add(self)
        return self.token

    
    def revoke_token(self):
        self.token_expiration = datetime.utcnow() - timedelta(seconds=1)

    
    @staticmethod
    def check_token(token):
        user = User.query.filter_by(token=token).first()
        if user is None or user.token_expiration < datetime.utcnow():
            return None
        return user


@login.user_loader
def load_user(id):
    return User.query.get(int(id))



class Institucion(PaginatedAPIMixin, db.Model):
    # __tablename__ = 'instituciones'
    id = db.Column(db.Integer(), primary_key=True)
    nombre = db.Column(db.String(255), nullable=False)
    cueanexo = db.Column(db.Integer(), nullable=False)
    domicilio = db.Column(db.String(255), nullable=True)
    localidad = db.Column(db.String(255), nullable=False)
    departamento = db.Column(db.String(255), nullable=False)
    region = db.Column(db.String(255), nullable=False)
    ambito = db.Column(db.String(255), nullable=True)
    # vacantes = db.Column(db.Integer(), nullable=False)
    # momento = db.Column(db.DateTime())
    # vacantes_2 = db.Column(db.Integer(), nullable=True)
    # momento_2 = db.Column(db.Integer(), nullable=True)
    # text = db.Column(db.Text(), nullable=False)
    # publish_date = db.Column(db.DateTime(), default=datetime.datetime.now)
    # user_id = db.Column(db.Integer(), db.ForeignKey('user.id'))
    
    #relacion uno a muchos con tituloes
    # posts = db.relationship('Post', backref='author', lazy='dynamic')
    tituloinstitucion = db.relationship('Titulo', backref='institucion', lazy='dynamic')
    
    # relacion muchos a muchos con users
    # artists = db.relationship('Artist', backref='albums', lazy='dynamic', secondary=albums_to_artists_table)
    # usuarios = db.relationship('User', backref='escuelas', lazy='dynamic', secondary=escuelasuser)
    
    # relacion muchos a muchos con user
    # To silence this warning, add the parameter 'overlaps="escuelas,escuelasuser_backref"' to the 'Institucion.users' relationship.
    # users = db.relationship('User', secondary=escuelasuser, backref=db.backref('institucion', lazy='dynamic'))
    # no debe ir ?
    # users = db.relationship('User', secondary=escuelasuser, backref=db.backref('institution', lazy='dynamic'))
    # users = db.relationship('User', secondary=escuelasuser, backref=db.backref('escuelas', lazy='dynamic'))
    
    
    def __init__(self, nombre=""):
        self.nombre = nombre
        
    
    def to_dict(self, include_email=False):
        data = {
            'id': self.id,
            'nombre': self.nombre,
            'cueanexo': self.cueanexo,
            'domicilio': self.domicilio,
            'localidad': self.localidad,
            # 'follower_count': self.followers.count(),
            'departamento': self.departamento,
            'region':self.region,
            'ambito':self.ambito
        }
        return data

    
    def from_dict(self, data, new_user=False):
        for field in ['nombre', 'cueanexo']:
            if field in data:
                setattr(self, field, data[field])
        if new_user and 'password' in data:
            self.set_password(data['password'])

        
    def search( self, word ):
        if (word is None):
            return False
        # all = self.fname + self.lname + self.email
        all = self.nombre
        return word.lower() in all.lower()


    def __repr__(self):
        return "<Institucion '{}'>".format(self.nombre)



class Titulo(PaginatedAPIMixin, db.Model):
    # __tablename__ = 'Titulos'
    id = db.Column(db.Integer(), primary_key=True)
    titulo = db.Column(db.String(255), nullable=False)
    # cueanexo = db.Column(db.Integer(), nullable=False)
    orientacion = db.Column(db.String(255), nullable=True)
    carrera = db.Column(db.String(255), nullable=True)
    resolucion = db.Column(db.String(255), nullable=True)
    modalidad = db.Column(db.String(255), nullable=False)
    institucion_id = db.Column(db.Integer(), db.ForeignKey('institucion.id'))
    # role_id = db.Column(db.Integer(), db.ForeignKey('Role.id'))
    # momento = db.Column(db.DateTime())
    # vacantes_2 = db.Column(db.Integer(), nullable=True)
    # momento_2 = db.Column(db.Integer(), nullable=True)
    # text = db.Column(db.Text(), nullable=False)
    # publish_date = db.Column(db.DateTime(), default=datetime.datetime.now)
    # user_id = db.Column(db.Integer(), db.ForeignKey('user.id'))
    
    #relacion uno a muchos con instituciones
    # posts = db.relationship('Post', backref='author', lazy='dynamic')
    # instituciontitulo = db.relationship('Institucion', backref='titulo', lazy='dynamic') 
    
    # relacion muchos a muchos con users
    # artists = db.relationship('Artist', backref='albums', lazy='dynamic', secondary=albums_to_artists_table)
    # usuarios = db.relationship('User', backref='escuelas', lazy='dynamic', secondary=escuelasuser)
    
    # relacion muchos a muchos con user
    # To silence this warning, add the parameter 'overlaps="escuelas,escuelasuser_backref"' to the 'Titulo.users' relationship.
    # users = db.relationship('User', secondary=escuelasuser, backref=db.backref('Titulo', lazy='dynamic'))
    # no debe ir ?
    # users = db.relationship('User', secondary=escuelasuser, backref=db.backref('institution', lazy='dynamic'))
    # users = db.relationship('User', secondary=escuelasuser, backref=db.backref('escuelas', lazy='dynamic'))
    
    
    def __init__(self, titulo=""):
        self.titulo = titulo
    
    
    def to_dict(self, include_email=False):
        data = {
            'id': self.id,
            'titulo': self.titulo,
            'orientacion': self.orientacion,
            'carrera': self.carrera,
            'resolucion': self.resolucion,
            # 'follower_count': self.followers.count(),
            'modalidad': self.modalidad,
            'institucion_id':self.institucion_id
        }
        '''
        if include_email:
            data['email'] = self.email
        '''
        return data

    
    def from_dict(self, data, new_user=False):
        for field in ['titulo', 'email', 'orientacion']:
            if field in data:
                setattr(self, field, data[field])
        if new_user and 'password' in data:
            self.set_password(data['password'])

    
    def search( self, word ):
        if (word is None):
            return False
        # all = self.fname + self.lname + self.email
        all = self.titulo
        return word.lower() in all.lower()


    def __repr__(self):
        return "<Titulo '{}'>".format(self.titulo)



class Post(SearchableMixin, db.Model):
    __searchable__ = ['body']
    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.String(140))
    timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    language = db.Column(db.String(5))

    def __repr__(self):
        return '<Post {}>'.format(self.body)


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    body = db.Column(db.String(140))
    timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow)

    def __repr__(self):
        return '<Message {}>'.format(self.body)


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    timestamp = db.Column(db.Float, index=True, default=time)
    payload_json = db.Column(db.Text)

    def get_data(self):
        return json.loads(str(self.payload_json))


class Task(db.Model):
    id = db.Column(db.String(36), primary_key=True)
    name = db.Column(db.String(128), index=True)
    description = db.Column(db.String(128))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    complete = db.Column(db.Boolean, default=False)

    def get_rq_job(self):
        try:
            rq_job = rq.job.Job.fetch(self.id, connection=current_app.redis)
        except (redis.exceptions.RedisError, rq.exceptions.NoSuchJobError):
            return None
        return rq_job

    def get_progress(self):
        job = self.get_rq_job()
        return job.meta.get('progress', 0) if job is not None else 100
