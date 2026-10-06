# 🎬 Catálogo de Filmes — Microsserviços, Autenticação, Papéis de Admin, Auditoria e Perfil

## O que é

Uma aplicação web de catálogo de filmes: usuários se cadastram, navegam pela filmografia de Tom Hanks (via API pública do TMDB), favoritam títulos e comentam. Além disso, existe uma camada de controle de acesso por papéis (`usuario` / `admin`), um sistema de auditoria que registra as ações relevantes do sistema, e uma página de perfil com foto guardada num object storage próprio.

A aplicação é dividida em **microsserviços independentes**, cada um em seu próprio container Docker — essa decisão está detalhada na seção [Arquitetura](#-arquitetura).

Projeto acadêmico desenvolvido para a disciplina do professor [@siriani](https://github.com/siriani).

**Ambiente publicado:** `https://pedro-ferreira-isw055.lapps.studio`

> ### 📄 Relatório (P1)
> Metodologia, arquitetura e evidências de cada entrega do bimestre, em PDF:
> **[📥 `docs/P1_ISW055_Pedro_Ferreira.pdf`](docs/P1_ISW055_Pedro_Ferreira.pdf)**

---

## 🏗️ Arquitetura

A aplicação é dividida em cinco peças, comunicando-se pela rede interna do Docker:

```
                    Internet
                        │
                        ▼
              ┌───────────────────┐
              │   catalogo_web     │  ← único ponto público (porta 8225)
              │  (Flask, templates)│
              └──┬──────┬──────┬───┘
                 │      │      │  rede interna Docker (sem porta exposta)
                 ▼      ▼      ▼
      ┌──────────┐ ┌──────────┐ ┌──────────┐
      │ auth_api │ │log_service│ │  minio   │
      │(sem UI)  │ │ (sem UI)  │ │(object   │
      └────┬─────┘ └────┬─────┘ │ storage) │
           │            │       └────┬─────┘
           ▼            ▼            ▼
   ┌───────────────┐ ┌────────────┐ ┌──────────────┐
   │ MySQL externo │ │Redis Stream│ │ bucket        │
   │ (usuarios,    │ │"auditoria" │ │ "perfis"      │
   │ favoritos,    │ │(XADD/      │ │ (fotos de     │
   │ comentários,  │ │ XREVRANGE) │ │  perfil)      │
   │ reset_...)    │ └────────────┘ └──────────────┘
   └───────────────┘
```

- **`catalogo_service` (`catalogo_web`)** — o único serviço com porta publicada para fora (`8225:5000`). Serve todas as páginas (catálogo, login, cadastro, perfil, telas de admin), guarda a sessão do usuário logado, e conversa com os outros serviços quando precisa. É ele quem decide, a cada requisição, o que o usuário logado pode ou não fazer.
- **`auth_service` (`auth_api`)** — **não tem porta publicada para o host**, só é alcançável pela rede interna do Docker. Concentra tudo relacionado a identidade: cadastro, login, papéis (`role`), exclusão de usuário e recuperação de senha (envio de e-mail via SMTP).
- **`log_service`** — também **sem porta publicada**. Recebe eventos de auditoria do `catalogo_web` e grava num Redis Stream. Não sabe nada sobre permissões ou regras de negócio, só registra o que já aconteceu.
- **`minio`** — object storage, também **sem porta publicada**. Guarda os arquivos de foto de perfil. O banco de dados nunca guarda o arquivo em si, só a **chave** de onde ele está (`foto_key`, na tabela `usuarios`). Exibir a foto de volta é o `catalogo_web` buscando esse arquivo no MinIO por dentro da rede interna e entregando os bytes pro navegador pela rota `GET /foto/<id>` — o bucket é privado (sem leitura pública nem URL pré-assinada), então o MinIO em si nunca fica exposto na internet.
- **Banco de dados MySQL** — **externo**, fora do `docker-compose.yml` (endereço configurado em `.env` via `DB_HOST`), compartilhado pelo `catalogo_service` e pelo `auth_service`.
- **Redis** — roda dentro do `docker-compose.yml`, também sem porta publicada, e guarda só o histórico de eventos (não é dado de negócio, é log).

A lógica por trás de isolar cada peça: o `auth_service` concentra tudo que é sensível sobre identidade num lugar que ninguém de fora alcança diretamente; o `log_service` garante que o histórico de ações não se perca nem seja alterado mexendo no código do catálogo; o `minio` mantém arquivo binário fora do banco relacional (que não é feito pra isso); e o `catalogo_web`, sendo o único ponto público, é o único lugar que precisa se preocupar com o que vem da internet.

---

## ✨ Funcionalidades

### Conta de usuário
- **Cadastro** (`/register`) — todo novo usuário nasce com `role = usuario`.
- **Login** (`/login`) — autenticação via `auth_api`; a sessão fica guardada num cookie assinado pelo Flask no `catalogo_web`.
- **Logout** (`/logout`).
- **Recuperação de senha** (`/forgot-password` → `/reset-password`) — gera um token seguro de 32 bytes com expiração de 30 minutos, e envia um e-mail com o link de redefinição via SMTP (ver [Configuração de e-mail](#-configuração-de-e-mail)).
- **Perfil** (`/perfil`) — nome, e-mail, bio e a lista de filmes favoritados. Toda edição (bio ou foto) é sempre aplicada à conta de quem está logado (`session['user_id']`) — não existe um campo de ID de usuário lido da requisição, então não há como um usuário editar o perfil de outro nem manipulando o formulário.
- **Foto de perfil** — upload de imagem (`png`, `jpg`, `jpeg`, `gif` ou `webp`, até 5 MB), validado por extensão e tipo de conteúdo antes de aceitar. O arquivo vai pro MinIO; o banco guarda só a referência.

### Catálogo (qualquer usuário logado)
- Navega pela filmografia de Tom Hanks.
- **Favorita** e **desfavorita** filmes — a remoção só atinge o próprio favorito, porque a consulta já filtra pelo `usuario_id` da sessão.
- **Comenta** em filmes — os comentários aparecem pra todo mundo, com o nome de quem escreveu.
- **Apaga os próprios comentários**.

### Administração (exclusivo de quem tem `role = admin`)
- **Moderação de comentários** — apaga o comentário de **qualquer usuário**, não só os próprios.
- **Gestão de papéis** (`/admin/usuarios`) — lista todos os usuários cadastrados e permite promover (`usuario` → `admin`) ou rebaixar (`admin` → `usuario`) qualquer um.
- **Excluir usuário** — na mesma tela de gestão de papéis, apaga definitivamente uma conta e tudo que está ligado a ela (favoritos, comentários, tokens de recuperação de senha). Um admin não pode apagar a própria conta enquanto estiver logado.
- **Dashboard de métricas** (`/admin/metricas`) — total de usuários cadastrados, total de favoritos, quantidade de filmes distintos favoritados, total de comentários, e a quebra de usuários por papel.
- **Logs de auditoria** (`/admin/logs`) — consulta os últimos eventos do sistema, do mais recente pro mais antigo.

---

## 🔐 Permissões por papel

### `usuario` (padrão de todo cadastro novo) pode:
- Navegar pelo catálogo de filmes.
- Adicionar e remover favoritos.
- Comentar em filmes.
- Apagar exclusivamente os próprios comentários.
- Editar exclusivamente o próprio perfil (bio e foto).

### `admin` herda tudo isso e, além disso, pode:
- Moderar comentários: apagar o de qualquer usuário — `POST /deletar-comentario/<id>`.
- Gerir papéis: listar usuários e promover/rebaixar qualquer um — `GET /admin/usuarios` e `POST /admin/usuarios/<id>/role`.
- Excluir usuário: apagar qualquer conta, exceto a própria — `POST /admin/usuarios/<id>/deletar`.
- Ver o dashboard de métricas — `GET /admin/metricas`.
- Consultar os logs de auditoria — `GET /admin/logs`.

---

## 🛡️ Como o controle de acesso funciona

Todas as checagens abaixo rodam **no backend**, a partir do `role` do usuário autenticado (guardado na sessão assinada do Flask, recebida do `auth_api` no login):

- **`POST /deletar-comentario/<id>`** — permite se o usuário é o autor do comentário ou admin; qualquer outro caso → `403`.
- **`GET /admin/usuarios`**, **`POST /admin/usuarios/<id>/role`**, **`POST /admin/usuarios/<id>/deletar`**, **`GET /admin/metricas`**, **`GET /admin/logs`** — só permitem se `role == 'admin'` (decorator `@admin_required`); qualquer outro caso → `403` (ou `401` se nem estiver logado).
- **`POST /perfil/bio`**, **`POST /perfil/foto`**, **`GET /foto/<id>`** — nunca leem um campo de ID vindo da requisição; a identidade de quem edita ou consulta é sempre `session['user_id']`. Não há como editar o perfil de outra pessoa nem enviando o ID dela no corpo da requisição, porque esse valor simplesmente não é lido em lugar nenhum do código.

A gestão de papéis e a exclusão de usuário são divididas em duas pontas: o `catalogo_web` (único ponto público) faz a checagem de admin, e delega a alteração de fato pra endpoints internos do `auth_api` (`GET /usuarios`, `PUT /usuarios/<id>/role`, `DELETE /usuarios/<id>`) — sem porta exposta pra internet. A exclusão em si apaga primeiro os favoritos, comentários e tokens de reset do usuário (pra não violar as chaves estrangeiras) e só depois o usuário.

A sessão do usuário guarda o `role` recebido no momento do login (um cookie assinado com o `SECRET_KEY` do `catalogo_web`, que não pode ser adulterado pelo cliente) — as decisões de permissão são tomadas localmente a partir daí, sem uma nova chamada de rede ao `auth_api` a cada ação.

---

## 📋 Logs e Auditoria

Toda ação relevante do sistema deixa um rastro — quem fez, o quê, e quando.

### Por que um microsserviço próprio, e por que Redis

O `log_service` não sabe nada sobre regras de negócio ou permissões: só recebe eventos e grava. Quem decide o que vale a pena logar é sempre o `catalogo_web`, porque é ele quem tem a sessão do usuário logado.

Log de auditoria tem um padrão de uso diferente de dado de negócio: escreve muito, lê pouco, sem transação complexa. Por isso não fica no MySQL — vai pro **Redis Streams** (`XADD` pra gravar, `XREVRANGE` pra consultar os mais recentes primeiro), estrutura pensada pra esse tipo de log ordenado no tempo.

### Eventos registrados

| Ação | Quando é disparado |
|---|---|
| `login` | Depois de autenticar com sucesso |
| `logout` | Antes de limpar a sessão |
| `favoritar` / `desfavoritar` | Ao adicionar/remover um favorito |
| `comentar` | Ao publicar um comentário |
| `apagar_comentario` | Ao apagar um comentário — o `detalhe` diz se foi `(próprio)` ou `(moderação)` |
| `atualizar_bio` / `atualizar_foto_perfil` | Ao editar o próprio perfil |
| `acesso_negado` | Toda vez que uma rota de admin barra um usuário comum com `403` |

Cada evento grava `usuario_id`, `acao`, `detalhe`, `ip` e `timestamp` (exibido já convertido pro horário de Brasília, UTC-3).

### Consultar os logs

`GET /admin/logs` (aceita `?n=` pra mudar quantos eventos trazer, padrão 50), protegida pelo mesmo `@admin_required` das outras telas de admin.

---

## 📧 Configuração de e-mail

A função de envio de e-mail (recuperação de senha) foi escrita de forma **genérica**, usando `smtplib` puro — funciona com qualquer provedor SMTP (Brevo, Mailtrap, Gmail, etc.), trocando só as variáveis de ambiente, sem mexer em código:

```
MAIL_SERVER=...
MAIL_PORT=...
MAIL_USERNAME=...
MAIL_PASSWORD=...
MAIL_USE_TLS=True   # ou MAIL_USE_SSL=True, dependendo da porta
MAIL_FROM=...       # precisa ser um remetente verificado, no caso do Brevo
```

Atualmente configurado com o **Brevo** (SMTP relay).

---

## 🗂️ Estrutura do projeto

```
CatalogoFilmes/
├── .env.example
├── docker-compose.yml
├── README.md
│
├── auth_service/                 # identidade — sem porta pública
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app.py                    # /register /login /forgot-password /reset-password
│                                  # /usuarios (interno) /usuarios/<id>/role (interno)
│                                  # /usuarios/<id> DELETE (interno)
│
├── log_service/                  # auditoria — sem porta pública
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app.py                    # POST /eventos, GET /eventos (grava/lê no Redis)
│
└── catalogo_service/              # público — porta 8225
    ├── Dockerfile
    ├── requirements.txt           # inclui a lib "minio"
    ├── app.py                     # rotas do catálogo, admin, perfil e /foto/<id>
    ├── static/
    │   └── style.css
    └── templates/
        ├── base.html
        ├── auth_base.html
        ├── login.html
        ├── register.html
        ├── forgot_password.html
        ├── reset_password.html
        ├── index.html
        ├── perfil.html             # perfil + upload de foto + bio
        ├── admin_usuarios.html     # gestão de papéis + exclusão de usuário
        ├── admin_metricas.html     # dashboard de métricas
        └── admin_logs.html         # logs de auditoria
```

---

## 🗃️ Modelo de dados

```sql
usuarios      (id, nome, email, senha_hash, role, bio, foto_key, criado_em)
favoritos     (id, usuario_id, tmdb_movie_id, titulo, poster_path, criado_em)
comentarios   (id, usuario_id, tmdb_movie_id, texto, criado_em)
reset_tokens  (token, usuario_id, criado_em, expira_em, usado)
```

`role` aceita dois valores: `usuario` (padrão) e `admin`. `bio` é um texto curto (até 280 caracteres). `foto_key` é a chave do objeto no MinIO (ex: `7/a1b2c3d4.jpg`) — nunca o arquivo em si.

Os eventos de auditoria não ficam nessas tabelas — vivem à parte, no Redis Stream `auditoria`, gerenciado pelo `log_service`. As fotos de perfil também não ficam no banco — vivem no bucket `perfis` do MinIO.

---

## 🐳 Configuração do Docker (`docker-compose.yml`)

```yaml
services:
  catalogo_web:
    build: ./catalogo_service
    ports:
      - "8225:5000"
    environment:
      - TMDB_API_KEY=${TMDB_API_KEY}
      - DB_HOST=${DB_HOST}
      - DB_USER=${DB_USER}
      - DB_PASSWORD=${DB_PASSWORD}
      - DB_NAME=${DB_NAME}
      - SECRET_KEY=${SECRET_KEY}
      - MINIO_ROOT_USER=${MINIO_ROOT_USER}
      - MINIO_ROOT_PASSWORD=${MINIO_ROOT_PASSWORD}
      - MINIO_BUCKET=${MINIO_BUCKET}
    depends_on:
      - auth_api
      - log_service
      - minio

  auth_api:
    build: ./auth_service
    environment:
      - PYTHONUNBUFFERED=1
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
      - MAIL_FROM=${MAIL_FROM}

  log_service:
    build: ./log_service
    environment:
      - PYTHONUNBUFFERED=1
      - REDIS_HOST=redis
      - REDIS_PORT=6379
    depends_on:
      - redis

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data

  minio:
    image: pgsty/minio:RELEASE.2026-08-04T00-00-00Z
    command: server /data --console-address ":9001"
    environment:
      - MINIO_ROOT_USER=${MINIO_ROOT_USER}
      - MINIO_ROOT_PASSWORD=${MINIO_ROOT_PASSWORD}
    volumes:
      - minio_data:/data

volumes:
  redis_data:
  minio_data:
```

O MySQL roda **fora** desse arquivo — o endereço vem de `DB_HOST` no `.env`. O Redis e o MinIO rodam **dentro**, mas nenhum dos dois publica porta pro host — só o `log_service` e o `catalogo_web`, respectivamente, falam com eles pela rede interna.

---

## ▶️ Como rodar localmente

1. Copie `.env.example` para `.env` e preencha com suas credenciais reais (TMDB, banco de dados, `SECRET_KEY`, SMTP — ver [Configuração de e-mail](#-configuração-de-e-mail) — e `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD`/`MINIO_BUCKET`).
2. `docker compose up --build -d`
3. Acesse `http://localhost:8225`.
4. Cadastre-se pela tela e promova seu próprio usuário a admin direto no banco:
   ```sql
   UPDATE usuarios SET role = 'admin' WHERE email = 'seu_email_de_teste@x.com';
   ```
   A partir daí, promover os próximos usuários (e apagar contas, se precisar) já pode ser feito pela própria tela `/admin/usuarios`.