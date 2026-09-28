import os
import json
import uuid
import requests
import mysql.connector
import threading
from mysql.connector import pooling
from functools import wraps
from datetime import datetime, timezone, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response
from werkzeug.security import generate_password_hash, check_password_hash
from minio import Minio
from minio.error import S3Error

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'default_secret')
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5 MB — limite de tamanho pra qualquer upload

BRASILIA_TZ = timezone(timedelta(hours=-3))

db_pool = pooling.MySQLConnectionPool(
    pool_name="catalogo_pool",
    pool_size=5,
    host=os.getenv('DB_HOST'),
    user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD'),
    database=os.getenv('DB_NAME')
)

def get_db_connection():
    conn = db_pool.get_connection()
    conn.ping(reconnect=True, attempts=3, delay=0.5)
    return conn

# --- MinIO (object storage da foto de perfil) ---
MINIO_BUCKET = os.getenv('MINIO_BUCKET', 'perfis')
EXTENSOES_PERMITIDAS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

minio_client = Minio(
    'minio:9000',  # nome do serviço na rede interna do Docker
    access_key=os.getenv('MINIO_ROOT_USER'),
    secret_key=os.getenv('MINIO_ROOT_PASSWORD'),
    secure=False
)

def garantir_bucket():
    """Cria o bucket se não existir e o mantém PRIVADO: o MinIO não tem porta
    publicada, e as fotos só saem pela rota /foto/<id> do próprio app."""
    if not minio_client.bucket_exists(MINIO_BUCKET):
        minio_client.make_bucket(MINIO_BUCKET)
    try:
        minio_client.delete_bucket_policy(MINIO_BUCKET)
    except S3Error:
        pass

try:
    garantir_bucket()
except Exception as e:
    print(f"Aviso: não foi possível preparar o bucket do MinIO no startup: {e}")

def extensao_valida(nome_arquivo):
    return '.' in nome_arquivo and nome_arquivo.rsplit('.', 1)[1].lower() in EXTENSOES_PERMITIDAS

def registrar_evento(usuario_id, acao, detalhe=''):
    ip = request.remote_addr

    def _enviar():
        try:
            requests.post('http://log_service:5002/eventos', json={
                'usuario_id': usuario_id,
                'acao': acao,
                'detalhe': detalhe,
                'ip': ip
            }, timeout=2)
        except requests.exceptions.RequestException:
            pass

    threading.Thread(target=_enviar, daemon=True).start()

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({"erro": "Não autenticado"}), 401
        if session.get('user_role') != 'admin':
            registrar_evento(session['user_id'], 'acesso_negado', f'tentou acessar {request.path}')
            return jsonify({"erro": "Ação restrita a administradores."}), 403
        return f(*args, **kwargs)
    return decorated

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        nome = request.form['nome']
        email = request.form['email']
        senha = request.form['senha']

        resposta = requests.post('http://auth_api:5001/register', json={
            'nome': nome,
            'email': email,
            'senha': senha
        })

        if resposta.status_code == 201:
            flash('Cadastro realizado! Faça seu login.', 'success')
            return redirect(url_for('login'))
        else:
            erro = resposta.json().get('erro', 'Erro no cadastro')
            flash(erro, 'danger')

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        senha = request.form['senha']

        resposta = requests.post('http://auth_api:5001/login', json={
            'email': email,
            'senha': senha
        })

        if resposta.status_code == 200:
            dados = resposta.json()
            session['user_id'] = dados['usuario']['id']
            session['nome'] = dados['usuario']['nome']
            session['user_role'] = dados['usuario']['role']
            registrar_evento(dados['usuario']['id'], 'login')
            flash('Login realizado com sucesso!', 'success')
            return redirect(url_for('index'))
        else:
            erro = resposta.json().get('erro', 'Erro ao fazer login')
            flash(erro, 'danger')

    return render_template('login.html')

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email']

        resposta = requests.post('http://auth_api:5001/forgot-password', json={'email': email})

        if resposta.status_code == 200:
            flash(resposta.json().get('mensagem'), 'success')
            return redirect(url_for('login'))
        else:
            erro = resposta.json().get('erro', 'Erro ao processar solicitação')
            flash(erro, 'danger')

    return render_template('forgot_password.html')

