import os
import time
from flask import Flask, request, jsonify
import redis

app = Flask(__name__)

STREAM_KEY = 'auditoria'

r = redis.Redis(
    host=os.getenv('REDIS_HOST', 'redis'),
    port=int(os.getenv('REDIS_PORT', 6379)),
    decode_responses=True
)

@app.route('/status', methods=['GET'])
def status():
    return jsonify({"servico": "log_service", "status": "online"}), 200

@app.route('/eventos', methods=['POST'])
def registrar_evento():
    dados = request.get_json()
    usuario_id = dados.get('usuario_id')
    acao = dados.get('acao')
    detalhe = dados.get('detalhe', '')
    ip = dados.get('ip', '')

    if usuario_id is None or not acao:
        return jsonify({"erro": "usuario_id e acao são obrigatórios"}), 400

    evento = {
        'usuario_id': str(usuario_id),
        'acao': acao,
        'detalhe': str(detalhe),
        'ip': str(ip),
        'timestamp': str(time.time())
    }

    event_id = r.xadd(STREAM_KEY, evento)
    return jsonify({"mensagem": "Evento registrado", "id": event_id}), 201

@app.route('/eventos', methods=['GET'])
def listar_eventos():
    n = request.args.get('n', default=50, type=int)
    entradas = r.xrevrange(STREAM_KEY, count=n)

    eventos = []
    for entry_id, campos in entradas:
        eventos.append({
            "id": entry_id,
            "usuario_id": campos.get('usuario_id'),
            "acao": campos.get('acao'),
            "detalhe": campos.get('detalhe'),
            "ip": campos.get('ip'),
            "timestamp": campos.get('timestamp'),
        })

    return jsonify({"eventos": eventos}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5002)