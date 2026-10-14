
import os
import secrets
from decimal import Decimal, InvalidOperation
from functools import wraps
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from flask import Flask, abort, redirect, render_template, request, session, url_for
from flask_sqlalchemy import SQLAlchemy
from PIL import Image, UnidentifiedImageError
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename

load_dotenv()

app = Flask(__name__)

# configurações
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER = BASE_DIR / "static" / "uploads"

app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY"),
    SQLALCHEMY_DATABASE_URI=os.environ.get(
        "DATABASE_URL",
        f"sqlite:///{BASE_DIR / 'cardapio.db'}"
    ),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    UPLOAD_FOLDER=str(UPLOAD_FOLDER),
    MAX_CONTENT_LENGTH=5 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "false").lower() == "true",
)

SENHA_ADMIN = os.environ.get("ADMIN_PASSWORD")

# configurações de acesso
app.secret_key = "chave_exemplo_apenas_para_demonstracao"
SENHA_ADMIN = "senha_exemplo_123_pra_deixar_vcs_curiosokkk"

# pasta de imagens
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)

UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)

db = SQLAlchemy(app)


# banco de dados
class Produto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    descricao = db.Column(db.String(200))
    preco = db.Column(db.Float, nullable=False)
    preco_combo = db.Column(db.Float, nullable=True)
    descricao_combo = db.Column(db.String(200), nullable=True)
    categoria = db.Column(db.String(50), nullable=False)
    disponivel = db.Column(db.Boolean, default=True, nullable=False)
    imagem = db.Column(db.String(120), nullable=True)


# funções auxiliares
def limpar_preco(valor):
    if not valor or not valor.strip():
        return None

    valor = valor.replace("R$", "").replace("$", "").strip()

    if "," in valor:
        valor = valor.replace(".", "").replace(",", ".")

    try:
        preco = Decimal(valor)
        if not preco.is_finite() or preco < 0:
            return None
        return float(preco)
    except (InvalidOperation, ValueError):
        return None


def salvar_imagem(arquivo):
    if not arquivo or not arquivo.filename:
        return None

    nome_original = secure_filename(arquivo.filename)

    if Path(nome_original).suffix.lower() not in {
        ".jpg", ".jpeg", ".png", ".webp"
    }:
        abort(400, description="formato de imagem inválido")

    try:
        imagem = Image.open(arquivo.stream)
        imagem.verify()
        formato = imagem.format
    except (UnidentifiedImageError, OSError, ValueError):
        abort(400, description="arquivo de imagem inválido")

    extensoes = {
        "JPEG": ".jpg",
        "PNG": ".png",
        "WEBP": ".webp",
    }

    if formato not in extensoes:
        abort(400, description="formato de imagem não permitido")

    nome = f"{uuid4().hex}{extensoes[formato]}"
    arquivo.stream.seek(0)
    arquivo.save(UPLOAD_FOLDER / nome)

    return nome


def login_required(func):
    @wraps(func)
    def verificar_login(*args, **kwargs):
        if not session.get("usuario_logado"):
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    return verificar_login


# proteção dos formulários
def gerar_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


app.jinja_env.globals["csrf_token"] = gerar_csrf_token


@app.before_request
def verificar_csrf():
    if request.method == "POST":
        token = session.get("csrf_token")
        enviado = request.form.get("csrf_token", "")

        if not token or not secrets.compare_digest(token, enviado):
            abort(400, description="formulário inválido ou expirado")


@app.errorhandler(RequestEntityTooLarge)
def arquivo_grande(erro):
    return "o arquivo enviado excede o limite de 5 mb", 413


# cardápio
@app.route("/")
def index():
    produtos = Produto.query.filter_by(disponivel=True).all()
    categorias = {}

    for produto in produtos:
        categorias.setdefault(produto.categoria, []).append(produto)

    return render_template("cardapio.html", categorias=categorias)


# autenticação
@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("usuario_logado"):
        return redirect(url_for("admin"))

    erro = None

    if request.method == "POST":
        senha = request.form.get("senha", "")

        if secrets.compare_digest(senha, SENHA_ADMIN):
            session.clear()
            session["usuario_logado"] = True
            return redirect(url_for("admin"))

        erro = "senha incorreta."

    return render_template("login.html", erro=erro)


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    return redirect(url_for("index"))


# painel administrativo
@app.route("/admin")
@login_required
def admin():
    produtos = Produto.query.order_by(Produto.id.desc()).all()
    return render_template("admin.html", produtos=produtos)


# adicionar produto
@app.route("/admin/adicionar", methods=["GET", "POST"])
@login_required
def adicionar():
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        categoria = request.form.get("categoria", "").strip()
        preco = limpar_preco(request.form.get("preco"))

        if not nome or not categoria or preco is None:
            abort(400, description="dados obrigatórios inválidos")

        valor_combo = request.form.get("preco_combo", "")
        preco_combo = limpar_preco(valor_combo)

        if valor_combo.strip() and preco_combo is None:
            abort(400, description="preço do combo inválido")

        arquivo = request.files.get("imagem")
        nome_imagem = salvar_imagem(arquivo)

        produto = Produto(
            nome=nome,
            descricao=request.form.get("descricao", "").strip(),
            preco=preco,
            preco_combo=preco_combo,
            descricao_combo=request.form.get("descricao_combo", "").strip(),
            categoria=categoria,
            imagem=nome_imagem
        )

        db.session.add(produto)
        db.session.commit()

        return redirect(url_for("admin"))

    return render_template("adicionar.html")


# editar produto
@app.route("/admin/editar/<int:id>", methods=["GET", "POST"])
@login_required
def editar(id):
    produto = db.get_or_404(Produto, id)

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        categoria = request.form.get("categoria", "").strip()
        preco = limpar_preco(request.form.get("preco"))
        valor_combo = request.form.get("preco_combo", "")
        preco_combo = limpar_preco(valor_combo)

        if not nome or not categoria or preco is None:
            abort(400, description="dados obrigatórios inválidos")

        if valor_combo.strip() and preco_combo is None:
            abort(400, description="preço do combo inválido")

        arquivo = request.files.get("imagem")
        nome_imagem = salvar_imagem(arquivo)

        produto.nome = nome
        produto.descricao = request.form.get("descricao", "").strip()
        produto.categoria = categoria
        produto.preco = preco
        produto.preco_combo = preco_combo
        produto.descricao_combo = request.form.get(
            "descricao_combo", ""
        ).strip()

        if nome_imagem:
            produto.imagem = nome_imagem

        db.session.commit()
        return redirect(url_for("admin"))

    return render_template("editar.html", produto=produto)


# excluir produto
@app.route("/admin/excluir/<int:id>", methods=["POST"])
@login_required
def excluir(id):
    produto = db.get_or_404(Produto, id)

    db.session.delete(produto)
    db.session.commit()

    return redirect(url_for("admin"))


# alterar disponibilidade
@app.route("/admin/status/<int:id>", methods=["POST"])
@login_required
def status(id):
    produto = db.get_or_404(Produto, id)

    produto.disponivel = not produto.disponivel
    db.session.commit()

    return redirect(url_for("admin"))


# inicialização do banco
with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "5000")),
        debug=False
    )
