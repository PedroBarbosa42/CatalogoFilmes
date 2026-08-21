const authSection = document.getElementById('auth-section');
const catalogoSection = document.getElementById('catalogo-section');
const loginBox = document.getElementById('login-box');
const cadastroBox = document.getElementById('cadastro-box');
const linkCadastro = document.getElementById('link-cadastro');
const linkLogin = document.getElementById('link-login');
const userDisplay = document.getElementById('user-display');
const btnLogout = document.getElementById('btn-logout');

let favoritos = [];
let comentarios = [];

linkCadastro.addEventListener('click', (e) => {
    e.preventDefault();
    loginBox.classList.add('hidden');
    cadastroBox.classList.remove('hidden');
});

linkLogin.addEventListener('click', (e) => {
    e.preventDefault();
    cadastroBox.classList.add('hidden');
    loginBox.classList.remove('hidden');
});

document.getElementById('form-cadastro').addEventListener('submit', async (e) => {
    e.preventDefault();
    const nome = document.getElementById('cadastro-nome').value;
    const email = document.getElementById('cadastro-email').value;
    const senha = document.getElementById('cadastro-senha').value;
    const erroDiv = document.getElementById('cadastro-erro');

    try {
        const response = await fetch('/api/registro', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ nome, email, senha })
        });
        const data = await response.json();

        if (response.ok) {
            alert('Cadastro realizado!');
            cadastroBox.classList.add('hidden');
            loginBox.classList.remove('hidden');
        } else {
            erroDiv.textContent = data.erro || 'Erro no cadastro.';
        }
    } catch {
        erroDiv.textContent = 'Erro de conexão.';
    }
});

document.getElementById('form-login').addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = document.getElementById('login-email').value;
    const senha = document.getElementById('login-senha').value;
    const erroDiv = document.getElementById('login-erro');

    try {
        const response = await fetch('/api/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, senha })
        });
        const data = await response.json();

        if (response.ok) {
            iniciarAplicacao();
        } else {
            erroDiv.textContent = data.erro || 'E-mail ou senha incorretos.';
        }
    } catch {
        erroDiv.textContent = 'Erro de conexão.';
    }
});

btnLogout.addEventListener('click', async () => {
    await fetch('/api/logout', { method: 'POST' });
    catalogoSection.classList.add('hidden');
    authSection.classList.remove('hidden');
});

async function verificarSessao() {
    const res = await fetch('/api/usuario/me');
    const data = await res.json();
    if (data.logado) {
        userDisplay.textContent = `Olá, ${data.nome}`;
        iniciarAplicacao();
    }
}

async function iniciarAplicacao() {
    authSection.classList.add('hidden');
    catalogoSection.classList.remove('hidden');
    await Promise.all([carregarFavoritos(), carregarComentarios()]);
    carregarFilmes();
}

async function carregarFavoritos() {
    const res = await fetch('/api/favoritos');
    if (res.ok) favoritos = await res.json();
}

async function carregarComentarios() {
    const res = await fetch('/api/comentarios');
    if (res.ok) comentarios = await res.json();
}

async function carregarFilmes() {
    const res = await fetch('/api/filmes');
    const filmes = await res.json();
    const container = document.getElementById('lista-filmes');
    container.innerHTML = '';

    filmes.forEach(filme => {
        const eFavorito = favoritos.some(f => f.tmdb_movie_id === filme.id);
        const comentariosFilme = comentarios.filter(c => c.tmdb_movie_id === filme.id);

        const card = document.createElement('div');
        card.className = 'card-filme';
        card.innerHTML = `
            <img src="${filme.poster_path || 'https://via.placeholder.com/500x750?text=Sem+Poster'}" alt="${filme.titulo}">
            <div class="card-body">
                <h3>${filme.titulo}</h3>
                <p class="sinopse">${filme.sinopse}</p>
                <button class="btn-fav ${eFavorito ? 'favoritado' : 'nao-favoritado'}" onclick="toggleFavorito(${filme.id}, '${filme.titulo.replace(/'/g, "\\'")}', '${filme.poster_path}', ${eFavorito})">
                    ${eFavorito ? '♥ Favoritado' : '♡ Favoritar'}
                </button>
                <div class="area-comentarios">
                    <div class="lista-comentarios">
                        ${comentariosFilme.map(c => `<div class="comentario-item">${c.texto}</div>`).join('')}
                    </div>
                    <form class="form-comentario" onsubmit="adicionarComentario(event, ${filme.id})">
                        <input type="text" placeholder="Escreva um comentário..." required>
                        <button type="submit" class="btn-secondary">Enviar</button>
                    </form>
                </div>
            </div>
        `;
        container.appendChild(card);
    });
}

async function toggleFavorito(id, titulo, poster, eFavorito) {
    if (eFavorito) {
        await fetch(`/api/favoritos/${id}`, { method: 'DELETE' });
    } else {
        await fetch('/api/favoritos', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tmdb_movie_id: id, titulo, poster_path: poster })
        });
    }
    await carregarFavoritos();
    carregarFilmes();
}

async function adicionarComentario(event, movieId) {
    event.preventDefault();
    const input = event.target.querySelector('input');
    const texto = input.value;

    await fetch('/api/comentarios', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tmdb_movie_id: movieId, texto })
    });

    input.value = '';
    await carregarComentarios();
    carregarFilmes();
}

verificarSessao();