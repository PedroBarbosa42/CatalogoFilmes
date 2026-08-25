from flask import Flask, request, jsonify
import mysql.connector
import os
from werkzeug.security import generate_password_hash, check_password_hash
import secrets
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText

app = Flask(__name__)

def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME')
    )

def enviar_email_recuperacao(email_destino, token):
    link_recuperacao = f"http://localhost:8225/reset-password?token={token}"
    
    corpo_email = f"""Olá,
    
Você solicitou a recuperação de senha.
Clique no link abaixo para redefinir:
{link_recuperacao}

Este link expira em 30 minutos.
Se você não solicitou, apenas ignore este e-mail.
"""
    
    mensagem = MIMEText(corpo_email)
    mensagem['Subject'] = 'Recuperação de Senha - Catálogo de Filmes'
    mensagem['From'] = 'seguranca@catalogofilmes.com'
    mensagem['To'] = email_destino

    try:
        with smtplib.SMTP(os.getenv('MAIL_SERVER'), int(os.getenv('MAIL_PORT'))) as server:
            if os.getenv('MAIL_USE_TLS') == 'True':
                server.starttls()
            server.login(os.getenv('MAIL_USERNAME'), os.getenv('MAIL_PASSWORD'))
            server.send_message(mensagem)
        return True
    except Exception as e:
        print(f"Erro SMTP: {e}")
        return False

@app.route('/status', methods=['GET'])
def status():
    return jsonify({"servico": "auth_api", "status": "online"}), 200

@app.route('/register', methods=['POST'])
def register():
    dados = request.get_json()
    nome = dados.get('nome')
    email = dados.get('email')
    senha = dados.get('senha')
    
    if not nome or not email or not senha:
        return jsonify({"erro": "Dados incompletos"}), 400
        
    senha_hash = generate_password_hash(senha)
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('INSERT INTO usuarios (nome, email, senha_hash, role) VALUES (%s, %s, %s, %s)', 
                       (nome, email, senha_hash, 'usuario'))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"mensagem": "Usuário registrado com sucesso!"}), 201
    except mysql.connector.IntegrityError:
        return jsonify({"erro": "Email já cadastrado"}), 409
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

@app.route('/login', methods=['POST'])
def login():
    dados = request.get_json()
    email = dados.get('email')
    senha = dados.get('senha')
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT * FROM usuarios WHERE email = %s', (email,))
    usuario = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if usuario and check_password_hash(usuario['senha_hash'], senha):
        return jsonify({
            "mensagem": "Login aprovado", 
            "usuario": {
                "id": usuario['id'],
                "nome": usuario['nome'],
                "role": usuario['role']
            }
        }), 200
    else:
        return jsonify({"erro": "Credenciais inválidas"}), 401

@app.route('/forgot-password', methods=['POST'])
def forgot_password():
    dados = request.get_json()
    email = dados.get('email')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT id FROM usuarios WHERE email = %s', (email,))
    usuario = cursor.fetchone()

    if not usuario:
        cursor.close()
        conn.close()
        return jsonify({"mensagem": "Se o e-mail existir, um link de recuperação será enviado."}), 200

    token = secrets.token_hex(32)
    agora = datetime.now()
    expira_em = agora + timedelta(minutes=30)

    cursor.execute('''
        INSERT INTO reset_tokens (token, usuario_id, criado_em, expira_em)
        VALUES (%s, %s, %s, %s)
    ''', (token, usuario['id'], agora, expira_em))
    conn.commit()
    cursor.close()
    conn.close()

    if enviar_email_recuperacao(email, token):
        return jsonify({"mensagem": "Se o e-mail existir, um link de recuperação será enviado."}), 200
    else:
        return jsonify({"erro": "Falha ao disparar o e-mail."}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)