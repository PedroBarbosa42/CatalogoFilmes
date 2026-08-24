from flask import Flask, request, jsonify
import mysql.connector
import os
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME')
    )

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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)