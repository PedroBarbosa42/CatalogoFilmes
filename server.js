const express = require('express');
const session = require('express-session');
const mariadb = require('mariadb');
const bcrypt = require('bcrypt');

const app = express();
const PORT = process.env.PORT || 8225;

const pool = mariadb.createPool({
  host: process.env.DB_HOST || 'localhost',
  user: process.env.DB_USER || 'root',
  password: process.env.DB_PASSWORD || '',
  database: process.env.DB_NAME || 'catalogo_filmes',
  connectionLimit: 5
});

app.use(express.json());
app.use(express.static('public'));

app.use(session({
  secret: process.env.SESSION_SECRET || 'chave-secreta-de-sessao',
  resave: false,
  saveUninitialized: false,
  cookie: { secure: false, maxAge: 24 * 60 * 60 * 1000 }
}));

function autenticarMiddleware(req, res, next) {
  if (!req.session.usuario_id) {
    return res.status(401).json({ erro: 'Não autorizado. Faça login primeiro.' });
  }
  next();
}

app.post('/api/registro', async (req, res) => {
  const { nome, email, senha } = req.body;
  if (!nome || !email || !senha) {
    return res.status(400).json({ erro: 'Todos os campos são obrigatórios.' });
  }

  let conn;
  try {
    conn = await pool.getConnection();
    const hash = await bcrypt.hash(senha, 10);
    await conn.query(
      'INSERT INTO usuarios (nome, email, senha_hash) VALUES (?, ?, ?)',
      [nome, email, hash]
    );
    res.status(201).json({ mensagem: 'Usuário cadastrado com sucesso.' });
  } catch (err) {
    if (err.code === 'ER_DUP_ENTRY') {
      return res.status(400).json({ erro: 'E-mail já cadastrado.' });
    }
    res.status(500).json({ erro: 'Erro ao cadastrar usuário.' });
  } finally {
    if (conn) conn.release();
  }
});

app.post('/api/login', async (req, res) => {
  const { email, senha } = req.body;
  let conn;
  try {
    conn = await pool.getConnection();
    const rows = await conn.query('SELECT * FROM usuarios WHERE email = ?', [email]);
    if (rows.length === 0) {
      return res.status(401).json({ erro: 'E-mail ou senha incorretos.' });
    }

    const usuario = rows[0];
    const senhaValida = await bcrypt.compare(senha, usuario.senha_hash);
    if (!senhaValida) {
      return res.status(401).json({ erro: 'E-mail ou senha incorretos.' });
    }

    req.session.usuario_id = usuario.id;
    req.session.usuario_nome = usuario.nome;
    res.json({ mensagem: 'Login efetuado.', usuario: { id: usuario.id, nome: usuario.nome } });
  } catch (err) {
    res.status(500).json({ erro: 'Erro interno ao realizar login.' });
  } finally {
    if (conn) conn.release();
  }
});

app.post('/api/logout', (req, res) => {
  req.session.destroy();
  res.json({ mensagem: 'Logout efetuado.' });
});

app.get('/api/usuario/me', (req, res) => {
  if (!req.session.usuario_id) {
    return res.status(401).json({ logado: false });
  }
  res.json({ logado: true, nome: req.session.usuario_nome });
});

app.get('/api/filmes', autenticarMiddleware, async (req, res) => {
  const apiKey = process.env.TMDB_API_KEY;
  if (!apiKey) {
    return res.status(500).json({ erro: 'TMDB_API_KEY não configurada no servidor.' });
  }

  try {
    const personId = 31;
    const response = await fetch(`https://api.themoviedb.org/3/person/${personId}/movie_credits?api_key=${apiKey}&language=pt-BR`);
    const data = await response.json();

    const filmes = (data.cast || []).map(filme => ({
      id: filme.id,
      titulo: filme.title,
      sinopse: filme.overview || 'Sinopse não disponível.',
      poster_path: filme.poster_path ? `https://image.tmdb.org/t/p/w500${filme.poster_path}` : null
    }));

    res.json(filmes);
  } catch (err) {
    res.status(500).json({ erro: 'Erro ao buscar filmes da TMDB.' });
  }
});

app.get('/api/favoritos', autenticarMiddleware, async (req, res) => {
  let conn;
  try {
    conn = await pool.getConnection();
    const rows = await conn.query(
      'SELECT tmdb_movie_id, titulo, poster_path FROM favoritos WHERE usuario_id = ?',
      [req.session.usuario_id]
    );
    res.json(rows);
  } catch (err) {
    res.status(500).json({ erro: 'Erro ao carregar favoritos.' });
  } finally {
    if (conn) conn.release();
  }
});

app.post('/api/favoritos', autenticarMiddleware, async (req, res) => {
  const { tmdb_movie_id, titulo, poster_path } = req.body;
  let conn;
  try {
    conn = await pool.getConnection();
    await conn.query(
      'INSERT INTO favoritos (usuario_id, tmdb_movie_id, titulo, poster_path) VALUES (?, ?, ?, ?)',
      [req.session.usuario_id, tmdb_movie_id, titulo, poster_path]
    );
    res.status(201).json({ mensagem: 'Filme favoritado com sucesso.' });
  } catch (err) {
    if (err.code === 'ER_DUP_ENTRY') {
      return res.status(400).json({ erro: 'Filme já está nos favoritos.' });
    }
    res.status(500).json({ erro: 'Erro ao favoritar filme.' });
  } finally {
    if (conn) conn.release();
  }
});

app.delete('/api/favoritos/:movieId', autenticarMiddleware, async (req, res) => {
  const movieId = req.params.movieId;
  let conn;
  try {
    conn = await pool.getConnection();
    await conn.query(
      'DELETE FROM favoritos WHERE usuario_id = ? AND tmdb_movie_id = ?',
      [req.session.usuario_id, movieId]
    );
    res.json({ mensagem: 'Favorito removido.' });
  } catch (err) {
    res.status(500).json({ erro: 'Erro ao remover favorito.' });
  } finally {
    if (conn) conn.release();
  }
});

app.get('/api/comentarios', autenticarMiddleware, async (req, res) => {
  let conn;
  try {
    conn = await pool.getConnection();
    const rows = await conn.query(
      'SELECT id, tmdb_movie_id, texto, criado_em FROM comentarios WHERE usuario_id = ? ORDER BY criado_em DESC',
      [req.session.usuario_id]
    );
    res.json(rows);
  } catch (err) {
    res.status(500).json({ erro: 'Erro ao carregar comentários.' });
  } finally {
    if (conn) conn.release();
  }
});

app.post('/api/comentarios', autenticarMiddleware, async (req, res) => {
  const { tmdb_movie_id, texto } = req.body;
  if (!texto || !texto.trim()) {
    return res.status(400).json({ erro: 'O texto do comentário não pode estar vazio.' });
  }

  let conn;
  try {
    conn = await pool.getConnection();
    await conn.query(
      'INSERT INTO comentarios (usuario_id, tmdb_movie_id, texto) VALUES (?, ?, ?)',
      [req.session.usuario_id, tmdb_movie_id, texto]
    );
    res.status(201).json({ mensagem: 'Comentário salvo com sucesso.' });
  } catch (err) {
    res.status(500).json({ erro: 'Erro ao salvar comentário.' });
  } finally {
    if (conn) conn.release();
  }
});

app.listen(PORT, () => {
  console.log(`Servidor rodando na porta ${PORT}`);
});