@app.route('/logout')
def logout():
    if 'user_id' in session:
        registrar_evento(session['user_id'], 'logout')
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    api_key = os.getenv('TMDB_API_KEY')
    url_busca = f"https://api.themoviedb.org/3/search/person?query=Tom+Hanks&api_key={api_key}"
    search_res = requests.get(url_busca).json()

    print("Retorno TMDB:", search_res)

    movies = []
    if 'results' in search_res and len(search_res['results']) > 0:
        person_id = search_res['results'][0]['id']
        movies_res = requests.get(f"https://api.themoviedb.org/3/person/{person_id}/movie_credits?api_key={api_key}").json()
        movies = movies_res.get('cast', [])
    else:
        flash('Erro de API: Filme não encontrado ou chave TMDB inválida. Verifique os logs.')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT tmdb_movie_id FROM favoritos WHERE usuario_id = %s", (session['user_id'],))
    favoritos = {row['tmdb_movie_id'] for row in cursor.fetchall()}

    cursor.execute("""
        SELECT c.id, c.tmdb_movie_id, c.texto, c.usuario_id, u.nome
        FROM comentarios c
        JOIN usuarios u ON u.id = c.usuario_id
    """)
    comentarios = {}
    for row in cursor.fetchall():
        comentarios.setdefault(row['tmdb_movie_id'], []).append(row)

    cursor.close()
    conn.close()

    return render_template('index.html', movies=movies, favoritos=favoritos, comentarios=comentarios)

@app.route('/favoritar', methods=['POST'])
def favoritar():
    if 'user_id' not in session: return redirect(url_for('login'))
    movie_id = request.form['movie_id']
    titulo = request.form['titulo']
    poster_path = request.form['poster_path']

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO favoritos (usuario_id, tmdb_movie_id, titulo, poster_path) VALUES (%s, %s, %s, %s)",
                       (session['user_id'], movie_id, titulo, poster_path))
        conn.commit()
        registrar_evento(session['user_id'], 'favoritar', titulo)
    except mysql.connector.IntegrityError:
        pass
    finally:
        cursor.close()
        conn.close()
    return redirect(url_for('index'))

@app.route('/desfavoritar', methods=['POST'])
def desfavoritar():
    if 'user_id' not in session: return redirect(url_for('login'))
    movie_id = request.form['movie_id']

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM favoritos WHERE usuario_id = %s AND tmdb_movie_id = %s",
                   (session['user_id'], movie_id))
    conn.commit()
    cursor.close()
    conn.close()
    registrar_evento(session['user_id'], 'desfavoritar', movie_id)
    return redirect(url_for('index'))

@app.route('/comentar', methods=['POST'])
def comentar():
    if 'user_id' not in session: return redirect(url_for('login'))
    movie_id = request.form['movie_id']
    texto = request.form['texto']

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO comentarios (usuario_id, tmdb_movie_id, texto) VALUES (%s, %s, %s)",
                   (session['user_id'], movie_id, texto))
    conn.commit()
    cursor.close()
    conn.close()
    registrar_evento(session['user_id'], 'comentar', texto[:100])
    return redirect(url_for('index'))

@app.route('/deletar-comentario/<int:comentario_id>', methods=['POST'])
def deletar_comentario(comentario_id):
    if 'user_id' not in session:
        return jsonify({"erro": "Não autenticado"}), 401

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT usuario_id FROM comentarios WHERE id = %s", (comentario_id,))
    comentario = cursor.fetchone()

    if not comentario:
        cursor.close()
        conn.close()
        return jsonify({"erro": "Comentário não encontrado"}), 404

    eh_dono = comentario['usuario_id'] == session['user_id']
    eh_admin = session.get('user_role') == 'admin'

    if not eh_dono and not eh_admin:
        cursor.close()
        conn.close()
        registrar_evento(session['user_id'], 'acesso_negado', f'tentou apagar comentário {comentario_id} de outro usuário')
        return jsonify({"erro": "Ação restrita: apenas o autor do comentário ou um admin podem apagá-lo."}), 403

    cursor.execute("DELETE FROM comentarios WHERE id = %s", (comentario_id,))
    conn.commit()
    cursor.close()
    conn.close()

    tipo = 'moderação' if eh_admin and not eh_dono else 'próprio'
    registrar_evento(session['user_id'], 'apagar_comentario', f'comentário {comentario_id} ({tipo})')

    flash('Comentário apagado.', 'success')
    return redirect(url_for('index'))

