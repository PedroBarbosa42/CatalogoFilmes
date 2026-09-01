import os
import requests
import mysql.connector
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'default_secret')

# Decorator reutilizável para as rotas que são EXCLUSIVAS de admin
# (gestão de papéis e dashboard de métricas). A checagem de moderação de
# comentário não usa isso porque ali o dono do comentário também tem
# permissão — não é "admin only" puro.
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({"erro": "Não autenticado"}), 401
        if session.get('user_role') != 'admin':
            return jsonify({"erro": "Ação restrita a administradores."}), 403
        return f(*args, **kwargs)
    return decorated

def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME')
    )

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
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    api_key = os.getenv('TMDB_API_KEY')
    url_busca = f"https://api.themoviedb.org/3/search/person?query=Tom+Hanks&api_key={api_key}"
    search_res = requests.get(url_busca).json()

    print("Retorno TMDB:", search_res)  # Debug para ver o erro no terminal

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

    # ALTERADO: antes só trazia os comentários do próprio usuário logado.
    # Agora traz os comentários de TODOS os usuários (join com "usuarios" para
    # mostrar o nome do autor), pois moderação só faz sentido se dá pra ver
    # comentários de outras pessoas. Também trazemos "id" e "usuario_id" de
    # cada comentário, que são necessários para o botão de apagar.
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
    except mysql.connector.IntegrityError:
        pass
    finally:
        cursor.close()
        conn.close()
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
    return redirect(url_for('index'))

# NOVO: ação exclusiva de admin (com fallback para o dono do comentário).
# Requisito 2: apagar comentário de QUALQUER usuário é privilégio de admin;
# um "usuario" comum só pode apagar o próprio comentário.
# Requisito 3: o enforcement roda aqui no backend, olhando o "role" que o
# catalogo_web recebeu do auth_service no login (guardado na sessão
# assinada do Flask) — não depende de nada que o front esconda ou mostre.
# Funciona igual seja clicando no botão da interface ou chamando o endpoint
# direto via curl/Postman com o cookie de sessão de um usuário autenticado.
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
        return jsonify({"erro": "Ação restrita: apenas o autor do comentário ou um admin podem apagá-lo."}), 403

    cursor.execute("DELETE FROM comentarios WHERE id = %s", (comentario_id,))
    conn.commit()
    cursor.close()
    conn.close()

    flash('Comentário apagado.', 'success')
    return redirect(url_for('index'))

# NOVO: Gestão de Papéis — segunda ação exclusiva de admin.
# Lista os usuários e permite promover/rebaixar o "role" de qualquer um.
# A checagem de admin acontece aqui, no catalogo_web (único ponto público);
# a alteração de fato é delegada ao auth_service, que é quem é dono da
# tabela "usuarios".
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

# NOVO: Dashboard de Métricas — rota exclusiva de admin com um relatório
# simples (quantos usuários existem, quantos favoritos, etc). O
# catalogo_web tem acesso direto ao banco, então consulta na hora.
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