# Catálogo de Filmes - Microsserviços e Autenticação

Atualização da arquitetura para a Atividade 3, implementando um serviço isolado de autenticação e comunicação via rede interna do Docker.

**Professor:** 

## 🏗️ O que mudou na Arquitetura?

1. **Serviço de Autenticação Isolado:** Todo o fluxo de login, cadastro, papéis de usuário (role) e recuperação de senha foi extraído do catálogo e movido para um novo container dedicado (`auth_api`).
2. **Rede Interna Segura:** O serviço de autenticação **não possui portas publicadas para o host**. O catálogo é o único ponto de entrada público. Toda a comunicação entre o catálogo e a autenticação ocorre invisível para a internet, utilizando o DNS interno do Docker.
3. **Recuperação de Senha com SMTP Real:** Implementação da geração de tokens seguros (32 bytes) com expiração de 30 minutos, armazenados no banco de dados. O envio de e-mails de recuperação é feito de forma real via porta 2525 utilizando o ambiente de desenvolvimento Mailtrap.

## 🔐 Permissões por papel

### `usuario` (padrão de todo cadastro novo) pode:
- Navegar pelo catálogo de filmes.
- Adicionar e remover favoritos.
- Comentar em filmes.
- Apagar **exclusivamente os próprios comentários**.

### `admin` herda tudo isso e, além disso, pode:
- **Moderação de comentários:** apagar o comentário de **qualquer usuário** (remover spoiler/xingamento), não só os próprios — `POST /deletar-comentario/<id>`.
- **Gestão de papéis:** listar todos os usuários cadastrados e promover/rebaixar o `role` de qualquer um — `GET /admin/usuarios` e `POST /admin/usuarios/<id>/role`.
- **Dashboard de métricas:** ver um relatório interno (total de usuários, favoritos, comentários, filmes distintos favoritados, usuários por papel) — `GET /admin/metricas`.

## 🛡️ Enforcement das ações de admin

Todas as checagens abaixo rodam no backend, a partir do `role` do usuário autenticado (guardado na sessão assinada do Flask, recebida do `auth_api` no login) — nunca dependem de nada que a interface esconda, então funcionam igual clicando na tela ou chamando o endpoint direto por Postman/curl:

- **`POST /deletar-comentario/<id>`**: permite se o usuário é o **autor** do comentário OU **admin**; qualquer outro caso → `403`.
- **`GET /admin/usuarios`**, **`POST /admin/usuarios/<id>/role`**, **`GET /admin/metricas`**: só permitem se `role == 'admin'` (decorator `@admin_required`); qualquer outro caso → `403` (ou `401` se nem estiver logado).

A gestão de papéis é dividida em duas pontas: o `catalogo_web` (único ponto público) faz a checagem de admin e delega a alteração de fato para dois endpoints internos do `auth_api` (`GET /usuarios` e `PUT /usuarios/<id>/role`) — que não têm porta exposta pra internet, só acessíveis pela rede interna do Docker, então continuam invisíveis de fora mesmo sem checagem própria de role.

## 🧪 Demonstração prática

```bash
# 1. Login como usuário comum, guardando o cookie de sessão
curl -c cookies_usuario.txt -X POST http://localhost:8225/login \
  -d "email=usuario@teste.com&senha=SenhaUsuario123"

# 2. Usuário comum tenta apagar um comentário de outra pessoa (ID de exemplo: 3)
curl -i -b cookies_usuario.txt -X POST http://localhost:8225/deletar-comentario/3
# Esperado: HTTP 403

# 3. Login como admin
curl -c cookies_admin.txt -X POST http://localhost:8225/login \
  -d "email=admin@teste.com&senha=SenhaAdmin123"

# 4. Admin apaga o mesmo comentário
curl -i -b cookies_admin.txt -X POST http://localhost:8225/deletar-comentario/3
# Esperado: sucesso (redirecionamento para o catálogo, comentário removido)

# 5. Usuário comum tenta acessar a gestão de papéis
curl -i -b cookies_usuario.txt http://localhost:8225/admin/usuarios
# Esperado: HTTP 403

# 6. Admin acessa normalmente
curl -i -b cookies_admin.txt http://localhost:8225/admin/usuarios
# Esperado: HTTP 200

# 7. Usuário comum tenta ver o dashboard de métricas
curl -i -b cookies_usuario.txt http://localhost:8225/admin/metricas
# Esperado: HTTP 403

# 8. Admin acessa normalmente
curl -i -b cookies_admin.txt http://localhost:8225/admin/metricas
# Esperado: HTTP 200
```

> Para ter um usuário `admin` no ambiente de testes, promova um cadastro já existente diretamente no banco (ainda não existe endpoint de promoção de papel):
> ```sql
> UPDATE usuarios SET role = 'admin' WHERE email = 'admin@teste.com';
> ```

*(Prints dos dois retornos — 403 e sucesso — devem ser anexados aqui na entrega.)*

## 🏗️ Padrão A ou B?

Hoje o projeto usa o **Padrão B — claims na sessão** (equivalente em espírito ao "claims no token"), e não o Padrão A.

O `catalogo_web` consulta o `auth_api` **uma única vez, no login**. A resposta (incluindo o `role`) é guardada na sessão do Flask — que é um cookie assinado criptograficamente com o `SECRET_KEY` do próprio `catalogo_web`, então não pode ser adulterado pelo cliente. A partir daí, toda decisão de permissão (inclusive o `403` da rota de apagar comentário) é tomada localmente pelo `catalogo_web`, lendo esse cookie — **sem nenhuma nova chamada de rede ao `auth_api`** a cada ação.

Isso é diferente do Padrão A (enforcement centralizado), onde cada ação sensível faria uma ida-e-volta de rede até o `auth_api` perguntando "esse usuário pode fazer isso?".

**Se fôssemos migrar para o Padrão A**, cada rota sensível do `catalogo_web` (como `/deletar-comentario/<id>`) precisaria, a cada requisição, chamar um novo endpoint do `auth_api` (ex: `GET /verificar-permissao?usuario_id=...&acao=...`) para confirmar o papel atual antes de agir, em vez de confiar no `role` já guardado na sessão. Ganharíamos atualização imediata (se um admin rebaixasse alguém, o efeito seria instantâneo, não só no próximo login), mas perderíamos performance e criaríamos uma dependência de rede a mais — e um ponto único de falha — em cada ação do catálogo.

## 🐳 Configuração do Docker (docker-compose.yml)

Abaixo, a demonstração de como os serviços estão isolados na mesma rede, garantindo que o `auth_api` não exponha portas externas:

```yaml
services:
  catalogo_web:
    build: ./catalogo_service
    ports:
      - "8225:5000" # ÚNICO PONTO PÚBLICO
    environment:
      - FLASK_SECRET_KEY=${FLASK_SECRET_KEY}
    depends_on:
      - db
      - auth_api
    networks:
      - rede_catalogo

  auth_api:
    build: ./auth_service
    # SEM PORTAS EXPOSTAS (sem diretiva 'ports')
    environment:
      - DB_HOST=${DB_HOST}
      - DB_USER=${DB_USER}
      - DB_PASSWORD=${DB_PASSWORD}
      - DB_NAME=${DB_NAME}
      - MAIL_SERVER=${MAIL_SERVER}
      - MAIL_PORT=${MAIL_PORT}
      - MAIL_USERNAME=${MAIL_USERNAME}
      - MAIL_PASSWORD=${MAIL_PASSWORD}
    depends_on:
      - db
    networks:
      - rede_catalogo

networks:
  rede_catalogo:
    driver: bridge
```