@app.route('/perfil', methods=['GET'])
def perfil():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT nome, email, bio, foto_key FROM usuarios WHERE id = %s", (session['user_id'],))
    usuario = cursor.fetchone()

    cursor.execute(
        "SELECT tmdb_movie_id, titulo, poster_path FROM favoritos WHERE usuario_id = %s ORDER BY criado_em DESC",
        (session['user_id'],)
    )
    favoritos = cursor.fetchall()
    cursor.close()
    conn.close()

    foto_url = None
    if usuario and usuario.get('foto_key'):
        versao = usuario['foto_key'].rsplit('/', 1)[-1].split('.')[0]
        foto_url = url_for('foto_perfil', usuario_id=session['user_id'], v=versao)

    return render_template('perfil.html', usuario=usuario, favoritos=favoritos, foto_url=foto_url)

@app.route('/foto/<int:usuario_id>', methods=['GET'])
def foto_perfil(usuario_id):
    if 'user_id' not in session:
        return ('', 401)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT foto_key FROM usuarios WHERE id = %s", (usuario_id,))
    linha = cursor.fetchone()
    cursor.close()
    conn.close()

    if not linha or not linha['foto_key']:
        return ('', 404)

    try:
        objeto = minio_client.get_object(MINIO_BUCKET, linha['foto_key'])
    except S3Error:
        return ('', 404)

    def gerar():
        try:
            for pedaco in objeto.stream(32 * 1024):
                yield pedaco
        finally:
            objeto.close()
            objeto.release_conn()

    resposta = Response(gerar(), mimetype=objeto.headers.get('Content-Type', 'application/octet-stream'))
    resposta.headers['Cache-Control'] = 'private, max-age=86400'
    resposta.headers['X-Content-Type-Options'] = 'nosniff'
    return resposta

@app.route('/perfil/bio', methods=['POST'])
def atualizar_bio():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    bio = request.form.get('bio', '').strip()[:280]

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE usuarios SET bio = %s WHERE id = %s", (bio, session['user_id']))
    conn.commit()
    cursor.close()
    conn.close()

    registrar_evento(session['user_id'], 'atualizar_bio')
    flash('Bio atualizada.', 'success')
    return redirect(url_for('perfil'))

@app.route('/perfil/foto', methods=['POST'])
def atualizar_foto():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    arquivo = request.files.get('foto')
    if not arquivo or arquivo.filename == '':
        flash('Nenhum arquivo selecionado.', 'danger')
        return redirect(url_for('perfil'))

    if not extensao_valida(arquivo.filename):
        flash('Formato inválido. Envie uma imagem (png, jpg, jpeg, gif ou webp).', 'danger')
        return redirect(url_for('perfil'))

    if not (arquivo.mimetype or '').startswith('image/'):
        flash('Arquivo inválido: o tipo de conteúdo não é uma imagem.', 'danger')
        return redirect(url_for('perfil'))

    try:
        garantir_bucket()

        extensao = arquivo.filename.rsplit('.', 1)[1].lower()
        chave = f"{session['user_id']}/{uuid.uuid4().hex}.{extensao}"

        arquivo.stream.seek(0, os.SEEK_END)
        tamanho = arquivo.stream.tell()
        arquivo.stream.seek(0)

        minio_client.put_object(
            MINIO_BUCKET, chave, arquivo.stream, length=tamanho, content_type=arquivo.mimetype
        )
    except S3Error as e:
        flash(f'Erro ao enviar a imagem para o object storage: {e}', 'danger')
        return redirect(url_for('perfil'))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE usuarios SET foto_key = %s WHERE id = %s", (chave, session['user_id']))
    conn.commit()
    cursor.close()
    conn.close()

    registrar_evento(session['user_id'], 'atualizar_foto_perfil', chave)
    flash('Foto de perfil atualizada!', 'success')
    return redirect(url_for('perfil'))

