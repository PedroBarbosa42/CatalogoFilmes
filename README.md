# 🎬 Catálogo de Filmes — Microsserviços, Autenticação e Papéis de Admin

Aplicação web de catálogo de filmes (filmografia de Tom Hanks, via API do TMDB) onde usuários cadastrados podem favoritar filmes e comentar. Construída como dois microsserviços separados em containers Docker, com um serviço de autenticação isolado e um sistema de papéis (`usuario` / `admin`) com moderação, gestão de acessos e métricas.

Projeto desenvolvido para a disciplina do professor [@siriani](https://github.com/siriani) — Atividade 3 (arquitetura de microsserviços) e evolução com controle de permissões por papel.

**Ambiente publicado:** `https://pedro-ferreira-isw055.lapps.studio`

---

## 🏗️ Arquitetura

A aplicação é dividida em dois serviços independentes, cada um no seu container, comunicando-se pela rede interna do Docker:

```
                    Internet
                        │
                        ▼
              ┌───────────────────┐
              │   catalogo_web     │  ← único ponto público (porta 8225)
              │  (Flask, templates)│
              └─────────┬──────────┘
                         │ rede interna Docker
                         │ (sem porta exposta)
                         ▼
              ┌───────────────────┐
              │     auth_api       │
              │  (Flask, sem UI)   │
              └─────────┬──────────┘
                         │
                         ▼
              ┌───────────────────┐
              │   MySQL externo    │  (fora do docker-compose,
              │  (usuarios, favo-  │   acessado também via DBeaver)
              │  ritos, comentá-   │
              │  rios, reset_...)  │
              └───────────────────┘
```

- **`catalogo_service` (`catalogo_web`)**: único serviço com porta publicada para fora (`8225:5000`). Serve as páginas (catálogo, login, cadastro, telas de admin), guarda a sessão do usuário logado e fala com o `auth_api` quando precisa (login, cadastro, recuperação de senha, gestão de papéis).
- **`auth_service` (`auth_api`)**: **não tem porta publicada para o host** — só é alcançável pela rede interna do Docker (`http://auth_api:5001`). Concentra tudo relacionado a identidade: cadastro, login, papéis (`role`), recuperação de senha com envio de e-mail real via Mailtrap.
- **Banco de dados**: MySQL **externo**, fora do `docker-compose.yml` (endereço configurado em `.env` via `DB_HOST`), compartilhado pelos dois serviços.

---

## ✨ Funcionalidades

### Catálogo (todo usuário logado)
- Navega pela filmografia de Tom Hanks (busca via API pública do TMDB).
- Favorita/desfavorita filmes.
- Comenta em filmes — os comentários aparecem para todos, com o nome de quem comentou.
- Apaga os **próprios** comentários.

### Conta
- Cadastro (`/register`) — todo novo usuário nasce com `role = usuario`.
- Login (`/login`) — sessão baseada em cookie assinado (Flask session).
- Recuperação de senha (`/forgot-password` → `/reset-password`) — token seguro de 32 bytes, expira em 30 minutos, enviado por e-mail real via Mailtrap (SMTP, porta 2525).

### Administração (exclusivo de `admin`)
- **Moderação de comentários**: apaga o comentário de **qualquer usuário** (não só os próprios) — útil pra remover spoiler ou xingamento.
- **Gestão de papéis**: tela (`/admin/usuarios`) que lista todos os usuários cadastrados e permite promover (`usuario` → `admin`) ou rebaixar (`admin` → `usuario`) qualquer um.
- **Dashboard de métricas** (`/admin/metricas`): total de usuários cadastrados, total de favoritos, filmes distintos favoritados, total de comentários e a quebra de usuários por papel.

---

## 🔐 Permissões por papel

### `usuario` (padrão de todo cadastro novo) pode:
- Navegar pelo catálogo de filmes.
- Adicionar e remover favoritos.
- Comentar em filmes.
- Apagar **exclusivamente os próprios comentários**.

### `admin` herda tudo isso e, além disso, pode:
- **Moderação de comentários**: apagar o comentário de **qualquer usuário** — `POST /deletar-comentario/<id>`.
- **Gestão de papéis**: listar todos os usuários e promover/rebaixar o `role` de qualquer um — `GET /admin/usuarios` e `POST /admin/usuarios/<id>/role`.
- **Dashboard de métricas**: ver o relatório interno — `GET /admin/metricas`.

---

## 🛡️ Enforcement das ações de admin

Todas as checagens abaixo rodam **no backend**, a partir do `role` do usuário autenticado (guardado na sessão assinada do Flask, recebida do `auth_api` no login) — nunca dependem de nada que a interface esconda, então funcionam igual clicando na tela ou chamando o endpoint direto:

- **`POST /deletar-comentario/<id>`**: permite se o usuário é o **autor** do comentário OU **admin**; qualquer outro caso → `403`.
- **`GET /admin/usuarios`**, **`POST /admin/usuarios/<id>/role`**, **`GET /admin/metricas`**: só permitem se `role == 'admin'` (decorator `@admin_required`); qualquer outro caso → `403` (ou `401` se nem estiver logado).

A gestão de papéis é dividida em duas pontas: o `catalogo_web` (único ponto público) faz a checagem de admin e delega a alteração de fato para dois endpoints internos do `auth_api` (`GET /usuarios` e `PUT /usuarios/<id>/role`) — que não têm porta exposta pra internet, só acessíveis pela rede interna do Docker, então continuam invisíveis de fora mesmo sem checagem própria de role.

---

## 🧪 Demonstração prática

O domínio público (`https://pedro-ferreira-isw055.lapps.studio`) fica atrás de um desafio anti-bot do Cloudflare, que barra requisições automatizadas sem navegador (curl, Postman) antes mesmo de chegar na aplicação. Por isso, a demonstração foi feita de duas formas, dependendo do alvo:

### Pelo navegador, direto no domínio público (forma usada aqui)

Login como usuário comum e como admin, acessando a mesma rota digitando a URL direto na barra de endereço (sem clicar em nenhum botão da interface):

1. Logado como `usuario` (Marcio), acessar `https://pedro-ferreira-isw055.lapps.studio/admin/usuarios` → retorna `{"erro": "Ação restrita a administradores."}`, HTTP `403`.
2. Logado como `admin` (Pedro), acessar a mesma URL → carrega a tela de Gestão de Papéis normalmente, HTTP `200`.

Acesso com usuario comum e admin
| Comum → Login | Admin → Login |
|---|---|
| ![Usuário comum recebe 403 em /admin/usuarios](imagens/comum-acesso.png) | ![Admin acessa /admin/usuarios com sucesso](imagens/admin-acesso.png) |

Teste `/admin/usuarios`:

| Usuário comum → `403` | Admin → sucesso |
|---|---|
| ![Usuário comum recebe 403 em /admin/usuarios](imagens/comum-403-usuarios.png) | ![Admin acessa /admin/usuarios com sucesso](imagens/admin-200-usuarios.png) |


O mesmo teste, repetido para `/admin/metricas`:

| Usuário comum → `403` | Admin → sucesso |
|---|---|
| ![Usuário comum recebe 403 em /admin/metricas](imagens/comum-403-metricas.png) | ![Admin acessa /admin/metricas com sucesso](imagens/admin-200-metricas.png) |

Já `/deletar-comentario/<id>` é testado clicando no botão "✕" do próprio comentário: ele só aparece para o autor ou para o admin, e some da interface para os demais — mas o enforcement real está no backend, não em esconder o botão.

| Usuário comum | Usuário admin |
|---|---|
| ![Usuário comum](imagens/deletar-comum.png) | ![Usuario admin](imagens/deletar-admin.png) |

### Alternativa via curl/Postman (rodando local, sem o Cloudflare no caminho)

Como o Cloudflare só existe na frente do domínio público, testar via curl/Postman contra o `localhost:8225` (mesma stack, rodando na própria máquina) prova exatamente o mesmo enforcement, sem esbarrar num proxy de terceiro:

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

> Para ter um usuário `admin` no ambiente de testes, promova um cadastro já existente diretamente no banco (antes de existir a tela de gestão de papéis, ou pra criar o primeiro admin):
> ```sql
> UPDATE usuarios SET role = 'admin' WHERE email = 'admin@teste.com';
> ```

---

## 🏗️ Padrão A ou B?

Hoje o projeto usa o **Padrão B — claims na sessão** (equivalente em espírito ao "claims no token"), e não o Padrão A.

O `catalogo_web` consulta o `auth_api` **uma única vez, no login**. A resposta (incluindo o `role`) é guardada na sessão do Flask — que é um cookie assinado criptograficamente com o `SECRET_KEY` do próprio `catalogo_web`, então não pode ser adulterado pelo cliente. A partir daí, toda decisão de permissão (inclusive o `403` das rotas de admin) é tomada localmente pelo `catalogo_web`, lendo esse cookie — **sem nenhuma nova chamada de rede ao `auth_api`** a cada ação.

Isso é diferente do Padrão A (enforcement centralizado), onde cada ação sensível faria uma ida-e-volta de rede até o `auth_api` perguntando "esse usuário pode fazer isso?".

**Se fôssemos migrar para o Padrão A**, cada rota sensível do `catalogo_web` (como `/deletar-comentario/<id>` ou `/admin/usuarios`) precisaria, a cada requisição, chamar um novo endpoint do `auth_api` (ex: `GET /verificar-permissao?usuario_id=...&acao=...`) para confirmar o papel atual antes de agir, em vez de confiar no `role` já guardado na sessão. Ganharíamos atualização imediata (se um admin rebaixasse alguém, o efeito seria instantâneo, não só no próximo login), mas perderíamos performance e criaríamos uma dependência de rede a mais — e um ponto único de falha — em cada ação do catálogo.

---

## 🗂️ Estrutura do projeto

```
CatalogoFilmes/
├── .env.example
├── docker-compose.yml
├── README.md
│
├── auth_service/                # serviço de autenticação (sem porta pública)
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app.py                   # /register /login /forgot-password /reset-password
│                                 # /usuarios (interno) /usuarios/<id>/role (interno)
│
└── catalogo_service/             # serviço público (porta 8225)
    ├── Dockerfile
    ├── requirements.txt
    ├── app.py                    # rotas do catálogo + rotas de admin
    ├── static/
    │   └── style.css
    └── templates/
        ├── login.html
        ├── register.html
        ├── forgot_password.html
        ├── reset_password.html
        ├── index.html
        ├── admin_usuarios.html   # gestão de papéis
        └── admin_metricas.html   # dashboard de métricas
```

---

## 🗃️ Modelo de dados

```sql
usuarios      (id, nome, email, senha_hash, role, criado_em)
favoritos     (id, usuario_id, tmdb_movie_id, titulo, poster_path, criado_em)
comentarios   (id, usuario_id, tmdb_movie_id, texto, criado_em)
reset_tokens  (token, usuario_id, criado_em, expira_em, usado)
```

`role` aceita dois valores: `usuario` (padrão) e `admin`.

---

## 🐳 Configuração do Docker (docker-compose.yml)

Os dois serviços da aplicação ficam isolados na mesma rede Docker, garantindo que o `auth_api` não exponha portas externas — o `catalogo_web` é o único ponto de entrada público:

```yaml
services:
  catalogo_web:
    build: ./catalogo_service
    ports:
      - "8225:5000" # ÚNICO PONTO PÚBLICO
    environment:
      - TMDB_API_KEY=${TMDB_API_KEY}
      - DB_HOST=${DB_HOST}
      - DB_USER=${DB_USER}
      - DB_PASSWORD=${DB_PASSWORD}
      - DB_NAME=${DB_NAME}
      - SECRET_KEY=${SECRET_KEY}
    depends_on:
      - auth_api

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
      - MAIL_USE_TLS=${MAIL_USE_TLS}
      - MAIL_USE_SSL=${MAIL_USE_SSL}
```

O banco de dados MySQL roda **fora** desse `docker-compose.yml` — o endereço vem da variável `DB_HOST` no `.env`.

---

## ▶️ Como rodar localmente

1. Copie `.env.example` para `.env` e preencha com suas credenciais reais (TMDB, banco de dados, SECRET_KEY, Mailtrap).
2. `docker compose up --build -d`
3. Acesse `http://localhost:8225`.
4. Para ter um usuário `admin` de teste, cadastre-se normalmente pela tela e depois promova o seu usuário direto no banco:
   ```sql
   UPDATE usuarios SET role = 'admin' WHERE email = 'seu_email_de_teste@x.com';
   ```
   A partir daí, promover os próximos usuários já pode ser feito pela própria tela `/admin/usuarios`.