@app.route('/admin/usuarios', methods=['GET'])
@admin_required
def admin_usuarios():
    resposta = requests.get('http://auth_api:5001/usuarios')
    usuarios = resposta.json().get('usuarios', [])
    return render_template('admin_usuarios.html', usuarios=usuarios)

@app.route('/admin/usuarios/<int:usuario_id>/role', methods=['POST'])
@admin_required
def admin_alterar_role(usuario_id):
    novo_role = request.form.get('role')

    resposta = requests.put(
        f'http://auth_api:5001/usuarios/{usuario_id}/role',
        json={'role': novo_role}
    )

    if resposta.status_code == 200:
        flash(resposta.json().get('mensagem', 'Papel atualizado.'), 'success')
    else:
        flash(resposta.json().get('erro', 'Erro ao atualizar papel'), 'danger')

    return redirect(url_for('admin_usuarios'))

@app.route('/admin/usuarios/<int:usuario_id>/deletar', methods=['POST'])
@admin_required
def admin_deletar_usuario(usuario_id):
    if usuario_id == session['user_id']:
        flash('Você não pode apagar a própria conta enquanto estiver logado.', 'danger')
        return redirect(url_for('admin_usuarios'))

    resposta = requests.delete(f'http://auth_api:5001/usuarios/{usuario_id}')

    if resposta.status_code == 200:
        flash(resposta.json().get('mensagem', 'Usuário apagado.'), 'success')
    else:
        flash(resposta.json().get('erro', 'Erro ao apagar usuário'), 'danger')

    return redirect(url_for('admin_usuarios'))

@app.route('/admin/metricas', methods=['GET'])
@admin_required
def admin_metricas():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT COUNT(*) AS total FROM usuarios")
    total_usuarios = cursor.fetchone()['total']

    cursor.execute("SELECT COUNT(*) AS total FROM favoritos")
    total_favoritos = cursor.fetchone()['total']

    cursor.execute("SELECT COUNT(DISTINCT tmdb_movie_id) AS total FROM favoritos")
    filmes_distintos_favoritados = cursor.fetchone()['total']

    cursor.execute("SELECT COUNT(*) AS total FROM comentarios")
    total_comentarios = cursor.fetchone()['total']

    cursor.execute("SELECT role, COUNT(*) AS total FROM usuarios GROUP BY role")
    usuarios_por_papel = cursor.fetchall()

    cursor.close()
    conn.close()

    metricas = {
        "total_usuarios": total_usuarios,
        "total_favoritos": total_favoritos,
        "filmes_distintos_favoritados": filmes_distintos_favoritados,
        "total_comentarios": total_comentarios,
        "usuarios_por_papel": usuarios_por_papel,
    }

    return render_template('admin_metricas.html', metricas=metricas)

@app.route('/admin/logs', methods=['GET'])
@admin_required
def admin_logs():
    n = request.args.get('n', default=50, type=int)

    try:
        resposta = requests.get(f'http://log_service:5002/eventos', params={'n': n}, timeout=3)
        eventos = resposta.json().get('eventos', [])
    except requests.exceptions.RequestException:
        eventos = []
        flash('Não foi possível consultar o log-service.', 'danger')

    for ev in eventos:
        try:
            ev['timestamp_fmt'] = datetime.fromtimestamp(float(ev['timestamp']), tz=BRASILIA_TZ).strftime('%d/%m/%Y %H:%M:%S')
        except (KeyError, ValueError, TypeError):
            ev['timestamp_fmt'] = ev.get('timestamp', '')

    return render_template('admin_logs.html', eventos=eventos, n=n)

@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    token = request.args.get('token') or request.form.get('token')

    if not token:
        flash('Token de recuperação não fornecido.', 'danger')
        return redirect(url_for('login'))

    if request.method == 'POST':
        nova_senha = request.form.get('senha')

        resposta = requests.post('http://auth_api:5001/reset-password', json={
            'token': token,
            'senha': nova_senha
        })

        if resposta.status_code == 200:
            flash(resposta.json().get('mensagem'), 'success')
            return redirect(url_for('login'))
        else:
            erro = resposta.json().get('erro', 'Erro ao redefinir senha')
            flash(erro, 'danger')

    return render_template('reset_password.html', token=token)