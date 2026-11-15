from flask import Flask, render_template, request, redirect, url_for, send_from_directory, session, flash, jsonify, send_file, abort
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import mysql.connector
import os
import json
import csv
import zipfile
import io
import re
import uuid
import smtplib
import ssl
import socket
from datetime import datetime, timedelta
from decimal import Decimal
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr, parseaddr
from email.policy import SMTP
# PDF (instale com: pip install reportlab)
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, PageBreak
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

# Validação de tipo real de imagem (imghdr foi removido no Python 3.13+)
try:
    import filetype
    _TEM_FILETYPE = True
except ImportError:
    _TEM_FILETYPE = False


# ============================================================================
# HELPERS DE VALIDAÇÃO
# ============================================================================
def _validar_email(email):
    """Valida formato básico de e-mail."""
    padrao = r'^[\w\.-]+@[\w\.-]+\.\w+$'
    return bool(re.match(padrao, email or ""))


def _validar_imagem_real(stream):
    """Valida se o stream é uma imagem de verdade (MIME real)."""
    if not _TEM_FILETYPE:
        return True  # se filetype não estiver instalado, deixa passar
    tipo = filetype.guess(stream)
    if not tipo:
        return False
    return tipo.mime in ("image/jpeg", "image/png", "image/gif", "image/webp")


app = Flask(__name__, template_folder='templates', static_folder='templates')
app.secret_key = "chave_secreta_ipe_2026"
app.permanent_session_lifetime = timedelta(hours=2)


@app.context_processor
def inject_perfil():
    id_perfil = session.get("id_perfil")
    return {
        "is_admin":      id_perfil == PERFIL_PATRIMONIO,
        "is_patrimonio": id_perfil == PERFIL_PATRIMONIO,
        "is_direcao":    False,   # mantido só por compatibilidade com templates
        "is_usuario":    id_perfil == PERFIL_USUARIO,
        "usuario_logado": "id_usuario" in session,
        "perfil_nome":   NOMES_PERFIL.get(id_perfil, "—"),
    }

app.permanent_session_lifetime = timedelta(hours=2)          # 🆕 Timeout de sessão
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'templates', 'uploads')
app.config['BACKUP_FOLDER'] = os.path.join(app.root_path, 'backups')
os.makedirs(app.config['BACKUP_FOLDER'], exist_ok=True)

# ==========================================
# BANCO DE DADOS
# ==========================================
DB_CONFIG = {'host': '127.0.0.1', 'user': 'root', 'password': '1234', 'database': 'gestao_patrimonio'}

# Importa os models DEPOIS que DB_CONFIG existe
from models import (
    BaseModel, Usuario, Sala, Categoria, Status,
    TipoChamado, TipoManutencao, TipoAlerta, TipoAnexo, TipoSala, TipoVerba,
    Patrimonio, Chamado, Manutencao, Movimentacao, ItemMovimentacao,
    Verba, Alerta, Anexo, Historico, HistoricoCompraItem, LogAuditoria,
    LancamentoCaixa, Receita, Despesa, FormularioCaixa
)

BaseModel.DB_CONFIG = DB_CONFIG


def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)


STATUS_CHAMADO = {1: 'Aberto', 2: 'Em Atendimento', 3: 'Concluido', 4: 'Cancelado'}
PRIORIDADES_VALIDAS = {'Baixa', 'Media', 'Alta'}

# ==========================================
# PERFIS DE ACESSO
# ==========================================
PERFIL_PATRIMONIO = 1    # Mirian, Paula — acesso total
PERFIL_USUARIO    = 2    # Setores — só abrem chamados e consultam

PERFIS_VALIDOS = {PERFIL_PATRIMONIO, PERFIL_USUARIO}

NOMES_PERFIL = {
    PERFIL_PATRIMONIO: "Patrimônio",
    PERFIL_USUARIO: "Usuário Padrão",
}

# ==========================================
# CHAVES DE ACESSO (perfis elevados)
# ==========================================
# Configuráveis via variáveis de ambiente. Fallback para os valores atuais.
# Formato: "CHAVE": (id_perfil, descrição, data_expiracao_opcional)
CHAVES_PERFIL = {
    os.environ.get("IPE_CHAVE_ADMIN",   "IPE2026ADMIN"):   {
        "id_perfil": PERFIL_PATRIMONIO,
        "descricao": "Chave de Administrador (Patrimônio)",
        "expira_em": os.environ.get("IPE_CHAVE_ADMIN_EXPIRA", "2026-12-31"),
    },
   
}

# Tentativas inválidas por sessão (para bloqueio temporário)
_CHAVES_TENTATIVAS = {}   # { session_id: {"count": int, "bloqueado_ate": datetime} }
_CHAVES_MAX_TENTATIVAS = 5
_CHAVES_BLOQUEIO_MIN = 15  # minutos


def _normalizar_chave(chave):
    """Remove espaços e padroniza para uppercase."""
    return (chave or "").strip().upper()


def _validar_chave(chave_raw):
    """
    Valida a chave.
    Retorna (id_perfil, mensagem_erro).
    Se válida: (id_perfil_int, None).
    Se inválida: (None, "motivo").
    """
    chave = _normalizar_chave(chave_raw)
    if not chave:
        return None, "Informe a chave de acesso."

    info = CHAVES_PERFIL.get(chave)
    if not info:
        return None, "Chave de acesso inválida."

    # Verifica expiração
    expira = info.get("expira_em")
    if expira:
        try:
            dt_exp = datetime.strptime(expira, "%Y-%m-%d").date()
            if datetime.now().date() > dt_exp:
                return None, "Esta chave de acesso expirou. Solicite uma nova."
        except ValueError:
            pass

    return info["id_perfil"], None


def _registrar_tentativa_chave(session_id, sucesso, chave_recebida, id_perfil=None):
    """
    Loga a tentativa no banco e controla o bloqueio por sessão.
    Retorna (bloqueado: bool, minutos_restantes: int).
    """
    # Log no banco
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        acao = "CHAVE_OK" if sucesso else "CHAVE_INVALIDA"
        descricao = (
            f"Chave de acesso {'válida' if sucesso else 'INVÁLIDA'} "
            f"(recebida: {chave_recebida[:3]}***) "
            f"{'→ perfil ' + str(NOMES_PERFIL.get(id_perfil, id_perfil)) if sucesso else ''}"
        )
        cursor.execute("""INSERT INTO Log_auditoria (acao, descricao, id_usuario)
                          VALUES (%s, %s, %s)""",
                       (acao, descricao, session.get("id_usuario")))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception:
        pass

    # Controle de bloqueio por sessão
    import time
    agora = datetime.now()
    estado = _CHAVES_TENTATIVAS.get(session_id, {"count": 0, "bloqueado_ate": None})

    if estado.get("bloqueado_ate") and agora < estado["bloqueado_ate"]:
        restante = int((estado["bloqueado_ate"] - agora).total_seconds() / 60) + 1
        return True, restante

    if sucesso:
        _CHAVES_TENTATIVAS.pop(session_id, None)
        return False, 0

    estado["count"] = estado.get("count", 0) + 1
    if estado["count"] >= _CHAVES_MAX_TENTATIVAS:
        estado["bloqueado_ate"] = agora + timedelta(minutes=_CHAVES_BLOQUEIO_MIN)
        _CHAVES_TENTATIVAS[session_id] = estado
        return True, _CHAVES_BLOQUEIO_MIN

    _CHAVES_TENTATIVAS[session_id] = estado
    restantes = _CHAVES_MAX_TENTATIVAS - estado["count"]
    return False, restantes

# ==========================================
# RESET DE SENHA (tokens em memória)
# ==========================================
# ⚠️ Tokens em memória são perdidos ao reiniciar o Flask.
# Para persistir, use uma tabela no banco (ver documentação no README).

import secrets
_RESET_TOKENS = {}   # { token: {"id_usuario": int, "expira_em": datetime, "email": str} }
_RESET_TTL_MIN = 15  # validade do link em minutos
_RESET_TENTATIVAS = {}  # { session_id: {"count": int, "bloqueado_ate": datetime} }
_RESET_MAX_TENTATIVAS = 3
_RESET_BLOQUEIO_MIN = 10


def _limpar_tokens_expirados():
    """Remove tokens vencidos da memória. Roda a cada solicitação de reset."""
    agora = datetime.now()
    expirados = [t for t, info in _RESET_TOKENS.items() if info["expira_em"] < agora]
    for t in expirados:
        del _RESET_TOKENS[t]


def _contar_tentativa_reset(session_id, sucesso):
    """Controla bloqueio por sessão para evitar spam de reset."""
    agora = datetime.now()
    estado = _RESET_TENTATIVAS.get(session_id, {"count": 0, "bloqueado_ate": None})

    if estado.get("bloqueado_ate") and agora < estado["bloqueado_ate"]:
        restante = int((estado["bloqueado_ate"] - agora).total_seconds() / 60) + 1
        return True, restante

    if sucesso:
        _RESET_TENTATIVAS.pop(session_id, None)
        return False, 0

    estado["count"] = estado.get("count", 0) + 1
    if estado["count"] >= _RESET_MAX_TENTATIVAS:
        estado["bloqueado_ate"] = agora + timedelta(minutes=_RESET_BLOQUEIO_MIN)
        _RESET_TENTATIVAS[session_id] = estado
        return True, _RESET_BLOQUEIO_MIN

    _RESET_TENTATIVAS[session_id] = estado
    return False, _RESET_MAX_TENTATIVAS - estado["count"]
# ==========================================
# CLASSIFICAÇÃO CGE - PORTARIA Nº 195/2016 (RJ)
# ==========================================
CATEGORIAS_CGE = [
    "1.2.3.1.1.01.02.01 - Amperímetro",
    "1.2.3.1.1.01.02.02 - Balanças",
    "1.2.3.1.1.01.02.09 - Multímetro",
    "1.2.3.1.1.01.02.10 - Osciloscópio",
    "1.2.3.1.1.01.02.15 - Termômetros Climáticos e Clínicos",
    "1.2.3.1.1.01.02.99 - Diversos (Medição e Orientação)",
    "1.2.3.1.1.01.03.01 - Antena Parabólica",
    "1.2.3.1.1.01.03.04 - Aparelhos Telefônicos (Interfone)",
    "1.2.3.1.1.01.03.99 - Diversos (Comunicação)",
    "1.2.3.1.1.01.06.01 - Aspirador de Pó",
    "1.2.3.1.1.01.06.05 - Cafeteiras",
    "1.2.3.1.1.01.06.07 - Escada Portátil",
    "1.2.3.1.1.01.06.09 - Ferro de Passar Roupa",
    "1.2.3.1.1.01.06.11 - Fogões",
    "1.2.3.1.1.01.06.12 - Fornos (Micro-ondas)",
    "1.2.3.1.1.01.06.15 - Geladeira / Refrigerador",
    "1.2.3.1.1.01.06.16 - Liquidificador",
    "1.2.3.1.1.01.06.19 - Máquina de Lavar Roupas",
    "1.2.3.1.1.01.06.25 - Ventiladores",
    "1.2.3.1.1.01.06.99 - Diversos (Utensílios Domésticos)",
    "1.2.3.1.1.01.08.09 - Livros",
    "1.2.3.1.1.01.08.10 - Mapas",
    "1.2.3.1.1.01.08.13 - Publicações",
    "1.2.3.1.1.01.12.01 - Cofres",
    "1.2.3.1.1.01.12.03 - Extintores de Incêndio",
    "1.2.3.1.1.01.13.01 - Instrumentos Musicais em Geral",
    "1.2.3.1.1.01.14.01 - Bebedouros Elétricos",
    "1.2.3.1.1.01.14.02 - Condicionadores de Ar",
    "1.2.3.1.1.01.14.03 - Exaustores e Coifas",
    "1.2.3.1.1.01.14.09 - Máquinas de Costura",
    "1.2.3.1.1.01.14.13 - Máquinas para Controle de Trânsito",
    "1.2.3.1.1.01.14.21 - Máquinas para Tratamento de Água",
    "1.2.3.1.1.01.14.99 - Diversos (Industrial)",
    "1.2.3.1.1.01.15.01 - Estabilizador",
    "1.2.3.1.1.01.15.02 - Geradores e Fontes de Alimentação",
    "1.2.3.1.1.01.15.03 - No-Break",
    "1.2.3.1.1.01.15.04 - Transformadores",
    "1.2.3.1.1.01.16.01 - Aparelhos de Cópia (Copiadoras)",
    "1.2.3.1.1.01.16.04 - Guilhotina",
    "1.2.3.1.1.01.16.05 - Máquinas de Impressão",
    "1.2.3.1.1.01.17.01 - Aparelhos de Som (Rádios)",
    "1.2.3.1.1.01.17.04 - Projetores (Data Show)",
    "1.2.3.1.1.01.17.05 - Televisão",
    "1.2.3.1.1.01.17.99 - Diversos (Áudio/Vídeo)",
    "1.2.3.1.1.01.18.01 - Computadores e Microcomputadores",
    "1.2.3.1.1.01.18.02 - Hub, Switch e Patch Panel",
    "1.2.3.1.1.01.18.03 - Impressoras",
    "1.2.3.1.1.01.18.05 - Monitores",
    "1.2.3.1.1.01.18.07 - Scanners",
    "1.2.3.1.1.01.18.10 - Teclados",
    "1.2.3.1.1.01.18.99 - Diversos (Informática)",
    "1.2.3.1.1.01.19.02 - Carimbos Datadores e Numeradores",
    "1.2.3.1.1.01.19.04 - Fichários",
    "1.2.3.1.1.01.19.05 - Fragmentadora de Papel",
    "1.2.3.1.1.01.19.07 - Grampeadores",
    "1.2.3.1.1.01.19.08 - Máquinas de Calcular",
    "1.2.3.1.1.01.19.10 - Máquinas de Escrever",
    "1.2.3.1.1.01.19.12 - Perfuradores de Papel",
    "1.2.3.1.1.01.20.03 - Ferramentas Agrícolas",
    "1.2.3.1.1.01.20.04 - Ferramentas para Construção Civil",
    "1.2.3.1.1.01.20.09 - Ferramentas para Trabalho em Madeira",
    "1.2.3.1.1.01.20.14 - Ferramentas para Oficina de Solda",
    "1.2.3.1.1.01.20.15 - Material de Jardinagem",
    "1.2.3.1.1.01.20.99 - Diversos (Ferramentas)",
    "1.2.3.1.1.01.21.01 - Bancadas para Cozinha",
    "1.2.3.1.1.01.21.02 - Bombas",
    "1.2.3.1.1.01.21.07 - Motores Térmicos e Elétricos",
    "1.2.3.1.1.01.21.08 - Prensas",
    "1.2.3.1.1.01.23.01 - Armários de Madeira, Aço e Especiais",
    "1.2.3.1.1.01.23.03 - Bancos (Escolares, de Jardim)",
    "1.2.3.1.1.01.23.05 - Cadeiras, Poltronas e Cadeiras Universitárias",
    "1.2.3.1.1.01.23.06 - Carteiras Escolares",
    "1.2.3.1.1.01.23.07 - Colchões",
    "1.2.3.1.1.01.23.10 - Estantes",
    "1.2.3.1.1.01.23.12 - Luminárias",
    "1.2.3.1.1.01.23.14 - Mesas",
    "1.2.3.1.1.01.23.17 - Relógios (Mesa, Parede, Ponto)",
    "1.2.3.1.1.01.23.18 - Roupeiros e Guarda-Roupas",
    "1.2.3.1.1.01.23.20 - Vitrines Especiais",
    "1.2.3.1.1.01.23.99 - Diversos (Mobiliário)",
    "1.2.3.1.1.01.24.11 - Quadros",
    "1.2.3.1.1.01.24.99 - Diversos (Obras de Arte)",
    "1.2.3.1.1.01.26.01 - Bicicletas",
    "1.2.3.1.1.01.26.02 - Carrinho de Mão",
    "1.2.3.1.1.01.26.07 - Empilhadeira",
]


# ==========================================
# DECORATORS
# ==========================================
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "id_usuario" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"erro": "Não autenticado.", "codigo": "NAO_AUTENTICADO"}), 401
            return redirect(url_for("login"))

        if session.get("id_perfil") != 1:
            if request.path.startswith("/api/"):
                return jsonify({
                    "erro": "Acesso negado: recurso exclusivo de administradores.",
                    "codigo": "PERMISSAO_NEGADA",
                    "pagina_sugerida": "/index.html"
                }), 403
            abort(403, description=(
                f"A área <strong>{request.path}</strong> é restrita a administradores. "
                "Se você precisa acessá-la, solicite permissão ao responsável pelo sistema."
            ))
        return f(*args, **kwargs)
    return decorated_function


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "id_usuario" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"erro": "Não autenticado.", "codigo": "NAO_AUTENTICADO"}), 401
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

def patrimonio_required(f):
    """
    Restrito ao setor de Patrimônio (id_perfil == 1).
    Substitui admin_required nos endpoints de escrita.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "id_usuario" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"erro": "Não autenticado.", "codigo": "NAO_AUTENTICADO"}), 401
            return redirect(url_for("login"))

        if session.get("id_perfil") != PERFIL_PATRIMONIO:
            if request.path.startswith("/api/"):
                return jsonify({
                    "erro": "Acesso negado: exclusivo do setor de Patrimônio.",
                    "codigo": "PERMISSAO_NEGADA",
                }), 403
            abort(403, description=(
                f"A área <strong>{request.path}</strong> é restrita ao <strong>setor de Patrimônio</strong>. "
                "Se você precisa executá-la, solicite ao responsável."
            ))
        return f(*args, **kwargs)
    return decorated_function



# ==========================================
# HANDLERS DE ERRO
# ==========================================
@app.errorhandler(403)
def erro_403(error):
    motivo = getattr(error, "description", None) or "Você não tem permissão para acessar esta área."
    try:
        return render_template("acesso_restrito.html", motivo=motivo, pagina=request.path), 403
    except Exception:
        return f"""
        <!DOCTYPE html><html><head><meta charset="utf-8"><title>Acesso Restrito</title>
        <style>body{{font-family:Poppins,Arial,sans-serif;background:#152937;color:#fff;
        display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:20px;}}
        .box{{background:#fff;color:#152937;padding:40px;border-radius:20px;max-width:520px;text-align:center;
        box-shadow:0 24px 60px rgba(0,0,0,0.3);}}
        h1{{margin-bottom:12px;}} a{{color:#F29310;font-weight:600;text-decoration:none;}}
        </style></head><body><div class="box">
        <div style="font-size:4rem;">🔒</div>
        <h1>Acesso Restrito</h1>
        <p>{motivo}</p>
        <p style="margin-top:24px;"><a href="/index.html">← Voltar ao início</a></p>
        </div></body></html>
        """, 403


@app.errorhandler(404)
def erro_404(error):
    if request.path.startswith("/api/"):
        return jsonify({"erro": "Recurso não encontrado.", "codigo": "NAO_ENCONTRADO"}), 404
    return f"""
    <!DOCTYPE html><html><head><meta charset="utf-8"><title>Não encontrado</title>
    <style>body{{font-family:Poppins,Arial,sans-serif;background:#152937;color:#fff;
    display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:20px;}}
    .box{{background:#fff;color:#152937;padding:40px;border-radius:20px;max-width:520px;text-align:center;
    box-shadow:0 24px 60px rgba(0,0,0,0.3);}}
    h1{{margin-bottom:12px;}} a{{color:#F29310;font-weight:600;text-decoration:none;}}
    </style></head><body><div class="box">
    <div style="font-size:4rem;">🔍</div>
    <h1>Página não encontrada</h1>
    <p>O endereço <code>{request.path}</code> não existe no sistema.</p>
    <p style="margin-top:24px;"><a href="/index.html">← Voltar ao início</a></p>
    </div></body></html>
    """, 404


# ==========================================
# CONSTANTES GLOBAIS
# ==========================================
ORIGEM_PREFIXO = "[ORIGEM:"
ORIGEM_SUFIXO = "]"

ORIGENS_VALIDAS = {
    "PDDE": {"nome": "PDDE Federal", "cor": "#15803d", "icone": "🏛️", "descricao": "Programa Dinheiro Direto na Escola"},
    "CITI": {"nome": "CITI Faetec", "cor": "#1e40af", "icone": "🏫", "descricao": "Centro de Integração e Tecnologia da Informação"},
    "PROPRIO": {"nome": "Recursos Próprios", "cor": "#b45309", "icone": "💰", "descricao": "Verba própria da instituição"},
    "DOACAO": {"nome": "Doação", "cor": "#6b21a8", "icone": "🎁", "descricao": "Doações de terceiros"},
    "CONVENIO": {"nome": "Convênio", "cor": "#0e7490", "icone": "🤝", "descricao": "Recursos de convênios"},
    "OUTRO": {"nome": "Outro", "cor": "#6b7280", "icone": "📋", "descricao": "Outras origens"}
}

CONTRATO_PREFIXO = "[CONTRATO_ATE:"
CONTRATO_SUFIXO = "]"

EXTRA_PREFIXO = "[EXTRA:"
EXTRA_SUFIXO = "]"

FOTOS_ARQUIVO = os.path.join(app.root_path, 'templates', 'uploads', 'patrimonios_fotos.json')
PASTA_FOTOS = os.path.join(app.root_path, 'templates', 'uploads', 'patrimonios')
os.makedirs(PASTA_FOTOS, exist_ok=True)


# ==========================================
# HELPERS GENÉRICOS
# ==========================================
def _extrair_origem_verba(nome):
    if not nome:
        return None, ""
    if ORIGEM_PREFIXO not in nome:
        return None, nome
    try:
        ini = nome.find(ORIGEM_PREFIXO)
        fim = nome.find(ORIGEM_SUFIXO, ini)
        if fim == -1:
            return None, nome
        origem = nome[ini + len(ORIGEM_PREFIXO):fim]
        nome_limpo = (nome[:ini] + nome[fim + 1:]).strip()
        return origem, nome_limpo
    except Exception:
        return None, nome


def _montar_nome_com_origem(nome_original, origem):
    _, limpo = _extrair_origem_verba(nome_original)
    if not origem or origem not in ORIGENS_VALIDAS:
        return limpo
    return f"{ORIGEM_PREFIXO}{origem}{ORIGEM_SUFIXO} {limpo}"


def _extrair_data_fim_contrato(descricao):
    if not descricao:
        return None
    try:
        inicio = descricao.find(CONTRATO_PREFIXO)
        if inicio == -1:
            return None
        fim = descricao.find(CONTRATO_SUFIXO, inicio)
        if fim == -1:
            return None
        return descricao[inicio + len(CONTRATO_PREFIXO):fim]
    except Exception:
        return None


def _montar_descricao_com_contrato(descricao_original, data_fim):
    descricao_limpa = descricao_original or ""
    if CONTRATO_PREFIXO in descricao_limpa:
        ini = descricao_limpa.find(CONTRATO_PREFIXO)
        fim = descricao_limpa.find(CONTRATO_SUFIXO, ini)
        if fim != -1:
            descricao_limpa = descricao_limpa[:ini] + descricao_limpa[fim + 1:]
    descricao_limpa = descricao_limpa.strip()
    if not data_fim:
        return descricao_limpa
    prefixo = f"{CONTRATO_PREFIXO}{data_fim}{CONTRATO_SUFIXO}"
    return f"{prefixo}\n{descricao_limpa}" if descricao_limpa else prefixo


def _ler_fotos_json():
    if not os.path.exists(FOTOS_ARQUIVO):
        return {}
    try:
        with open(FOTOS_ARQUIVO, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _salvar_fotos_json(dados):
    os.makedirs(os.path.dirname(FOTOS_ARQUIVO), exist_ok=True)
    with open(FOTOS_ARQUIVO, 'w', encoding='utf-8') as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


def _extrair_extra_descricao(descricao):
    if not descricao:
        return {}, ""
    if EXTRA_PREFIXO not in descricao:
        return {}, descricao
    try:
        ini = descricao.find(EXTRA_PREFIXO)
        fim = descricao.find(EXTRA_SUFIXO, ini)
        if fim == -1:
            return {}, descricao
        json_str = descricao[ini + len(EXTRA_PREFIXO):fim]
        extra = json.loads(json_str)
        descricao_limpa = (descricao[:ini] + descricao[fim + 1:]).strip()
        return extra, descricao_limpa
    except (json.JSONDecodeError, ValueError):
        return {}, descricao


def _montar_descricao_com_extra(descricao_original, extra_dict):
    _, limpa = _extrair_extra_descricao(descricao_original)
    if not extra_dict:
        return limpa
    extra_limpo = {k: v for k, v in extra_dict.items() if v}
    if not extra_limpo:
        return limpa
    json_str = json.dumps(extra_limpo, ensure_ascii=False)
    prefixo = f"{EXTRA_PREFIXO}{json_str}{EXTRA_SUFIXO}"
    return f"{prefixo}\n{limpa}" if limpa else prefixo

# ==========================================
# HELPERS: múltiplos bens por chamado (sem tabela N:N)
# ==========================================
CHAMADO_BENS_PREFIXO = "[CHAMADO_BENS:"
CHAMADO_BENS_SUFIXO = "]"


def _extrair_bens_chamado(descricao):
    """Retorna (lista_de_bens, descricao_limpa)."""
    if not descricao:
        return [], ""
    if CHAMADO_BENS_PREFIXO not in descricao:
        return [], descricao
    try:
        ini = descricao.find(CHAMADO_BENS_PREFIXO)
        fim = descricao.find(CHAMADO_BENS_SUFIXO, ini)
        if fim == -1:
            return [], descricao
        json_str = descricao[ini + len(CHAMADO_BENS_PREFIXO):fim]
        bens = json.loads(json_str)
        if not isinstance(bens, list):
            return [], descricao
        limpa = (descricao[:ini] + descricao[fim + 1:]).strip()
        return bens, limpa
    except (json.JSONDecodeError, ValueError):
        return [], descricao


def _montar_descricao_com_bens(descricao_original, bens_lista):
    """Serializa a lista de bens na descrição. Se já existia, substitui."""
    _, limpa = _extrair_bens_chamado(descricao_original or "")
    if not bens_lista:
        return limpa
    json_str = json.dumps(bens_lista, ensure_ascii=False)
    prefixo = f"{CHAMADO_BENS_PREFIXO}{json_str}{CHAMADO_BENS_SUFIXO}"
    return f"{prefixo}\n{limpa}" if limpa else prefixo

# ==========================================
# HELPERS DE PAGINAÇÃO
# ==========================================
def _paginar(query_base, params, page, per_page, cursor):
    """
    Calcula APENAS os metadados de paginação (total, página, total_pages).
    NÃO executa a query paginada — a rota faz isso.
    """
    page = max(1, int(page or 1))
    per_page = min(200, max(5, int(per_page or 20)))

    count_sql = f"SELECT COUNT(*) AS total FROM ({query_base}) AS sub"
    cursor.execute(count_sql, params)
    row = cursor.fetchone()
    total = int(row["total"] or 0) if row else 0

    total_pages = max(1, (total + per_page - 1) // per_page)

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
    }
# ==========================================
# CONFIGURAÇÃO DE E-MAIL (SMTP)
# ==========================================
SMTP_CONFIG_FILE = os.path.join(app.root_path, 'smtp_config.json')


def _ler_config_smtp():
    if not os.path.exists(SMTP_CONFIG_FILE):
        return {"servidor": "smtp.gmail.com", "porta": 587, "usuario": "", "senha": "",
                "remetente_nome": "IPE - Sistema de Inventário", "ativo": False}
    try:
        with open(SMTP_CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"servidor": "smtp.gmail.com", "porta": 587, "usuario": "", "senha": "",
                "remetente_nome": "IPE - Sistema de Inventário", "ativo": False}


def _salvar_config_smtp(dados):
    with open(SMTP_CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


MASCARA_SENHA = "••••••••"


def _limpar_senha_smtp(senha):
    return re.sub(r"[\s\u00a0\u200b]+", "", senha or "")


def _enviar_email(destinatarios, assunto, corpo_html, corpo_texto=None):
    config = _ler_config_smtp()
    if not config.get("ativo"):
        return False, "O envio de e-mails está desativado. Configure em Painel ADM → Notificações."
    if not config.get("usuario") or not config.get("senha"):
        return False, "Credenciais SMTP não configuradas."
    config["senha"] = _limpar_senha_smtp(config["senha"])
    config["usuario"] = config["usuario"].strip()
    if not config["senha"].isascii() or not config["usuario"].isascii():
        return False, ("Usuário ou senha SMTP contêm caracteres inválidos. "
                       "Abra Enviar Notificações → Configuração SMTP e digite a senha de app novamente.")
    if isinstance(destinatarios, str):
        destinatarios = [destinatarios]
    if not destinatarios:
        return False, "Nenhum destinatário informado."

    try:
        msg = MIMEMultipart("alternative", policy=SMTP)
        msg["Subject"] = assunto
        nome_remetente = str(config.get("remetente_nome") or "IPE")
        msg["From"] = formataddr((nome_remetente, config["usuario"]))

        emails_puros = []
        for d in destinatarios:
            _, email = parseaddr(d)
            emails_puros.append(email or d)

        # ✅ NOVO: valida se sobrou algum e-mail válido
        emails_puros = [e for e in emails_puros if e and "@" in e]
        if not emails_puros:
            return False, "Nenhum e-mail válido entre os destinatários."

        if corpo_texto:
            msg.attach(MIMEText(corpo_texto, "plain", "utf-8"))
        if corpo_html:
            msg.attach(MIMEText(corpo_html, "html", "utf-8"))

        host = config["servidor"].strip()
        porta = int(config.get("porta") or 587)
        contexto = ssl.create_default_context()

        if porta == 465:
            servidor = smtplib.SMTP_SSL(host, porta, timeout=20, context=contexto)
            servidor.ehlo()
        else:
            servidor = smtplib.SMTP(host, porta, timeout=20)
            servidor.ehlo()
            servidor.starttls(context=contexto)
            servidor.ehlo()

        try:
            servidor.login(config["usuario"], config["senha"])
            servidor.sendmail(config["usuario"], emails_puros, msg.as_bytes(policy=SMTP))
        finally:
            try:
                servidor.quit()
            except Exception:
                pass
        return True, f"E-mail enviado para {len(emails_puros)} destinatário(s)!"
    except smtplib.SMTPAuthenticationError:
        return False, "Falha na autenticação SMTP. Verifique usuário e senha."
    except smtplib.SMTPServerDisconnected:
        return False, "O servidor SMTP encerrou a conexão. Verifique servidor/porta."
    except (socket.timeout, TimeoutError):
        return False, "Tempo esgotado ao conectar no servidor SMTP."
    except (ConnectionError, socket.gaierror, ssl.SSLError) as e:
        return False, f"Falha de conexão/SSL com o servidor SMTP: {str(e)}"
    except smtplib.SMTPException as e:
        return False, f"Erro SMTP: {str(e)}"
    except Exception as e:
        return False, f"Erro ao enviar e-mail: {str(e)}"


# ==========================================
# CLASSES DE SERVIÇO
# ==========================================
class ChamadoService:
    def __init__(self, config):
        self.config = config

    def _get_connection(self):
        return mysql.connector.connect(**self.config)

    def abrir_chamado(self, id_usuario, id_patrimonio, id_tipo_chamado, descricao, prioridade, data_previsao=None):
        conn = None; cursor = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            query = """
                INSERT INTO Chamado (descricao_problema, prioridade, id_usuario, id_patrimonio, id_status, id_tipo_chamado, data_previsao_conclusao, data_abertura)
                VALUES (%s, %s, %s, %s, 1, %s, %s, NOW())
            """
            cursor.execute(query, (descricao, prioridade, id_usuario,
                                   id_patrimonio if id_patrimonio else None,
                                   id_tipo_chamado, data_previsao))
            conn.commit()
            return cursor.lastrowid
        except mysql.connector.Error as err:
            print(f"Erro ao abrir chamado: {err}")
            return False
        finally:
            if cursor: cursor.close()
            if conn: conn.close()

    def atualizar_status(self, id_chamado, id_novo_status):
        conn = self._get_connection(); cursor = conn.cursor()
        try:
            cursor.execute("UPDATE Chamado SET id_status = %s WHERE id_chamado = %s", (id_novo_status, id_chamado))
            conn.commit()
        finally:
            cursor.close(); conn.close()
        self.notificar_mudanca_status(id_chamado, id_novo_status)

    def vincular_item(self, id_chamado, id_patrimonio):
        conn = self._get_connection(); cursor = conn.cursor()
        try:
            cursor.execute("UPDATE Chamado SET id_patrimonio = %s WHERE id_chamado = %s", (id_patrimonio, id_chamado))
            conn.commit()
        finally:
            cursor.close(); conn.close()

    def anexar_foto(self, id_chamado, caminho_arquivo, id_tipo_anexo=1):
        conn = self._get_connection(); cursor = conn.cursor()
        try:
            cursor.execute("""INSERT INTO Anexo (caminho, id_chamado, id_tipo_anexo, data_upload)
                              VALUES (%s, %s, %s, NOW())""", (caminho_arquivo, id_chamado, id_tipo_anexo))
            conn.commit()
        finally:
            cursor.close(); conn.close()

    def notificar_mudanca_status(self, id_chamado, id_novo_status):
        conn = self._get_connection(); cursor = conn.cursor()
        try:
            nome_status = STATUS_CHAMADO.get(int(id_novo_status), f"ID {id_novo_status}")
            mensagem = f"Status do chamado #{id_chamado} alterado para \"{nome_status}\""
            cursor.execute("INSERT INTO Historico (descricao, id_chamado) VALUES (%s, %s)", (mensagem, id_chamado))
            conn.commit()
        finally:
            cursor.close(); conn.close()


class PatrimonioService:
    def __init__(self, config):
        self.config = config
        self._ultimo_erro = None

    def _get_connection(self):
        return mysql.connector.connect(**self.config)

    def calcular_depreciacao(self, valor_compra, data_aquisicao, taxa_depreciacao_anual):
        if not valor_compra or not data_aquisicao or not taxa_depreciacao_anual:
            return float(valor_compra or 0.0)
        try:
            anos_decorridos = (datetime.now() - datetime.strptime(str(data_aquisicao), '%Y-%m-%d')).days / 365.25
            valor_atual = float(valor_compra) * ((1 - (float(taxa_depreciacao_anual) / 100)) ** anos_decorridos)
            return max(round(valor_atual, 2), 0.0)
        except Exception:
            return float(valor_compra or 0.0)

    def cadastrar_patrimonio(self, nome, numero_patrimonio, valor_compra, data_aquisicao, taxa_depreciacao, id_sala, id_categoria=None, id_status=1):
        conn = None
        cursor = None
        self._ultimo_erro = None    # ← reset a cada tentativa
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            if not id_categoria or str(id_categoria).strip() == "":
                cursor.execute("SELECT id_categoria FROM Categoria LIMIT 1")
                res = cursor.fetchone()
                val_categoria = res[0] if res else None
            else:
                val_categoria = int(id_categoria)

            if val_categoria is None:
                self._ultimo_erro = "Nenhuma categoria cadastrada no sistema."
                return False

            val_sala = int(id_sala) if id_sala and str(id_sala).strip() != "" else None
            num_limpo = ''.join(filter(str.isdigit, str(numero_patrimonio)))
            num_val = int(num_limpo) if num_limpo else numero_patrimonio

            cursor.execute("""
                INSERT INTO Patrimonio (nome, numero_patrimonio, valor_atual, data_aquisicao,
                                        taxa_depreciacao, id_sala, id_categoria, id_status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (nome, num_val, float(valor_compra), data_aquisicao,
                  float(taxa_depreciacao), val_sala, val_categoria, int(id_status)))
            conn.commit()
            return True
        except mysql.connector.Error as err:
            print(f"ERRO MYSQL PATRIMONIO: {err}")
            if err.errno == 1062:  # Duplicidade
                self._ultimo_erro = f"Já existe um patrimônio cadastrado com o Nº {numero_patrimonio}."
            else:
                self._ultimo_erro = f"Erro no banco de dados: {err}"
            return False
        finally:
            if cursor: cursor.close()
            if conn: conn.close()


class ManutencaoService:
    def __init__(self, config):
        self.config = config

    def _get_connection(self):
        return mysql.connector.connect(**self.config)

    def estimarCusto(self, id_chamado, custo_estimado, descricao_servico=""):
        conn = None; cursor = None
        try:
            conn = self._get_connection(); cursor = conn.cursor()
            cursor.execute("SELECT id_manutencao FROM Manutencao WHERE id_chamado = %s", (id_chamado,))
            existente = cursor.fetchone()

            if existente:
                cursor.execute("UPDATE Manutencao SET observacao = %s WHERE id_chamado = %s", (descricao_servico, id_chamado))
            else:
                cursor.execute("""INSERT INTO Manutencao (id_chamado, data_inicio, data_fim, observacao, id_tipo_manutencao)
                                  VALUES (%s, CURDATE(), CURDATE(), %s, 1)""", (id_chamado, descricao_servico))

            if float(custo_estimado) > 0:
                cursor.execute("""INSERT INTO verba (nome, descricao, ano_referencia, saldo_inicial, saldo_atual, id_tipo_verba)
                                  VALUES (%s, %s, YEAR(CURDATE()), 0, 0, (SELECT id_tipo_verba FROM tipo_verba LIMIT 1))""",
                               (f"Manutenção #{id_chamado} (estimativa)",
                                f"Estimativa de custo: R$ {float(custo_estimado):.2f} - {descricao_servico[:100]}"))
            conn.commit()
            return True
        except mysql.connector.Error as err:
            print(f"ERRO MANUTENCAO (estimarCusto): {err}")
            return False
        finally:
            if cursor: cursor.close()
            if conn: conn.close()

    def iniciarReparo(self, id_chamado):
        conn = None; cursor = None
        try:
            conn = self._get_connection(); cursor = conn.cursor()
            cursor.execute("UPDATE Manutencao SET data_inicio = NOW() WHERE id_chamado = %s", (id_chamado,))
            cursor.execute("UPDATE Chamado SET id_status = 2 WHERE id_chamado = %s", (id_chamado,))
            conn.commit()
            return True
        except mysql.connector.Error as err:
            print(f"ERRO MANUTENCAO (iniciarReparo): {err}")
            return False
        finally:
            if cursor: cursor.close()
            if conn: conn.close()

    def finalizarReparo(self, id_chamado, custo_final=None):
        conn = None; cursor = None
        try:
            conn = self._get_connection(); cursor = conn.cursor(dictionary=True)
            valor_lancamento = float(custo_final) if custo_final else 0.0
            cursor.execute("UPDATE Manutencao SET data_fim = NOW() WHERE id_chamado = %s", (id_chamado,))
            cursor.execute("UPDATE Chamado SET id_status = 3 WHERE id_chamado = %s", (id_chamado,))
            if valor_lancamento > 0:
                cursor.execute("""INSERT INTO verba (nome, descricao, ano_referencia, saldo_inicial, saldo_atual, id_tipo_verba)
                                  VALUES (%s, %s, YEAR(CURDATE()), 0, 0, (SELECT id_tipo_verba FROM tipo_verba LIMIT 1))""",
                               (f"Manutenção #{id_chamado} (final)",
                                f"Manutenção do Chamado #{id_chamado} - R$ {valor_lancamento:.2f}"))
            conn.commit()
            return True
        except mysql.connector.Error as err:
            print(f"ERRO MANUTENCAO (finalizarReparo): {err}")
            return False
        finally:
            if cursor: cursor.close()
            if conn: conn.close()


chamado_service = ChamadoService(DB_CONFIG)
patrimonio_service = PatrimonioService(DB_CONFIG)
manutencao_service = ManutencaoService(DB_CONFIG)


# ==========================================
# ARQUIVOS ESTÁTICOS
# ==========================================
TEMPLATES_DIR = os.path.join(app.root_path, 'templates')


def _achar_arquivo(pasta, nome_pedido):
    if not os.path.isdir(pasta):
        return None
    base, ext = os.path.splitext(nome_pedido)
    candidatos = [nome_pedido, base + 's' + ext]
    if base.endswith('s'):
        candidatos.append(base[:-1] + ext)
    existentes = os.listdir(pasta)
    for candidato in candidatos:
        for real in existentes:
            if real.lower() == candidato.lower():
                return real
    return None


@app.route('/styles.css')
def css():
    return send_from_directory(TEMPLATES_DIR, 'styles.css')


@app.route('/img/<path:filename>')
def imagens(filename):
    pasta = os.path.join(TEMPLATES_DIR, 'img')
    real = _achar_arquivo(pasta, os.path.basename(filename))
    if not real:
        return f"Imagem '{filename}' nao encontrada", 404
    return send_from_directory(pasta, real)


@app.route('/<path:filename>.js')
def arquivos_js(filename):
    nome = os.path.basename(filename) + '.js'
    real = _achar_arquivo(TEMPLATES_DIR, nome)
    if not real:
        return f"Arquivo '{nome}' nao encontrado", 404
    return send_from_directory(TEMPLATES_DIR, real)


# ==========================================
# ROTAS DE NAVEGAÇÃO
# ==========================================
@app.route("/")
@app.route("/index.html")
def index():
    return render_template("index.html")


@app.route("/inventario.html")
def inventario():
    return render_template("inventario.html")


@app.route("/sobre.html")
def sobre():
    return render_template("sobre.html")


@app.route("/chamados.html")
def chamados_page():
    return render_template("chamados.html")


@app.route("/historico.html")
def historico_page():
    return render_template("historico.html")


@app.route("/novo-chamado.html")
def novo_chamado_page():
    return render_template("novo-chamado.html")


@app.route("/admin.html")
@admin_required
def admin_page():
    return render_template("admin.html")


@app.route("/backup.html")
@admin_required
def backup_page():
    return render_template("backup.html")


@app.route("/alugados.html")
@admin_required
def alugados_page():
    return render_template("alugados.html")


@app.route("/movimentacoes.html")
def movimentacoes_page():
    return render_template("movimentacoes.html")


@app.route("/baixa.html")
@admin_required
def baixa_page():
    return render_template("baixa.html")


@app.route("/reparos.html")
def reparos_page():
    return render_template("reparos.html")


@app.route("/financeiro.html")
@admin_required
def financeiro():
    return render_template("financeiro.html")


@app.route("/relatorios.html")
@patrimonio_required
def relatorios_page():
    return render_template("relatorios.html")

@app.route("/notificacoes-envio.html")
@admin_required
def notificacoes_envio_page():
    return render_template("notificacoes-envio.html")

@app.route("/esqueci-senha", methods=["GET", "POST"])
def esqueci_senha():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()

        if not _validar_email(email):
            flash("E-mail inválido.", "erro")
            return redirect(url_for("esqueci_senha"))

        session_id = session.get("_id", request.remote_addr or "anon")

        # Bloqueio por sessão
        bloqueado, restante = _contar_tentativa_reset(session_id, False)
        if bloqueado and restante > 0:
            flash(f"Muitas solicitações. Tente novamente em {restante} minuto(s).", "erro")
            return redirect(url_for("esqueci_senha"))

        # Limpa tokens vencidos
        _limpar_tokens_expirados()

        # Verifica se o e-mail existe (mas NÃO revela ao usuário)
        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT id_usuario, nome, e_mail FROM Usuario WHERE LOWER(e_mail) = %s", (email,))
            usuario = cursor.fetchone()
        finally:
            if cursor: cursor.close()
            if conn: conn.close()

        # Sempre mostra a mesma mensagem (evita enumeration attack)
        mensagem_padrao = (
            "Se este e-mail estiver cadastrado, enviaremos um link de recuperação. "
            "Verifique sua caixa de entrada e o spam."
        )

        if usuario:
            # Gera token seguro
            token = secrets.token_urlsafe(32)
            _RESET_TOKENS[token] = {
                "id_usuario": usuario["id_usuario"],
                "expira_em": datetime.now() + timedelta(minutes=_RESET_TTL_MIN),
                "email": usuario["e_mail"],
            }

            # Monta o link
            base_url = request.host_url.rstrip("/")
            link = f"{base_url}/reset-senha/{token}"

            # Log no terminal (para TCC, substitui o envio real)
            print("\n" + "=" * 70)
            print(f"🔐 LINK DE RECUPERAÇÃO DE SENHA")
            print(f"   Para: {usuario['nome']} <{usuario['e_mail']}>")
            print(f"   Link: {link}")
            print(f"   Válido por: {_RESET_TTL_MIN} minutos")
            print("=" * 70 + "\n")

            # Tenta enviar por e-mail (usa SMTP já configurado)
            try:
                corpo_html = f"""
                <html><body style="font-family: Arial, sans-serif; background:#f7f7f5; padding:20px;">
                    <div style="max-width:560px; margin:0 auto; background:white; border-radius:12px; overflow:hidden;">
                        <div style="background:linear-gradient(135deg, #FFD730, #F29310); padding:25px; text-align:center;">
                            <h1 style="margin:0; color:#152937;">🔐 IPE</h1>
                        </div>
                        <div style="padding:30px;">
                            <h2 style="color:#152937;">Recuperação de senha</h2>
                            <p>Olá, <strong>{usuario['nome']}</strong>.</p>
                            <p>Recebemos uma solicitação para redefinir a senha da sua conta no IPE.</p>
                            <p style="text-align:center; margin:30px 0;">
                                <a href="{link}" style="
                                    display:inline-block;
                                    background:linear-gradient(135deg, #FFD730, #F29310);
                                    color:#152937; text-decoration:none;
                                    padding:14px 30px; border-radius:10px; font-weight:600;">
                                    🔓 Redefinir minha senha
                                </a>
                            </p>
                            <p style="color:#5b6670; font-size:0.9rem;">
                                Este link é válido por <strong>{_RESET_TTL_MIN} minutos</strong>.
                                Se você não solicitou, ignore este e-mail.
                            </p>
                            <hr style="border:none; border-top:1px solid #e5e7eb; margin:25px 0;">
                            <p style="color:#999; font-size:0.78rem; text-align:center;">
                                Enviado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}
                            </p>
                        </div>
                    </div>
                </body></html>
                """
                corpo_texto = (
                    f"Recuperação de senha — IPE\n\n"
                    f"Olá, {usuario['nome']}.\n\n"
                    f"Acesse o link para redefinir sua senha (válido por {_RESET_TTL_MIN} min):\n"
                    f"{link}\n\n"
                    f"Se você não solicitou, ignore este e-mail."
                )
                _enviar_email(
                    [usuario["e_mail"]],
                    "🔐 Recuperação de senha - IPE",
                    corpo_html,
                    corpo_texto
                )
            except Exception as e:
                print(f"[RESET] Aviso: não foi possível enviar e-mail ({e}). Use o link acima.")

            _contar_tentativa_reset(session_id, True)

        flash(mensagem_padrao, "sucesso")
        return redirect(url_for("login"))

    return render_template("esqueci-senha.html")

@app.route("/reset-senha/<token>", methods=["GET", "POST"])
def reset_senha(token):
    _limpar_tokens_expirados()

    info = _RESET_TOKENS.get(token)
    if not info:
        flash("Link inválido ou expirado. Solicite um novo.", "erro")
        return redirect(url_for("esqueci_senha"))

    # Token expirado (caso a limpeza não tenha rodado)
    if info["expira_em"] < datetime.now():
        del _RESET_TOKENS[token]
        flash("Este link expirou. Solicite um novo.", "erro")
        return redirect(url_for("esqueci_senha"))

    if request.method == "POST":
        nova_senha = request.form.get("nova_senha") or ""
        confirmar = request.form.get("confirmar_senha") or ""

        if len(nova_senha) < 4:
            flash("A senha deve ter pelo menos 4 caracteres.", "erro")
            return redirect(url_for("reset_senha", token=token))

        if nova_senha != confirmar:
            flash("As senhas não coincidem.", "erro")
            return redirect(url_for("reset_senha", token=token))

        # Atualiza no banco
        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            senha_hash = generate_password_hash(nova_senha)
            cursor.execute(
                "UPDATE Usuario SET senha = %s WHERE id_usuario = %s",
                (senha_hash, info["id_usuario"])
            )
            conn.commit()

            # Log de auditoria
            try:
                cursor.execute("""INSERT INTO Log_auditoria (acao, descricao, id_usuario)
                                  VALUES ('UPDATE', %s, %s)""",
                               (f"Senha redefinida via link de recuperação (usuário #{info['id_usuario']})",
                                info["id_usuario"]))
                conn.commit()
            except mysql.connector.Error:
                pass

            # Remove o token (uso único)
            del _RESET_TOKENS[token]

            flash("Senha redefinida com sucesso! Faça login com a nova senha.", "sucesso")
            return redirect(url_for("login"))

        except mysql.connector.Error as err:
            flash(f"Erro ao redefinir: {err}", "erro")
            return redirect(url_for("reset_senha", token=token))
        finally:
            if cursor: cursor.close()
            if conn: conn.close()

    return render_template("reset-senha.html", token=token, email=info["email"])

# ==========================================
# AUTENTICAÇÃO
# ==========================================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        senha = request.form.get("senha") or ""
        admin_check = request.form.get("admin_check")

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM Usuario WHERE LOWER(e_mail) = %s", (email,))
        usuario_logado = cursor.fetchone()
        cursor.close()
        conn.close()

        if usuario_logado:
            senha_banco = (usuario_logado.get("senha") or "").strip()

            senha_valida = False
            if senha_banco.startswith("scrypt:") or senha_banco.startswith("pbkdf2:"):
                senha_valida = check_password_hash(senha_banco, senha)
            else:
                senha_valida = (senha_banco == senha)
                if senha_valida:
                    try:
                        novo_hash = generate_password_hash(senha)
                        conn2 = get_db_connection()
                        cur2 = conn2.cursor()
                        cur2.execute("UPDATE Usuario SET senha = %s WHERE id_usuario = %s",
                                     (novo_hash, usuario_logado['id_usuario']))
                        conn2.commit()
                        cur2.close()
                        conn2.close()
                    except mysql.connector.Error:
                        pass

            if senha_valida:
                session_id = session.get("_id", request.remote_addr or "anon")
                
                # ✅ REGRA DE SEGURANÇA: 
                # Se o usuário é Administrador (perfil 1), a chave é OBRIGATÓRIA.
                # Se o usuário é Padrão (perfil 2), a chave é ignorada.
                exigir_chave = (usuario_logado["id_perfil"] == PERFIL_PATRIMONIO) or admin_check

                if exigir_chave:
                    chave_raw = request.form.get("chave") or ""
                    
                    # Verifica bloqueio por tentativas
                    bloqueado, restante = _registrar_tentativa_chave(session_id, False, "")
                    if bloqueado and restante > 0:
                        flash(f"Muitas tentativas inválidas. Tente novamente em {restante} minuto(s).", "erro")
                        return redirect(url_for("login"))

                    id_perfil_chave, erro = _validar_chave(chave_raw)

                    if erro:
                        bloqueado, restante = _registrar_tentativa_chave(session_id, False, chave_raw)
                        if bloqueado:
                            flash(f"Chave inválida. Conta bloqueada por {restante} minuto(s).", "erro")
                        else:
                            flash(f"{erro} Você tem mais {restante} tentativa(s).", "erro")
                        return redirect(url_for("login"))

                    # Chave válida: confere se o usuário tem o mesmo perfil
                    if usuario_logado["id_perfil"] != id_perfil_chave:
                        nome_esperado = NOMES_PERFIL.get(id_perfil_chave, "Usuário")
                        nome_atual = NOMES_PERFIL.get(usuario_logado["id_perfil"], "Usuário")
                        _registrar_tentativa_chave(session_id, False, chave_raw)
                        flash(
                            f"Chave válida, mas esta conta está registrada como {nome_atual}. "
                            f"A chave fornecida é de {nome_esperado}.",
                            "erro"
                        )
                        return redirect(url_for("login"))

                    _registrar_tentativa_chave(session_id, True, chave_raw, id_perfil_chave)

                # Login efetuado com sucesso
                session['id_usuario'] = usuario_logado['id_usuario']
                session['nome'] = usuario_logado['nome']
                session['id_perfil'] = usuario_logado['id_perfil']
                session.permanent = True
                print(f"[LOGIN] ✅ {email} ({usuario_logado['nome']}) - perfil={usuario_logado['id_perfil']}")
                return redirect(url_for("index"))

            print(f"[LOGIN] ❌ Senha inválida para {email}")
        else:
            print(f"[LOGIN] ❌ Usuário não encontrado: {email}")

        flash("E-mail ou senha incorretos!", "erro")
        return redirect(url_for("login"))
    return render_template("login.html")


@app.route("/cadastro", methods=["GET", "POST"])
def cadastro():
    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        senha = request.form.get("senha") or ""
        confirmar = request.form.get("confirmar_senha") or ""
        admin_check = request.form.get("admin_check")
        id_perfil = PERFIL_USUARIO

        # ---- Validações básicas ----
        if not nome or not email or not senha:
            flash("Preencha todos os campos obrigatórios.", "erro")
            return redirect(url_for("cadastro"))

        if not _validar_email(email):
            flash("E-mail inválido. Use o formato nome@dominio.com", "erro")
            return redirect(url_for("cadastro"))

        if len(senha) < 4:
            flash("A senha deve ter pelo menos 4 caracteres.", "erro")
            return redirect(url_for("cadastro"))

        if senha != confirmar:
            flash("As senhas não coincidem. Digite a mesma senha nos dois campos.", "erro")
            return redirect(url_for("cadastro"))

        # ---- Chave de acesso (se marcou admin) ----
        if admin_check:
            chave_raw = request.form.get("chave") or ""
            session_id = session.get("_id", request.remote_addr or "anon")

            # Verifica bloqueio antes de tudo
            bloqueado, restante = _registrar_tentativa_chave(session_id, False, "")
            if bloqueado and restante > 0:
                flash(f"Muitas tentativas inválidas. Tente novamente em {restante} minuto(s).", "erro")
                return redirect(url_for("cadastro"))

            id_perfil, erro = _validar_chave(chave_raw)

            if erro:
                # Conta a tentativa inválida
                bloqueado, restante = _registrar_tentativa_chave(session_id, False, chave_raw)
                if bloqueado:
                    flash(f"Chave inválida. Conta bloqueada por {restante} minuto(s).", "erro")
                else:
                    flash(f"{erro} Você tem mais {restante} tentativa(s).", "erro")
                return redirect(url_for("cadastro"))

            # Chave válida → registra sucesso
            _registrar_tentativa_chave(session_id, True, chave_raw, id_perfil)
            nome_perfil = NOMES_PERFIL.get(id_perfil, "Usuário")
            flash(f"Chave válida! Conta será criada como {nome_perfil}.", "sucesso")
        else:
            id_perfil = PERFIL_USUARIO

        # ---- Cria a conta ----
        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id_usuario FROM Usuario WHERE e_mail = %s", (email,))
            if cursor.fetchone():
                flash("Este e-mail já está cadastrado. Faça login ou use outro e-mail.", "erro")
                return redirect(url_for("cadastro"))

            senha_hash = generate_password_hash(senha)
            cursor.execute(
                "INSERT INTO Usuario (nome, e_mail, senha, id_perfil) VALUES (%s, %s, %s, %s)",
                (nome, email, senha_hash, id_perfil)
            )
            conn.commit()

            nome_perfil = NOMES_PERFIL.get(id_perfil, "Usuário")
            flash(f"Conta criada com sucesso como {nome_perfil}! Faça login para continuar.", "sucesso")
            return redirect(url_for("login"))

        except mysql.connector.Error as err:
            if err.errno == 1062:
                flash("Este e-mail já está cadastrado. Faça login ou use outro e-mail.", "erro")
            else:
                flash(f"Erro ao cadastrar: {err}", "erro")
            return redirect(url_for("cadastro"))
        finally:
            if cursor: cursor.close()
            if conn: conn.close()

    return render_template("cadastro.html")


@app.route("/perfil.html")
def perfil():
    if 'id_usuario' not in session:
        return redirect(url_for("login"))
    return render_template("perfil.html")


@app.route("/logout")
def logout():
    session.clear()
    # O cache é limpo pelo JS no próximo carregamento
    return redirect(url_for("login"))


@app.route("/atualizar_perfil", methods=["POST"])
def atualizar_perfil():
    if 'id_usuario' not in session:
        return redirect(url_for("login"))

    id_usuario = session['id_usuario']
    nome = (request.form.get("nome") or "").strip()
    email = (request.form.get("email") or "").strip()
    senha = request.form.get("senha") or ""

    if not nome:
        flash("O nome nao pode ficar em branco.", "erro")
        return redirect(url_for("perfil"))
    if not email:
        flash("O e-mail nao pode ficar em branco.", "erro")
        return redirect(url_for("perfil"))
    if not _validar_email(email):
        flash("E-mail inválido.", "erro")
        return redirect(url_for("perfil"))
    if senha and len(senha) < 4:
        flash("A nova senha deve ter pelo menos 4 caracteres.", "erro")
        return redirect(url_for("perfil"))

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id_usuario FROM Usuario WHERE e_mail = %s AND id_usuario <> %s", (email, id_usuario))
        if cursor.fetchone():
            flash("Este e-mail ja esta sendo usado.", "erro")
            return redirect(url_for("perfil"))

        if senha:
            senha_hash = generate_password_hash(senha)
            cursor.execute("UPDATE Usuario SET nome = %s, e_mail = %s, senha = %s WHERE id_usuario = %s",
                           (nome, email, senha_hash, id_usuario))
        else:
            cursor.execute("UPDATE Usuario SET nome = %s, e_mail = %s WHERE id_usuario = %s",
                           (nome, email, id_usuario))
        conn.commit()
        session['nome'] = nome
        flash("Perfil atualizado com sucesso!", "sucesso")
    except mysql.connector.Error:
        conn.rollback()
        flash("Nao foi possivel salvar.", "erro")
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for("perfil"))


# ==========================================
# API - DADOS DO USUÁRIO
# ==========================================
@app.route("/api/dados_usuario")
def api_dados_usuario():
    if 'id_usuario' not in session:
        return jsonify({"erro": "Nao logado"}), 401

    id_usuario = session['id_usuario']
    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id_usuario, nome, e_mail, id_perfil FROM Usuario WHERE id_usuario = %s", (id_usuario,))
    usuario = cursor.fetchone()

    if not usuario:
        cursor.close(); conn.close()
        session.clear()
        return jsonify({"erro": "Usuario nao encontrado"}), 404

    estatisticas = {"total": 0, "abertos": 0, "andamento": 0, "concluidos": 0}
    try:
        cursor.execute("SELECT id_status, COUNT(*) AS qtd FROM Chamado WHERE id_usuario = %s GROUP BY id_status", (id_usuario,))
        for linha in cursor.fetchall():
            qtd = linha['qtd']
            estatisticas['total'] += qtd
            if linha['id_status'] == 1: estatisticas['abertos'] += qtd
            elif linha['id_status'] == 2: estatisticas['andamento'] += qtd
            elif linha['id_status'] == 3: estatisticas['concluidos'] += qtd
    except mysql.connector.Error:
        pass

    cursor.close(); conn.close()
    usuario['estatisticas'] = estatisticas
    usuario['nome_perfil'] = NOMES_PERFIL.get(usuario['id_perfil'], 'Usuário')
    return jsonify(usuario)


# ==========================================
# API - CHAMADOS (Versão 1:1)
# ==========================================

@app.route("/api/patrimonios", methods=["GET"])
def api_listar_patrimonios_select():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        # Busca apenas patrimônios que NÃO foram dados baixa, ordenados por nome
        cursor.execute("""
            SELECT id_patrimonio, nome, numero_patrimonio 
            FROM Patrimonio 
            WHERE processo_baixa IS NULL 
            ORDER BY nome ASC
        """)
        patrimonios = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify(patrimonios)
    except mysql.connector.Error as err:
        return jsonify({"erro": str(err)}), 500

@app.route("/api/chamados", methods=["GET"])
def api_chamados():
    id_usuario = session.get("id_usuario")
    id_perfil = session.get("id_perfil")

    if not id_usuario:
        return jsonify({"erro": "Não autenticado.", "codigo": "NAO_AUTENTICADO"}), 401

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    query = """
        SELECT c.id_chamado,
               DATE_FORMAT(c.data_abertura, '%d/%m/%Y %H:%i') AS data_abertura,
               c.descricao_problema,
               c.prioridade,
               c.id_status,
               IFNULL(u.nome, 'Sistema') AS nome_usuario,
               IFNULL(p.nome, 'Não informado') AS nome_patrimonio,
               p.numero_patrimonio,
               CASE c.id_status
                   WHEN 1 THEN 'Aberto'
                   WHEN 2 THEN 'Em Atendimento'
                   WHEN 3 THEN 'Concluído'
                   WHEN 4 THEN 'Cancelado'
                   ELSE 'Aberto'
               END AS nome_status
        FROM Chamado c
        LEFT JOIN Usuario u ON c.id_usuario = u.id_usuario
        LEFT JOIN Patrimonio p ON c.id_patrimonio = p.id_patrimonio
    """
    params = []
    if id_perfil != 1:
        query += " WHERE c.id_usuario = %s"
        params.append(id_usuario)
    query += " ORDER BY c.id_chamado DESC"

    try:
        cursor.execute(query, params)
        chamados = cursor.fetchall()
        
        for c in chamados:
            # Agora o bem é único, então só montamos a lista com ele
            c["bens"] = [{
                "id": c.get("id_patrimonio"),
                "nome": c.get("nome_patrimonio"),
                "numero": c.get("numero_patrimonio")
            }] if c.get("nome_patrimonio") != "Não informado" else []

        resp = jsonify(chamados)
        resp.headers["Cache-Control"] = "private, max-age=0"
        return resp
    except mysql.connector.Error as err:
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close()
        conn.close()
# ==========================================
# API - TIPOS DE CHAMADO (Restaurada)
# ==========================================
@app.route("/api/tipos-chamado", methods=["GET"])
def api_tipos_chamado():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # Tenta buscar os tipos no banco
        cursor.execute("SELECT id_tipo_chamado, nome FROM Tipo_chamado ORDER BY nome ASC")
        tipos = cursor.fetchall()
        
        # Se a tabela estiver vazia, cria os tipos padrão para não travar a tela
        if not tipos:
            cursor.execute("INSERT INTO Tipo_chamado (nome) VALUES ('Manutenção Corretiva'), ('Manutenção Preventiva'), ('Suporte Técnico')")
            conn.commit()
            cursor.execute("SELECT id_tipo_chamado, nome FROM Tipo_chamado ORDER BY nome ASC")
            tipos = cursor.fetchall()

        return jsonify(tipos)
    except mysql.connector.Error as err:
        # Fallback caso a tabela não exista ou dê erro de SQL
        return jsonify([
            {"id_tipo_chamado": 1, "nome": "Manutenção Corretiva (Padrão)"},
            {"id_tipo_chamado": 2, "nome": "Manutenção Preventiva (Padrão)"},
            {"id_tipo_chamado": 3, "nome": "Suporte Técnico (Padrão)"}
        ])
    finally:
        cursor.close()
        conn.close()
        
@app.route("/api/novo-chamado", methods=["POST"])
@app.route("/api/chamado/cadastrar", methods=["POST"])
def api_cadastrar_chamado():
    if 'id_usuario' not in session:
        return jsonify({"erro": "Sessão expirada."}), 401

    id_usuario = session['id_usuario']
    id_tipo_chamado = request.form.get("id_tipo_chamado")
    prioridade = request.form.get("prioridade", "Media")
    descricao_problema = (request.form.get("descricao_problema") or "").strip()
    data_previsao = request.form.get("data_previsao_conclusao") or None
    id_patrimonio = request.form.get("id_patrimonio")

    if not id_tipo_chamado:
        return jsonify({"erro": "Selecione um Tipo de Chamado válido."}), 400
    if not descricao_problema:
        return jsonify({"erro": "Descreva o problema antes de enviar."}), 400
    if prioridade not in PRIORIDADES_VALIDAS:
        return jsonify({"erro": "Prioridade inválida."}), 400
    if not id_patrimonio:
        return jsonify({"erro": "Selecione um patrimônio."}), 400

    conn = None; cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Verifica se o patrimônio existe
        cursor.execute("SELECT id_patrimonio FROM Patrimonio WHERE id_patrimonio = %s", (id_patrimonio,))
        if not cursor.fetchone():
            return jsonify({"erro": "Patrimônio não encontrado."}), 400

        # Insere o chamado limpo
        cursor.execute("""
            INSERT INTO Chamado (descricao_problema, prioridade, id_usuario, id_patrimonio,
                                 id_status, id_tipo_chamado, data_previsao_conclusao, data_abertura)
            VALUES (%s, %s, %s, %s, 1, %s, %s, NOW())
        """, (descricao_problema, prioridade, id_usuario, id_patrimonio,
              id_tipo_chamado, data_previsao))

        id_chamado_criado = cursor.lastrowid

        # Anexo (opcional)
        if 'anexo' in request.files:
            file = request.files['anexo']
            if file.filename != '':
                os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                nome_seguro = secure_filename(file.filename)
                caminho_salvar = os.path.join(app.config['UPLOAD_FOLDER'], nome_seguro)
                caminho_relativo = f"uploads/{nome_seguro}"
                file.save(caminho_salvar)
                cursor.execute(
                    "INSERT INTO Anexo (caminho, id_chamado, id_tipo_anexo, data_upload) VALUES (%s, %s, 1, NOW())",
                    (caminho_relativo, id_chamado_criado)
                )

        conn.commit()
        return jsonify({
            "mensagem": f"Chamado #{id_chamado_criado} cadastrado com sucesso!",
            "id_chamado": id_chamado_criado
        }), 201
    except mysql.connector.Error as err:
        if conn: conn.rollback()
        return jsonify({"erro": f"Erro ao gravar chamado: {err}"}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()



@app.route("/api/chamado/atualizar-status", methods=["POST"])
@admin_required
def api_atualizar_status():
    id_chamado = request.form.get("id_chamado")
    id_status = request.form.get("id_status")
    if not id_chamado:
        return jsonify({"erro": "Chamado não informado."}), 400
    try:
        id_status_int = int(id_status)
    except (TypeError, ValueError):
        return jsonify({"erro": "Status inválido."}), 400
    if id_status_int not in STATUS_CHAMADO:
        return jsonify({"erro": "Status inválido."}), 400
    chamado_service.atualizar_status(id_chamado, id_status_int)
    return jsonify({"sucesso": True, "mensagem": f"Status atualizado para \"{STATUS_CHAMADO[id_status_int]}\"!"})


@app.route("/api/chamado/anexar-foto", methods=["POST"])
def api_anexar_foto():
    id_chamado = request.form.get("id_chamado")
    if not id_chamado:
        return jsonify({"erro": "Chamado não informado."}), 400
    if 'foto' not in request.files:
        return jsonify({"erro": "Nenhum arquivo enviado"}), 400
    foto = request.files['foto']
    if foto.filename == '':
        return jsonify({"erro": "Arquivo vazio"}), 400

    ext = os.path.splitext(foto.filename)[1].lower()
    if ext not in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
        return jsonify({"erro": "Formato não aceito (use JPG, PNG, GIF ou WEBP)."}), 400

    if not _validar_imagem_real(foto.stream):
        return jsonify({"erro": "Arquivo não é uma imagem válida."}), 400
    foto.seek(0)

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    nome_seguro = secure_filename(foto.filename)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    nome_final = f"chamado_{id_chamado}_{timestamp}_{nome_seguro}"
    caminho_salvar = os.path.join(app.config['UPLOAD_FOLDER'], nome_final)
    caminho_relativo = f"uploads/{nome_final}"
    foto.save(caminho_salvar)
    chamado_service.anexar_foto(id_chamado, caminho_relativo, id_tipo_anexo=1)
    return jsonify({"sucesso": True, "caminho": caminho_relativo})

# ==========================================
# CHAMADOS — AÇÕES COMPLEMENTARES
# ==========================================

@app.route("/api/chamado/<int:id_chamado>", methods=["DELETE"])
@admin_required
def api_chamado_excluir(id_chamado):
    """Exclui um chamado definitivamente. Só ADM. Bloqueia se houver manutenção em andamento."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id_chamado, descricao_problema, id_status FROM Chamado WHERE id_chamado = %s",
                       (id_chamado,))
        ch = cursor.fetchone()
        if not ch:
            return jsonify({"erro": "Chamado não encontrado."}), 404

        if ch["id_status"] == 2:
            return jsonify({"erro": "Não é possível excluir um chamado em atendimento. Conclua ou cancele antes."}), 400

        # Apaga dependências (ordem importa por causa das FKs)
        cursor.execute("DELETE FROM Anexo WHERE id_chamado = %s", (id_chamado,))
        cursor.execute("DELETE FROM Historico WHERE id_chamado = %s", (id_chamado,))
        cursor.execute("DELETE FROM Manutencao WHERE id_chamado = %s", (id_chamado,))
        cursor.execute("DELETE FROM Chamado WHERE id_chamado = %s", (id_chamado,))

        cursor.execute("""INSERT INTO Log_auditoria (acao, descricao, id_usuario)
                          VALUES ('DELETE', %s, %s)""",
                       (f"Chamado #{id_chamado} excluído", session['id_usuario']))
        conn.commit()
        return jsonify({"sucesso": True, "mensagem": f"Chamado #{id_chamado} excluído."})
    except mysql.connector.Error as err:
        conn.rollback()
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close(); conn.close()


@app.route("/api/chamado/<int:id_chamado>/cancelar", methods=["POST"])
@admin_required
def api_chamado_cancelar(id_chamado):
    """Cancela com motivo obrigatório. Grava no histórico."""
    motivo = (request.form.get("motivo") or "").strip()
    if not motivo or len(motivo) < 5:
        return jsonify({"erro": "Informe o motivo (mín. 5 caracteres)."}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id_status FROM Chamado WHERE id_chamado = %s", (id_chamado,))
        ch = cursor.fetchone()
        if not ch:
            return jsonify({"erro": "Chamado não encontrado."}), 404
        if ch["id_status"] == 3:
            return jsonify({"erro": "Chamado já concluído não pode ser cancelado."}), 400
        if ch["id_status"] == 4:
            return jsonify({"erro": "Chamado já está cancelado."}), 400

        cursor.execute("UPDATE Chamado SET id_status = 4 WHERE id_chamado = %s", (id_chamado,))
        cursor.execute("""INSERT INTO Historico (descricao, id_chamado)
                          VALUES (%s, %s)""",
                       (f'Status do chamado alterado para "Cancelado". Motivo: {motivo}', id_chamado))
        cursor.execute("""INSERT INTO Log_auditoria (acao, descricao, id_usuario)
                          VALUES ('UPDATE', %s, %s)""",
                       (f"Chamado #{id_chamado} cancelado: {motivo[:80]}", session['id_usuario']))
        conn.commit()
        return jsonify({"sucesso": True, "mensagem": "Chamado cancelado."})
    except mysql.connector.Error as err:
        conn.rollback()
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close(); conn.close()


@app.route("/api/chamado/<int:id_chamado>/reabrir", methods=["POST"])
@admin_required
def api_chamado_reabrir(id_chamado):
    """Reabre um chamado concluído ou cancelado (volta para status 1)."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id_status FROM Chamado WHERE id_chamado = %s", (id_chamado,))
        ch = cursor.fetchone()
        if not ch:
            return jsonify({"erro": "Chamado não encontrado."}), 404
        if ch["id_status"] in (1, 2):
            return jsonify({"erro": "Chamado já está aberto/em atendimento."}), 400

        cursor.execute("UPDATE Chamado SET id_status = 1 WHERE id_chamado = %s", (id_chamado,))
        cursor.execute("""INSERT INTO Historico (descricao, id_chamado)
                          VALUES (%s, %s)""",
                       ('Status do chamado alterado para "Aberto" (reaberto)', id_chamado))
        cursor.execute("""INSERT INTO Log_auditoria (acao, descricao, id_usuario)
                          VALUES ('UPDATE', %s, %s)""",
                       (f"Chamado #{id_chamado} reaberto", session['id_usuario']))
        conn.commit()
        return jsonify({"sucesso": True, "mensagem": "Chamado reaberto."})
    except mysql.connector.Error as err:
        conn.rollback()
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close(); conn.close()


@app.route("/api/chamado/<int:id_chamado>/prioridade", methods=["POST"])
@admin_required
def api_chamado_prioridade(id_chamado):
    """Altera a prioridade de um chamado."""
    nova = (request.form.get("prioridade") or "").strip()
    if nova not in PRIORIDADES_VALIDAS:
        return jsonify({"erro": f"Prioridade inválida. Use {', '.join(PRIORIDADES_VALIDAS)}."}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id_chamado FROM Chamado WHERE id_chamado = %s", (id_chamado,))
        if not cursor.fetchone():
            return jsonify({"erro": "Chamado não encontrado."}), 404
        cursor.execute("UPDATE Chamado SET prioridade = %s WHERE id_chamado = %s", (nova, id_chamado))
        cursor.execute("""INSERT INTO Historico (descricao, id_chamado)
                          VALUES (%s, %s)""",
                       (f'Prioridade alterada para "{nova}"', id_chamado))
        conn.commit()
        return jsonify({"sucesso": True, "mensagem": f"Prioridade atualizada para {nova}."})
    except mysql.connector.Error as err:
        conn.rollback()
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close(); conn.close()

@app.route("/api/chamado/<int:id_chamado>/historico", methods=["GET"])
def api_historico_chamado(id_chamado):
    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    cursor.execute("""SELECT id_historico, descricao, DATE_FORMAT(data_evento, '%d/%m/%Y %H:%i') AS data_evento
                      FROM Historico WHERE id_chamado = %s ORDER BY id_historico DESC""", (id_chamado,))
    historico = cursor.fetchall()
    cursor.close(); conn.close()
    return jsonify(historico)


@app.route("/api/historico", methods=["GET"])
def api_historico_geral():
    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT h.id_historico,
               DATE_FORMAT(h.data_evento, '%d/%m/%Y %H:%i') AS data_evento,
               DATE_FORMAT(h.data_evento, '%Y-%m-%d') AS data_evento_iso,
               h.descricao, h.id_chamado, c.descricao_problema, c.prioridade,
               IFNULL(u.nome, 'Sistema') AS nome_usuario
        FROM Historico h
        LEFT JOIN Chamado c ON h.id_chamado = c.id_chamado
        LEFT JOIN Usuario u ON c.id_usuario = u.id_usuario
        ORDER BY h.id_historico DESC
    """)
    historico = cursor.fetchall()
    cursor.close(); conn.close()
    return jsonify(historico)


@app.route("/api/chamado/<int:id_chamado>/anexos", methods=["GET"])
def api_anexos_chamado(id_chamado):
    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    cursor.execute("""SELECT id_anexo, caminho, DATE_FORMAT(data_upload, '%d/%m/%Y %H:%i') AS data_upload
                      FROM Anexo WHERE id_chamado = %s ORDER BY id_anexo DESC""", (id_chamado,))
    anexos = cursor.fetchall()
    cursor.close(); conn.close()
    return jsonify(anexos)

@app.route("/api/chamado/<int:id_chamado>/detalhes", methods=["GET"])
def api_chamado_detalhes(id_chamado):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT c.id_chamado,
                   DATE_FORMAT(c.data_abertura, '%d/%m/%Y %H:%i') AS data_abertura,
                   DATE_FORMAT(c.data_abertura, '%Y-%m-%d') AS data_abertura_iso,
                   c.descricao_problema, c.prioridade, c.id_status,
                   c.id_patrimonio,
                   IFNULL(u.nome, 'Sistema') AS nome_usuario,
                   IFNULL(tc.nome, '—') AS tipo_chamado,
                   c.data_previsao_conclusao,
                   DATE_FORMAT(c.data_previsao_conclusao, '%d/%m/%Y') AS data_previsao_fmt,
                   IFNULL(p.nome, NULL) AS nome_patrimonio_principal,
                   p.numero_patrimonio AS numero_patrimonio_principal
            FROM Chamado c
            LEFT JOIN Usuario u ON c.id_usuario = u.id_usuario
            LEFT JOIN Tipo_chamado tc ON c.id_tipo_chamado = tc.id_tipo_chamado
            LEFT JOIN Patrimonio p ON c.id_patrimonio = p.id_patrimonio
            WHERE c.id_chamado = %s
        """, (id_chamado,))
        chamado = cursor.fetchone()
        if not chamado:
            return jsonify({"erro": "Chamado não encontrado."}), 404

        cursor.execute("""
            SELECT m.id_manutencao,
                   DATE_FORMAT(m.data_inicio, '%d/%m/%Y') AS data_inicio_manutencao,
                   DATE_FORMAT(m.data_fim, '%d/%m/%Y') AS data_fim_manutencao,
                   m.observacao AS observacao_manutencao,
                   DATEDIFF(m.data_fim, m.data_inicio) AS duracao_dias
            FROM Manutencao m WHERE m.id_chamado = %s LIMIT 1
        """, (id_chamado,))
        chamado["manutencao"] = cursor.fetchone()

        # ✅ Limpa a string suja do banco de dados
        bens_extras, desc_limpa = _extrair_bens_chamado(chamado.get("descricao_problema") or "")
        chamado["descricao_problema"] = desc_limpa.strip() # Remove espaços vazios

        bens_lista = []
        if chamado.get("id_patrimonio") and chamado.get("nome_patrimonio_principal"):
            bens_lista.append({
                "id": chamado["id_patrimonio"],
                "nome": chamado["nome_patrimonio_principal"],
                "numero": chamado["numero_patrimonio_principal"],
            })
        for b in bens_extras:
            if not any(x["id"] == b.get("id") for x in bens_lista):
                bens_lista.append(b)

        chamado["bens"] = bens_lista
        
        chamado.pop("nome_patrimonio_principal", None)
        chamado.pop("numero_patrimonio_principal", None)

        cursor.execute("""
            SELECT id_historico, descricao,
                   DATE_FORMAT(data_evento, '%d/%m/%Y %H:%i') AS data_evento,
                   DATE_FORMAT(data_evento, '%Y-%m-%d') AS data_evento_iso
            FROM Historico WHERE id_chamado = %s ORDER BY id_historico ASC
        """, (id_chamado,))
        chamado["historico"] = cursor.fetchall()

        cursor.execute("""
            SELECT id_anexo, caminho,
                   DATE_FORMAT(data_upload, '%d/%m/%Y %H:%i') AS data_upload
            FROM Anexo WHERE id_chamado = %s ORDER BY id_anexo ASC
        """, (id_chamado,))
        chamado["anexos"] = cursor.fetchall()

        return jsonify(chamado)
    except mysql.connector.Error as err:
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close()
        conn.close()
        
@app.route('/uploads/<path:filename>')
def download_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


# ==========================================
# API - SALAS E INVENTÁRIO
# ==========================================
@app.route("/api/salas", methods=["GET", "POST"])
def api_salas():
    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    if request.method == "POST":
        if session.get("id_perfil") != 1:
            cursor.close(); conn.close()
            return jsonify({"erro": "Acesso negado.", "codigo": "PERMISSAO_NEGADA"}), 403
        nome_sala = request.form.get("nome")
        bloco = request.form.get("bloco")
        id_tipo_sala = request.form.get("id_tipo_sala", 1)
        cursor.execute("INSERT INTO Sala (numero_sala, bloco, id_tipo_sala) VALUES (%s, %s, %s)",
                       (nome_sala, bloco, id_tipo_sala))
        conn.commit()
        cursor.close(); conn.close()
        return jsonify({"sucesso": True, "mensagem": "Sala cadastrada com sucesso!"})

    cursor.execute("SELECT id_sala, numero_sala AS nome, bloco FROM Sala ORDER BY numero_sala ASC")
    salas = cursor.fetchall()
    cursor.close(); conn.close()
    return jsonify(salas)


@app.route("/api/inventario/listar", methods=["GET"])
def api_listar_inventario():
    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT p.id_patrimonio, p.nome, p.numero_patrimonio,
               p.valor_atual AS valor_compra,
               DATE_FORMAT(p.data_aquisicao, '%Y-%m-%d') AS data_aquisicao,
               DATE_FORMAT(p.data_aquisicao, '%d/%m/%Y') AS data_aquisicao_formatada,
               p.taxa_depreciacao, p.processo_baixa,
               IFNULL(s.numero_sala, 'Não Alocado') AS nome_sala,
               s.bloco AS bloco_sala,
               IFNULL(st.nome, 'Ativo') AS nome_status
        FROM Patrimonio p
        LEFT JOIN Sala s ON p.id_sala = s.id_sala
        LEFT JOIN _status st ON p.id_status = st.id_status
        ORDER BY p.id_patrimonio DESC
    """)
    bens = cursor.fetchall()
    for bem in bens:
        bem['valor_atual'] = patrimonio_service.calcular_depreciacao(
            bem['valor_compra'], bem['data_aquisicao'], bem['taxa_depreciacao'])
    cursor.close(); conn.close()
    return jsonify(bens)


@app.route("/api/inventario/filtros", methods=["GET"])
def api_inventario_filtros():
    """Opções dos filtros do inventário (categorias, salas e status)."""
    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id_categoria, nome FROM Categoria ORDER BY nome ASC")
        db_cats = cursor.fetchall() or []
        por_nome = {c["nome"]: c["id_categoria"] for c in db_cats}

        # Categorias CGE (Portaria 195/2016): usa o id real se já existir no banco,
        # senão envia "cge::<nome>" (buscar e cadastrar já sabem resolver esse prefixo).
        categorias, usados = [], set()
        for nome in CATEGORIAS_CGE:
            if nome in por_nome:
                categorias.append({"id_categoria": por_nome[nome], "nome": nome})
                usados.add(nome)
            else:
                categorias.append({"id_categoria": f"cge::{nome}", "nome": nome})
        for c in db_cats:
            if c["nome"] not in usados:
                categorias.append({"id_categoria": c["id_categoria"], "nome": c["nome"]})
        categorias.sort(key=lambda c: c["nome"])

        cursor.execute("SELECT id_sala, numero_sala AS nome, bloco FROM Sala ORDER BY bloco ASC, numero_sala ASC")
        salas = cursor.fetchall() or []

        cursor.execute("SELECT id_status, nome FROM _status ORDER BY id_status ASC")
        status = cursor.fetchall() or []

        return jsonify({"categorias": categorias, "salas": salas, "status": status})
    except mysql.connector.Error as err:
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close(); conn.close()


@app.route("/api/inventario/cadastrar", methods=["POST"])
@admin_required
def api_cadastrar_inventario():
    nome = request.form.get("nome")
    numero_patrimonio = request.form.get("numero_patrimonio")
    valor_compra = request.form.get("valor_compra")
    data_aquisicao = request.form.get("data_aquisicao")
    taxa_depreciacao = request.form.get("taxa_depreciacao", 10.0)
    id_sala = request.form.get("id_sala")
    id_categoria = request.form.get("id_categoria", 1)

    # Resolve categoria CGE
    if isinstance(id_categoria, str) and id_categoria.startswith("cge::"):
        nome_cge = id_categoria.replace("cge::", "", 1)
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT id_categoria FROM Categoria WHERE nome = %s LIMIT 1", (nome_cge,))
            row = cursor.fetchone()
            if row:
                id_categoria = row["id_categoria"]
            else:
                cursor.execute(
                    "INSERT INTO Categoria (nome, descricao) VALUES (%s, %s)",
                    (nome_cge, "Classificação CGE - Portaria 195/2016")
                )
                conn.commit()
                id_categoria = cursor.lastrowid
        finally:
            cursor.close()
            conn.close()

    sucesso = patrimonio_service.cadastrar_patrimonio(
        nome, numero_patrimonio, valor_compra, data_aquisicao,
        taxa_depreciacao, id_sala, id_categoria
    )

    # Detecta se é chamada AJAX (fetch) ou form tradicional
    quer_json = (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in (request.headers.get("Accept") or "")
        or request.form.get("_ajax") == "1"
    )

    # ---------- SUCESSO ----------
    if sucesso:
        if quer_json:
            return jsonify({
                "sucesso": True,
                "mensagem": f'Patrimônio "{nome}" cadastrado com sucesso!'
            })
        flash(f'Patrimônio "{nome}" cadastrado com sucesso!', "sucesso")
        return redirect("/inventario.html")

    # ---------- ERRO (1062, validação, etc.) ----------
    mensagem_erro = patrimonio_service._ultimo_erro or "Erro ao salvar patrimônio."

    if quer_json:
        status_code = 409 if "já existe" in mensagem_erro.lower() else 400
        return jsonify({"erro": mensagem_erro}), status_code

    flash(mensagem_erro, "erro")
    return redirect("/inventario.html")



# ==========================================
# API - FINANCEIRO
# ==========================================
@app.route("/api/financeiro/resumo", methods=["GET"])
@admin_required
def api_financeiro_resumo():
    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    resumo = {"total_entradas": 0.0, "total_saidas": 0.0, "saldo_atual": 0.0,
              "total_movimentacoes": 0, "saldo_bloqueado": 0.0}
    try:
        cursor.execute("SELECT IFNULL(SUM(valor), 0) AS total FROM Lancamento_caixa WHERE tipo_movimento = 'Receita'")
        resumo["total_entradas"] = float(cursor.fetchone()["total"] or 0)
        cursor.execute("SELECT IFNULL(SUM(valor), 0) AS total FROM Lancamento_caixa WHERE tipo_movimento = 'Despesa'")
        resumo["total_saidas"] = float(cursor.fetchone()["total"] or 0)
        cursor.execute("SELECT COUNT(*) AS total FROM Lancamento_caixa")
        resumo["total_movimentacoes"] = int(cursor.fetchone()["total"] or 0)
        cursor.execute("SELECT IFNULL(SUM(saldo_bloqueado), 0) AS total FROM Verba")
        resumo["saldo_bloqueado"] = float(cursor.fetchone()["total"] or 0)
        resumo["saldo_atual"] = round(resumo["total_entradas"] - resumo["total_saidas"], 2)
    except mysql.connector.Error as err:
        print(f"ERRO resumo financeiro: {err}")
    finally:
        cursor.close(); conn.close()
    return jsonify(resumo)


@app.route("/api/financeiro/movimentacoes", methods=["GET"])
@admin_required
def api_financeiro_movimentacoes():
    tipo = request.args.get("tipo", "").strip()
    categoria = request.args.get("categoria", "").strip()
    origem_filtro = request.args.get("origem", "").strip()
    busca = request.args.get("busca", "").strip()
    data_ini = request.args.get("data_ini", "").strip()
    data_fim = request.args.get("data_fim", "").strip()
    limite = request.args.get("limite", 200, type=int)

    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    query = """
        SELECT lc.id_lancamento,
               DATE_FORMAT(lc.data_lancamento, '%d/%m/%Y %H:%i') AS data_formatada,
               DATE_FORMAT(lc.data_lancamento, '%Y-%m-%d') AS data_iso,
               lc.tipo_movimento, lc.descricao, lc.valor, lc.forma_pagamento,
               lc.numero_documento, lc.bimestre,
               d.categoria AS categoria_despesa, d.aprovacao, d.id_verba,
               v.nome AS verba_nome,
               CASE WHEN d.aprovacao = 1 THEN 'Aprovado'
                    WHEN d.aprovacao = 0 THEN 'Pendente'
                    ELSE NULL END AS status_despesa
        FROM Lancamento_caixa lc
        LEFT JOIN Despesa d ON d.id_lancamento = lc.id_lancamento
        LEFT JOIN verba v ON v.id_verba = d.id_verba
        WHERE 1=1
    """
    params = []
    if tipo in ("Receita", "Despesa"):
        query += " AND lc.tipo_movimento = %s"; params.append(tipo)
    if categoria:
        query += " AND (d.categoria = %s OR lc.descricao LIKE %s)"
        params.append(categoria); params.append(f"%{categoria}%")
    if busca:
        query += " AND (lc.descricao LIKE %s OR lc.numero_documento LIKE %s)"
        params.append(f"%{busca}%"); params.append(f"%{busca}%")
    if data_ini:
        query += " AND DATE(lc.data_lancamento) >= %s"; params.append(data_ini)
    if data_fim:
        query += " AND DATE(lc.data_lancamento) <= %s"; params.append(data_fim)
    query += " ORDER BY lc.data_lancamento DESC, lc.id_lancamento DESC LIMIT %s"
    params.append(limite)

    try:
        cursor.execute(query, params)
        movs = cursor.fetchall()
        for m in movs:
            m["status"] = (m.get("status_despesa") or "Pendente") if m["tipo_movimento"] == "Despesa" else "Recebido"
            m["valor"] = float(m["valor"])
            origem, _ = _extrair_origem_verba(m.get("verba_nome") or "")
            m["origem"] = origem
            m["origem_nome"] = ORIGENS_VALIDAS.get(origem, {}).get("nome") if origem else None
            m["origem_cor"] = ORIGENS_VALIDAS.get(origem, {}).get("cor") if origem else None
            m["origem_icone"] = ORIGENS_VALIDAS.get(origem, {}).get("icone") if origem else None
        if origem_filtro:
            if origem_filtro == "SEM_ORIGEM":
                movs = [m for m in movs if not m["origem"]]
            else:
                movs = [m for m in movs if m["origem"] == origem_filtro]
        return jsonify(movs)
    except mysql.connector.Error as err:
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close(); conn.close()


@app.route("/api/financeiro/movimentacoes", methods=["POST"])
@admin_required
def api_financeiro_criar_movimentacao():
    tipo = (request.form.get("tipo_movimento") or "").strip()
    descricao = (request.form.get("descricao") or "").strip()
    valor_raw = (request.form.get("valor") or "0").replace(",", ".")
    categoria = (request.form.get("categoria") or "").strip()
    forma_pagamento = (request.form.get("forma_pagamento") or "Pix").strip()
    numero_documento = (request.form.get("numero_documento") or "").strip()
    aprovacao = request.form.get("aprovacao")
    id_verba = request.form.get("id_verba") or None
    origem_verba = (request.form.get("origem_verba") or "").strip()

    if tipo not in ("Receita", "Despesa"):
        return jsonify({"erro": "Tipo de movimentação inválido."}), 400
    if not descricao:
        return jsonify({"erro": "Informe uma descrição."}), 400
    try:
        valor = float(valor_raw)
        if valor <= 0: raise ValueError()
    except ValueError:
        return jsonify({"erro": "Valor inválido."}), 400
    if forma_pagamento not in ("Dinheiro", "Cartao", "Pix", "Transferencia"):
        forma_pagamento = "Pix"
    if origem_verba and origem_verba not in ORIGENS_VALIDAS:
        return jsonify({"erro": "Origem da verba inválida."}), 400

    conn = get_db_connection(); cursor = conn.cursor()
    try:
        bimestre = (datetime.now().month - 1) // 2 + 1
        cursor.execute("""INSERT INTO Formulario_caixa (data_servico, forma_pagamento, objeto_servico, periodo_referencia, status, bimestre_referencia)
                          VALUES (CURDATE(), %s, %s, 'Mensal', 'Aberto', %s)""",
                       (forma_pagamento, descricao, bimestre))
        id_formulario = cursor.lastrowid

        cursor.execute("""INSERT INTO Lancamento_caixa (data_lancamento, tipo_movimento, descricao, valor, forma_pagamento, numero_documento, id_formulario)
                          VALUES (NOW(), %s, %s, %s, %s, %s, %s)""",
                       (tipo, descricao, valor, forma_pagamento, numero_documento or None, id_formulario))
        id_lancamento = cursor.lastrowid

        if not id_verba and origem_verba:
            nome_verba = _montar_nome_com_origem(descricao[:100], origem_verba)
            cursor.execute("""INSERT INTO verba (nome, descricao, ano_referencia, saldo_inicial, saldo_atual, id_tipo_verba)
                              VALUES (%s, %s, YEAR(CURDATE()), %s, %s, (SELECT id_tipo_verba FROM tipo_verba LIMIT 1))""",
                           (nome_verba, f"{tipo} - {descricao}", valor, valor))
            id_verba = cursor.lastrowid

        if tipo == "Despesa":
            aprovado = 1 if aprovacao == "1" else 0
            cursor.execute("""INSERT INTO Despesa (id_despesa, aprovacao, valor, categoria, id_lancamento, id_verba)
                              VALUES (%s, %s, %s, %s, %s, %s)""",
                           (id_lancamento, aprovado, valor, categoria or None, id_lancamento, id_verba))
        else:
            cursor.execute("""INSERT INTO Receita (id_receita, data_geracao, periodo, id_lancamento)
                              VALUES (%s, NOW(), 'Mensal', %s)""", (id_lancamento, id_lancamento))

        origem_nome = ORIGENS_VALIDAS.get(origem_verba, {}).get("nome", "Não informada")
        cursor.execute("""INSERT INTO Log_auditoria (acao, descricao, id_usuario)
                          VALUES ('INSERT', %s, %s)""",
                       (f"{tipo} cadastrada ({origem_nome}): {descricao[:80]} (R$ {valor:.2f})", session['id_usuario']))
        conn.commit()
        return jsonify({"sucesso": True, "mensagem": f"{tipo} de R$ {valor:.2f} registrada!", "id_lancamento": id_lancamento}), 201
    except mysql.connector.Error as err:
        conn.rollback()
        return jsonify({"erro": f"Erro no banco: {err}"}), 500
    finally:
        cursor.close(); conn.close()


@app.route("/api/financeiro/movimentacoes/<int:id_lancamento>", methods=["PUT", "POST"])
@admin_required
def api_financeiro_editar_movimentacao(id_lancamento):
    descricao = (request.form.get("descricao") or "").strip()
    valor_raw = (request.form.get("valor") or "0").replace(",", ".")
    categoria = (request.form.get("categoria") or "").strip()
    forma_pagamento = (request.form.get("forma_pagamento") or "").strip()
    numero_documento = (request.form.get("numero_documento") or "").strip()

    if not descricao:
        return jsonify({"erro": "Descrição obrigatória."}), 400
    try:
        valor = float(valor_raw)
        if valor <= 0: raise ValueError()
    except ValueError:
        return jsonify({"erro": "Valor inválido."}), 400

    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT tipo_movimento FROM Lancamento_caixa WHERE id_lancamento = %s", (id_lancamento,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"erro": "Movimentação não encontrada."}), 404
        cursor.execute("""UPDATE Lancamento_caixa SET descricao = %s, valor = %s, forma_pagamento = %s, numero_documento = %s
                          WHERE id_lancamento = %s""",
                       (descricao, valor, forma_pagamento or None, numero_documento or None, id_lancamento))
        if row["tipo_movimento"] == "Despesa":
            cursor.execute("UPDATE Despesa SET valor = %s, categoria = %s WHERE id_lancamento = %s",
                           (valor, categoria or None, id_lancamento))
        cursor.execute("""INSERT INTO Log_auditoria (acao, descricao, id_usuario)
                          VALUES ('UPDATE', %s, %s)""",
                       (f"Movimentação #{id_lancamento} editada", session['id_usuario']))
        conn.commit()
        return jsonify({"sucesso": True, "mensagem": "Movimentação atualizada!"})
    except mysql.connector.Error as err:
        conn.rollback()
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close(); conn.close()


@app.route("/api/financeiro/movimentacoes/<int:id_lancamento>", methods=["DELETE"])
@admin_required
def api_financeiro_excluir_movimentacao(id_lancamento):
    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT descricao, tipo_movimento, valor FROM Lancamento_caixa WHERE id_lancamento = %s", (id_lancamento,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"erro": "Movimentação não encontrada."}), 404
        cursor.execute("DELETE FROM Lancamento_caixa WHERE id_lancamento = %s", (id_lancamento,))
        cursor.execute("""INSERT INTO Log_auditoria (acao, descricao, id_usuario)
                          VALUES ('DELETE', %s, %s)""",
                       (f"{row['tipo_movimento']} excluída: {row['descricao'][:60]}", session['id_usuario']))
        conn.commit()
        return jsonify({"sucesso": True, "mensagem": "Movimentação excluída!"})
    except mysql.connector.Error as err:
        conn.rollback()
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close(); conn.close()


@app.route("/api/financeiro/categorias", methods=["GET"])
@admin_required
def api_financeiro_categorias():
    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT DISTINCT categoria FROM Despesa WHERE categoria IS NOT NULL AND categoria <> '' ORDER BY categoria ASC")
        existentes = [r["categoria"] for r in cursor.fetchall()]
        padrao = ["Equipamentos", "Serviços", "Manutenção", "Laboratório",
                  "Acessórios", "Material de Escritório", "Tecnologia", "Limpeza"]
        return jsonify(sorted(set(existentes + padrao)))
    except mysql.connector.Error as err:
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close(); conn.close()


@app.route("/api/financeiro/verbas", methods=["GET"])
@admin_required
def api_financeiro_verbas():
    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id_verba, nome, saldo_atual, saldo_bloqueado FROM Verba ORDER BY nome ASC")
        verbas = cursor.fetchall()
        for v in verbas:
            v["saldo_atual"] = float(v["saldo_atual"] or 0)
            v["saldo_bloqueado"] = float(v["saldo_bloqueado"] or 0)
        return jsonify(verbas)
    except mysql.connector.Error as err:
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close(); conn.close()


@app.route("/api/financeiro/grafico", methods=["GET"])
@admin_required
def api_financeiro_grafico():
    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT DATE_FORMAT(data_lancamento, '%Y-%m') AS mes,
                   DATE_FORMAT(data_lancamento, '%m/%Y') AS mes_label,
                   SUM(CASE WHEN tipo_movimento = 'Receita' THEN valor ELSE 0 END) AS entradas,
                   SUM(CASE WHEN tipo_movimento = 'Despesa' THEN valor ELSE 0 END) AS saidas
            FROM Lancamento_caixa
            WHERE data_lancamento >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)
            GROUP BY mes, mes_label ORDER BY mes ASC
        """)
        dados = cursor.fetchall()
        for d in dados:
            d["entradas"] = float(d["entradas"] or 0)
            d["saidas"] = float(d["saidas"] or 0)
        return jsonify(dados)
    except mysql.connector.Error as err:
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close(); conn.close()


@app.route("/api/financeiro/origens", methods=["GET"])
@admin_required
def api_financeiro_origens():
    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    resultado = {o: {"id": o, "nome": i["nome"], "cor": i["cor"], "icone": i["icone"],
                     "descricao": i["descricao"], "total_movimentacoes": 0,
                     "total_valor": 0.0, "saldo": 0.0}
                 for o, i in ORIGENS_VALIDAS.items()}
    try:
        cursor.execute("SELECT id_verba, nome, saldo_inicial, saldo_atual FROM verba")
        for v in cursor.fetchall():
            origem, _ = _extrair_origem_verba(v["nome"] or "")
            if origem and origem in resultado:
                resultado[origem]["total_movimentacoes"] += 1
                resultado[origem]["total_valor"] += float(v["saldo_inicial"] or 0)
                resultado[origem]["saldo"] += float(v["saldo_atual"] or 0)
        for o in resultado:
            resultado[o]["total_valor"] = round(resultado[o]["total_valor"], 2)
            resultado[o]["saldo"] = round(resultado[o]["saldo"], 2)
    except mysql.connector.Error as err:
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close(); conn.close()
    return jsonify(list(resultado.values()))


@app.route("/api/financeiro/resumo-por-origem", methods=["GET"])
@admin_required
def api_financeiro_resumo_por_origem():
    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    resumo = {o: {"id": o, "nome": i["nome"], "cor": i["cor"], "icone": i["icone"],
                  "entradas": 0.0, "saidas": 0.0, "saldo": 0.0}
              for o, i in ORIGENS_VALIDAS.items()}
    resumo["SEM_ORIGEM"] = {"id": "SEM_ORIGEM", "nome": "Sem Origem Definida",
                            "cor": "#9ca3af", "icone": "❓",
                            "entradas": 0.0, "saidas": 0.0, "saldo": 0.0}
    try:
        cursor.execute("""
            SELECT lc.tipo_movimento, lc.valor, v.nome AS verba_nome
            FROM Lancamento_caixa lc
            LEFT JOIN Despesa d ON d.id_lancamento = lc.id_lancamento
            LEFT JOIN verba v ON v.id_verba = d.id_verba
        """)
        for l in cursor.fetchall():
            origem, _ = _extrair_origem_verba(l.get("verba_nome") or "")
            chave = origem if origem in resumo else "SEM_ORIGEM"
            valor = float(l["valor"] or 0)
            if l["tipo_movimento"] == "Receita":
                resumo[chave]["entradas"] += valor
            else:
                resumo[chave]["saidas"] += valor
        for k in resumo:
            resumo[k]["saldo"] = round(resumo[k]["entradas"] - resumo[k]["saidas"], 2)
            resumo[k]["entradas"] = round(resumo[k]["entradas"], 2)
            resumo[k]["saidas"] = round(resumo[k]["saidas"], 2)
    except mysql.connector.Error:
        pass
    finally:
        cursor.close(); conn.close()
    return jsonify([v for v in resumo.values() if v["entradas"] > 0 or v["saidas"] > 0])


# ==========================================
# API - MANUTENÇÃO
# ==========================================
@app.route("/api/manutencao/estimar", methods=["POST"])
@admin_required
def api_estimar_custo():
    id_chamado = request.form.get("id_chamado")
    custo_estimado = request.form.get("custo_estimado", 0.0)
    descricao = request.form.get("descricao_servico", "")
    if not id_chamado:
        return jsonify({"erro": "ID do chamado é obrigatório."}), 400
    if manutencao_service.estimarCusto(id_chamado, custo_estimado, descricao):
        return jsonify({"sucesso": True, "mensagem": "Estimativa registrada!"})
    return jsonify({"erro": "Erro ao registrar estimativa."}), 500


@app.route("/api/manutencao/iniciar", methods=["POST"])
@admin_required
def api_iniciar_reparo():
    id_chamado = request.form.get("id_chamado")
    if manutencao_service.iniciarReparo(id_chamado):
        return jsonify({"sucesso": True, "mensagem": "Manutenção iniciada!"})
    return jsonify({"erro": "Erro ao iniciar manutenção."}), 500


@app.route("/api/manutencao/finalizar", methods=["POST"])
@admin_required
def api_finalizar_reparo():
    id_chamado = request.form.get("id_chamado")
    custo_final = request.form.get("custo_final")
    if manutencao_service.finalizarReparo(id_chamado, custo_final):
        return jsonify({"sucesso": True, "mensagem": "Manutenção finalizada!"})
    return jsonify({"erro": "Erro ao finalizar manutenção."}), 500


@app.route("/api/manutencao/<int:id_chamado>", methods=["GET"])
def api_obter_manutencao(id_chamado):
    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT m.id_manutencao, m.id_chamado, m.observacao AS descricao_servico,
                   DATE_FORMAT(m.data_inicio, '%d/%m/%Y %H:%i') AS data_inicio,
                   DATE_FORMAT(m.data_fim, '%d/%m/%Y %H:%i') AS data_fim,
                   c.id_status AS status_chamado
            FROM Manutencao m
            LEFT JOIN Chamado c ON m.id_chamado = c.id_chamado
            WHERE m.id_chamado = %s LIMIT 1
        """, (id_chamado,))
        manutencao = cursor.fetchone()
        if not manutencao:
            return jsonify({"mensagem": "Nenhuma manutenção registrada."}), 404
        status_map = {1: "Agendada", 2: "Em Andamento", 3: "Concluída", 4: "Cancelada"}
        manutencao["status_manutencao"] = status_map.get(manutencao.get("status_chamado"), "Agendada")
        cursor.execute("""SELECT nome, descricao, saldo_inicial FROM verba
                          WHERE nome LIKE %s OR descricao LIKE %s ORDER BY id_verba ASC""",
                       (f"%Manutenção #{id_chamado}%", f"%Chamado #{id_chamado}%"))
        custo_estimado = 0.0; custo_final = 0.0
        for v in cursor.fetchall():
            try:
                desc = v.get("descricao") or ""
                if "R$" in desc:
                    valor = float(desc.split("R$")[-1].strip().split()[0])
                else:
                    valor = float(v.get("saldo_inicial") or 0)
                if "(estimativa)" in (v.get("nome") or "") or "Estimativa" in desc:
                    custo_estimado += valor
                elif "(final)" in (v.get("nome") or "") or "Manutenção do Chamado" in desc:
                    custo_final += valor
                else:
                    custo_estimado = max(custo_estimado, valor)
            except Exception:
                pass
        manutencao["custo_estimado"] = round(custo_estimado, 2)
        manutencao["custo_final"] = round(custo_final, 2)
        manutencao.pop("status_chamado", None)
        return jsonify(manutencao)
    except mysql.connector.Error as err:
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close(); conn.close()


# ==========================================
# API - LOG DE AUDITORIA
# ==========================================
@app.route("/api/log-auditoria", methods=["POST"])
@admin_required
def api_criar_log():
    dados = request.get_json(silent=True) or {}
    acao = (dados.get("acao") or "ACAO")[:100]
    descricao = dados.get("descricao", "")[:1000]
    conn = get_db_connection(); cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO Log_auditoria (acao, descricao, id_usuario) VALUES (%s, %s, %s)",
                       (acao, descricao, session['id_usuario']))
        conn.commit()
        return jsonify({"sucesso": True})
    except mysql.connector.Error as err:
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close(); conn.close()


@app.route("/api/log-auditoria", methods=["GET"])
@admin_required
def api_listar_logs():
    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT l.id_log, l.acao,
               DATE_FORMAT(l.data, '%d/%m/%Y %H:%i') AS data_formatada,
               l.descricao, IFNULL(u.nome, 'Sistema') AS nome_usuario
        FROM Log_auditoria l
        LEFT JOIN Usuario u ON l.id_usuario = u.id_usuario
        ORDER BY l.id_log DESC LIMIT 200
    """)
    logs = cursor.fetchall()
    cursor.close(); conn.close()
    return jsonify(logs)


# ==========================================
# API - USUÁRIOS
# ==========================================
@app.route("/api/usuarios", methods=["GET"])
@admin_required
def api_listar_usuarios():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    query_base = """
        SELECT u.id_usuario, u.nome, u.e_mail, u.id_perfil,
               IFNULL(p.nome, 'Usuário') AS nome_perfil,
               (SELECT COUNT(*) FROM Chamado c WHERE c.id_usuario = u.id_usuario) AS total_chamados
        FROM Usuario u
        LEFT JOIN Perfil p ON u.id_perfil = p.id_perfil
        WHERE 1=1
    """
    try:
        meta = _paginar(query_base, [], page, per_page, cursor)
        cursor.execute(
            f"{query_base} ORDER BY u.id_usuario ASC LIMIT %s OFFSET %s",
            [meta["per_page"], (meta["page"] - 1) * meta["per_page"]]
        )
        usuarios = cursor.fetchall()
        return jsonify({
            **meta,
            "usuarios": usuarios,
            # retrocompatibilidade: também devolve como lista pura
            # (o frontend antigo que usa `res.json()` como array continua funcionando)
            "_legacy": usuarios,
        })
    finally:
        cursor.close()
        conn.close()


@app.route("/api/usuarios/<int:id_usuario>/perfil", methods=["POST"])
@patrimonio_required
def api_alterar_perfil_usuario(id_usuario):
    novo_perfil_raw = request.form.get("id_perfil")
    try:
        novo_perfil_int = int(novo_perfil_raw)
    except (TypeError, ValueError):
        return jsonify({"erro": "Perfil inválido."}), 400

    if novo_perfil_int not in PERFIS_VALIDOS:
        return jsonify({"erro": "Perfil inválido. Use 1 ou 2."}), 400

    if id_usuario == session.get("id_usuario"):
        return jsonify({"erro": "Você não pode alterar o próprio perfil."}), 400


    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE Usuario SET id_perfil = %s WHERE id_usuario = %s",
                       (novo_perfil_int, id_usuario))
        nome_perfil = NOMES_PERFIL.get(novo_perfil_int, "Usuário")
        cursor.execute("""INSERT INTO Log_auditoria (acao, descricao, id_usuario)
                          VALUES (%s, %s, %s)""",
                       ("UPDATE",
                        f"Perfil do usuário #{id_usuario} alterado para {nome_perfil}",
                        session['id_usuario']))
        conn.commit()
        print(f"[ALTERAR PERFIL] ✅ usuário #{id_usuario} → {nome_perfil}")
        return jsonify({"sucesso": True, "mensagem": f"Perfil alterado para {nome_perfil}!"})
    except mysql.connector.Error as err:
        conn.rollback()
        print(f"[ALTERAR PERFIL] ❌ erro MySQL: {err}")
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/api/usuarios/<int:id_usuario>", methods=["DELETE"])
@admin_required
def api_excluir_usuario(id_usuario):
    if id_usuario == session.get("id_usuario"):
        return jsonify({"erro": "Você não pode excluir a si mesmo."}), 400
    conn = get_db_connection(); cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM Chamado WHERE id_usuario = %s", (id_usuario,))
        qtd = cursor.fetchone()[0]
        if qtd > 0:
            return jsonify({"erro": f"Este usuário possui {qtd} chamado(s) e não pode ser excluído."}), 400
        cursor.execute("DELETE FROM Usuario WHERE id_usuario = %s", (id_usuario,))
        cursor.execute("""INSERT INTO Log_auditoria (acao, descricao, id_usuario)
                          VALUES (%s, %s, %s)""",
                       ("DELETE", f"Usuário #{id_usuario} excluído", session['id_usuario']))
        conn.commit()
        return jsonify({"sucesso": True, "mensagem": "Usuário excluído!"})
    except mysql.connector.Error as err:
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close(); conn.close()


# ==========================================
# API - ALERTAS
# ==========================================
@app.route("/api/alertas", methods=["GET"])
def api_listar_alertas():
    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT a.id_alerta,
               DATE_FORMAT(a.data_vencimento, '%d/%m/%Y') AS data_vencimento,
               a.mensagem, IFNULL(t.nome, 'Alerta') AS tipo_alerta
        FROM Alerta a
        LEFT JOIN Tipo_alerta t ON a.id_tipo_alerta = t.id_tipo_alerta
        WHERE a.data_vencimento >= CURDATE()
        ORDER BY a.data_vencimento DESC LIMIT 20
    """)
    alertas = cursor.fetchall()
    cursor.close(); conn.close()
    return jsonify(alertas)


@app.route("/api/alertas", methods=["POST"])
@admin_required
def api_criar_alerta():
    data_vencimento = request.form.get("data_vencimento")
    mensagem = request.form.get("mensagem")
    id_tipo_alerta = request.form.get("id_tipo_alerta", 1)
    if not data_vencimento or not mensagem:
        return jsonify({"erro": "Data e mensagem são obrigatórios."}), 400
    conn = get_db_connection(); cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO Alerta (data_vencimento, mensagem, id_tipo_alerta) VALUES (%s, %s, %s)",
                       (data_vencimento, mensagem, id_tipo_alerta))
        cursor.execute("""INSERT INTO Log_auditoria (acao, descricao, id_usuario)
                          VALUES (%s, %s, %s)""",
                       ("INSERT", f"Alerta criado: {mensagem[:60]}", session['id_usuario']))
        conn.commit()
        return jsonify({"sucesso": True, "mensagem": "Alerta criado!"})
    except mysql.connector.Error as err:
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close(); conn.close()


# ==========================================
# API - ESTATÍSTICAS ADMIN
# ==========================================
@app.route("/api/admin/estatisticas", methods=["GET"])
@admin_required
def api_admin_estatisticas():
    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    stats = {}
    try:
        cursor.execute("""SELECT p.nome AS perfil, COUNT(u.id_usuario) AS qtd
                          FROM Usuario u JOIN Perfil p ON u.id_perfil = p.id_perfil
                          GROUP BY p.id_perfil""")
        stats["usuarios_por_perfil"] = cursor.fetchall()

        cursor.execute("""SELECT IFNULL(s.nome, 'Sem Status') AS status, COUNT(p.id_patrimonio) AS qtd
                          FROM Patrimonio p LEFT JOIN _status s ON p.id_status = s.id_status
                          GROUP BY s.id_status""")
        stats["patrimonios_por_status"] = cursor.fetchall()

        cursor.execute("SELECT id_status, COUNT(*) AS qtd FROM Chamado GROUP BY id_status")
        stats["chamados_por_status"] = cursor.fetchall()

        cursor.execute("SELECT id_patrimonio, valor_atual, data_aquisicao, taxa_depreciacao FROM Patrimonio")
        valor_total = 0.0
        for p in cursor.fetchall():
            valor_total += patrimonio_service.calcular_depreciacao(
                p['valor_atual'], p['data_aquisicao'], p['taxa_depreciacao'])
        stats["valor_total_patrimonio"] = round(valor_total, 2)

        cursor.execute("""SELECT COUNT(*) AS qtd FROM Chamado
                          WHERE id_status = 3
                            AND MONTH(data_abertura) = MONTH(CURDATE())
                            AND YEAR(data_abertura) = YEAR(CURDATE())""")
        stats["chamados_concluidos_mes"] = cursor.fetchone()["qtd"]
    except mysql.connector.Error as err:
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close(); conn.close()
    return jsonify(stats)


# ==========================================
# MÓDULO - BACKUP
# ==========================================
TABELAS_BACKUP = ["perfil", "tipo_sala", "tipo_manutencao", "tipo_chamado",
                  "tipo_anexo", "tipo_alerta", "tipo_verba", "status", "categoria",
                  "usuario", "sala", "verba", "formulario_caixa", "lancamento_caixa",
                  "receita", "despesa", "historico_compra_item",
                  "patrimonio", "movimentacao", "item_movimentacao",
                  "chamado", "historico", "manutencao", "anexo",
                  "alerta", "log_auditoria"]


def _nome_arquivo_backup(ext):
    return f"backup_ipe_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"


def _serializar_valor(v):
    if isinstance(v, datetime): return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, Decimal): return float(v)
    if isinstance(v, bytes): return f"<binário: {len(v)} bytes>"
    return v


def _exportar_tabela(cursor, tabela):
    try:
        cursor.execute(f"SELECT * FROM `{tabela}`")
        return [{k: _serializar_valor(v) for k, v in l.items()} for l in cursor.fetchall()]
    except mysql.connector.Error as err:
        print(f"AVISO: {tabela}: {err}")
        return []


def _registrar_log_backup(acao, descricao):
    try:
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("INSERT INTO Log_auditoria (acao, descricao, id_usuario) VALUES (%s, %s, %s)",
                       (acao[:100], descricao[:1000], session.get('id_usuario', 1)))
        conn.commit(); cursor.close(); conn.close()
    except Exception:
        pass


@app.route("/api/backup/info", methods=["GET"])
@admin_required
def api_backup_info():
    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    info = {"tabelas": [], "backups": [], "total_registros": 0}
    for t in TABELAS_BACKUP:
        try:
            cursor.execute(f"SELECT COUNT(*) AS total FROM `{t}`")
            total = cursor.fetchone()["total"]
            info["tabelas"].append({"nome": t, "total": total})
            info["total_registros"] += total
        except mysql.connector.Error:
            info["tabelas"].append({"nome": t, "total": 0, "erro": True})
    cursor.close(); conn.close()

    pasta = app.config['BACKUP_FOLDER']
    if os.path.isdir(pasta):
        for arq in sorted(os.listdir(pasta), reverse=True):
            cam = os.path.join(pasta, arq)
            if os.path.isfile(cam):
                info["backups"].append({"nome": arq, "tamanho_kb": round(os.path.getsize(cam)/1024, 2),
                                        "data": datetime.fromtimestamp(os.path.getmtime(cam)).strftime("%d/%m/%Y %H:%M")})
    return jsonify(info)


@app.route("/api/backup/exportar-json", methods=["GET"])
@admin_required
def api_backup_exportar_json():
    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    dump = {"sistema": "IPE", "data_exportacao": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            "versao": "1.0", "tabelas": {}}
    for t in TABELAS_BACKUP:
        dump["tabelas"][t] = _exportar_tabela(cursor, t)
    cursor.close(); conn.close()
    json_bytes = json.dumps(dump, ensure_ascii=False, indent=2).encode("utf-8")
    nome = _nome_arquivo_backup("json")
    with open(os.path.join(app.config['BACKUP_FOLDER'], nome), "wb") as f:
        f.write(json_bytes)
    _registrar_log_backup("EXPORT", f"Backup JSON: {nome}")
    return send_file(io.BytesIO(json_bytes), mimetype="application/json", as_attachment=True, download_name=nome)


@app.route("/api/backup/exportar-sql", methods=["GET"])
@admin_required
def api_backup_exportar_sql():
    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    sql = ["-- IPE Backup", f"-- Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
           "SET FOREIGN_KEY_CHECKS = 0;", "SET NAMES utf8mb4;", ""]
    for t in TABELAS_BACKUP:
        try:
            cursor.execute(f"SELECT * FROM `{t}`")
            linhas = cursor.fetchall()
            if not linhas: continue
            sql.append(f"-- Tabela `{t}`")
            cols = list(linhas[0].keys())
            cols_sql = ", ".join(f"`{c}`" for c in cols)
            for l in linhas:
                vals = []
                for c in cols:
                    v = l[c]
                    if v is None: vals.append("NULL")
                    elif isinstance(v, (int, float)): vals.append(str(v))
                    elif isinstance(v, Decimal): vals.append(str(float(v)))
                    elif isinstance(v, datetime): vals.append(f"'{v.strftime('%Y-%m-%d %H:%M:%S')}'")
                    else: vals.append(f"'{str(v).replace(chr(92), chr(92)*2).replace(chr(39), chr(39)*2)}'")
                sql.append(f"INSERT INTO `{t}` ({cols_sql}) VALUES ({', '.join(vals)});")
            sql.append("")
        except mysql.connector.Error as err:
            sql.append(f"-- Erro em {t}: {err}")
    sql.append("SET FOREIGN_KEY_CHECKS = 1;")
    cursor.close(); conn.close()
    sql_bytes = "\n".join(sql).encode("utf-8")
    nome = _nome_arquivo_backup("sql")
    with open(os.path.join(app.config['BACKUP_FOLDER'], nome), "wb") as f:
        f.write(sql_bytes)
    _registrar_log_backup("EXPORT", f"Backup SQL: {nome}")
    return send_file(io.BytesIO(sql_bytes), mimetype="application/sql", as_attachment=True, download_name=nome)


@app.route("/api/backup/exportar-csv/<tabela>", methods=["GET"])
@admin_required
def api_backup_exportar_csv(tabela):
    if tabela not in TABELAS_BACKUP:
        return jsonify({"erro": "Tabela não autorizada."}), 400
    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(f"SELECT * FROM `{tabela}`")
        linhas = cursor.fetchall()
        if not linhas:
            return jsonify({"erro": f"Tabela '{tabela}' vazia."}), 404
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=linhas[0].keys())
        writer.writeheader()
        for l in linhas:
            writer.writerow({k: _serializar_valor(v) for k, v in l.items()})
        csv_bytes = output.getvalue().encode("utf-8-sig")
        nome = f"{tabela}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        with open(os.path.join(app.config['BACKUP_FOLDER'], nome), "wb") as f:
            f.write(csv_bytes)
        _registrar_log_backup("EXPORT", f"Backup CSV: {nome}")
        return send_file(io.BytesIO(csv_bytes), mimetype="text/csv", as_attachment=True, download_name=nome)
    except mysql.connector.Error as err:
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close(); conn.close()


@app.route("/api/backup/exportar-zip", methods=["GET"])
@admin_required
def api_backup_exportar_zip():
    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1. JSON completo
        dump = {"sistema": "IPE", "data_exportacao": datetime.now().strftime("%d/%m/%Y %H:%M:%S"), "tabelas": {}}
        for t in TABELAS_BACKUP:
            dump["tabelas"][t] = _exportar_tabela(cursor, t)
        zf.writestr("backup_completo.json", json.dumps(dump, ensure_ascii=False, indent=2))

        # 2. SQL
        sql_lines = ["-- IPE Backup", f"-- Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
                     "SET FOREIGN_KEY_CHECKS = 0;", "SET NAMES utf8mb4;", ""]
        for t in TABELAS_BACKUP:
            try:
                cursor.execute(f"SELECT * FROM `{t}`")
                linhas = cursor.fetchall()
                if not linhas: continue
                sql_lines.append(f"-- Tabela `{t}`")
                cols = list(linhas[0].keys())
                cols_sql = ", ".join(f"`{c}`" for c in cols)
                for l in linhas:
                    vals = []
                    for c in cols:
                        v = l[c]
                        if v is None: vals.append("NULL")
                        elif isinstance(v, (int, float)): vals.append(str(v))
                        elif isinstance(v, Decimal): vals.append(str(float(v)))
                        elif isinstance(v, datetime): vals.append(f"'{v.strftime('%Y-%m-%d %H:%M:%S')}'")
                        else:
                            s = str(v).replace("\\", "\\\\").replace("'", "''")
                            vals.append(f"'{s}'")
                    sql_lines.append(f"INSERT INTO `{t}` ({cols_sql}) VALUES ({', '.join(vals)});")
                sql_lines.append("")
            except mysql.connector.Error as err:
                sql_lines.append(f"-- Erro em {t}: {err}")
        sql_lines.append("SET FOREIGN_KEY_CHECKS = 1;")
        zf.writestr("backup_completo.sql", "\n".join(sql_lines))

        # 3. CSVs por tabela
        for t in TABELAS_BACKUP:
            try:
                cursor.execute(f"SELECT * FROM `{t}`")
                linhas = cursor.fetchall()
                if not linhas: continue
                out = io.StringIO()
                w = csv.DictWriter(out, fieldnames=linhas[0].keys())
                w.writeheader()
                for l in linhas:
                    w.writerow({k: _serializar_valor(v) for k, v in l.items()})
                zf.writestr(f"csv/{t}.csv", out.getvalue().encode("utf-8-sig"))
            except mysql.connector.Error:
                pass

        zf.writestr("LEIA-ME.txt",
            f"IPE Backup Completo\n"
            f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n"
            f"Conteúdo:\n"
            f"  - backup_completo.json  (estrutura JSON)\n"
            f"  - backup_completo.sql   (dump SQL)\n"
            f"  - csv/<tabela>.csv      (CSV por tabela)\n")

    zip_bytes = zip_buffer.getvalue()
    nome = _nome_arquivo_backup("zip")
    with open(os.path.join(app.config['BACKUP_FOLDER'], nome), "wb") as f:
        f.write(zip_bytes)
    cursor.close(); conn.close()
    _registrar_log_backup("EXPORT", f"Backup ZIP: {nome}")
    return send_file(io.BytesIO(zip_bytes), mimetype="application/zip",
                     as_attachment=True, download_name=nome)


@app.route("/api/backup/download/<path:nome>", methods=["GET"])
@admin_required
def api_backup_download(nome):
    nome_seguro = secure_filename(nome)
    pasta = app.config['BACKUP_FOLDER']
    if not os.path.exists(os.path.join(pasta, nome_seguro)):
        return jsonify({"erro": "Backup não encontrado."}), 404
    return send_from_directory(pasta, nome_seguro, as_attachment=True)


@app.route("/api/backup/excluir/<path:nome>", methods=["DELETE"])
@admin_required
def api_backup_excluir(nome):
    nome_seguro = secure_filename(nome)
    pasta = app.config['BACKUP_FOLDER']
    cam = os.path.join(pasta, nome_seguro)
    if not os.path.exists(cam):
        return jsonify({"erro": "Backup não encontrado."}), 404
    try:
        os.remove(cam)
        _registrar_log_backup("DELETE", f"Backup excluído: {nome_seguro}")
        return jsonify({"sucesso": True, "mensagem": "Backup excluído!"})
    except OSError as err:
        return jsonify({"erro": str(err)}), 500


# ==========================================
# MÓDULO - MOVIMENTAÇÕES
# ==========================================
@app.route("/api/movimentacoes", methods=["GET"])
@login_required
def api_listar_movimentacoes():
    sala_origem = request.args.get("sala_origem", type=int)
    sala_destino = request.args.get("sala_destino", type=int)
    data_ini = request.args.get("data_ini", "").strip()
    data_fim = request.args.get("data_fim", "").strip()
    id_patrimonio = request.args.get("id_patrimonio", type=int)
    busca = request.args.get("busca", "").strip()
    limite = request.args.get("limite", 100, type=int)

    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    query = """
        SELECT m.id_movimentacao,
               DATE_FORMAT(m.data_movimentacao, '%d/%m/%Y %H:%i') AS data_formatada,
               DATE_FORMAT(m.data_movimentacao, '%Y-%m-%d') AS data_iso,
               IFNULL(so.numero_sala, '—') AS sala_origem,
               so.bloco AS bloco_origem,
               IFNULL(sd.numero_sala, '—') AS sala_destino,
               sd.bloco AS bloco_destino,
               (SELECT COUNT(*) FROM item_movimentacao im WHERE im.id_movimentacao = m.id_movimentacao) AS total_itens
        FROM Movimentacao m
        LEFT JOIN Sala so ON m.id_sala_origem = so.id_sala
        LEFT JOIN Sala sd ON m.id_sala_destino = sd.id_sala
        WHERE 1=1
    """
    params = []
    if sala_origem: query += " AND m.id_sala_origem = %s"; params.append(sala_origem)
    if sala_destino: query += " AND m.id_sala_destino = %s"; params.append(sala_destino)
    if data_ini: query += " AND DATE(m.data_movimentacao) >= %s"; params.append(data_ini)
    if data_fim: query += " AND DATE(m.data_movimentacao) <= %s"; params.append(data_fim)
    if id_patrimonio:
        query += " AND m.id_movimentacao IN (SELECT id_movimentacao FROM item_movimentacao WHERE id_patrimonio = %s)"
        params.append(id_patrimonio)
    if busca:
        query += " AND (so.numero_sala LIKE %s OR sd.numero_sala LIKE %s OR so.bloco LIKE %s OR sd.bloco LIKE %s)"
        params.extend([f"%{busca}%"] * 4)
    query += " ORDER BY m.data_movimentacao DESC, m.id_movimentacao DESC LIMIT %s"
    params.append(limite)
    try:
        cursor.execute(query, params)
        return jsonify(cursor.fetchall())
    except mysql.connector.Error as err:
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close(); conn.close()


@app.route("/api/movimentacoes/<int:id_movimentacao>", methods=["GET"])
def api_detalhes_movimentacao(id_movimentacao):
    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""SELECT m.id_movimentacao,
                                 DATE_FORMAT(m.data_movimentacao, '%d/%m/%Y %H:%i') AS data_formatada,
                                 IFNULL(so.numero_sala, '—') AS sala_origem, so.bloco AS bloco_origem,
                                 IFNULL(sd.numero_sala, '—') AS sala_destino, sd.bloco AS bloco_destino
                          FROM Movimentacao m
                          LEFT JOIN Sala so ON m.id_sala_origem = so.id_sala
                          LEFT JOIN Sala sd ON m.id_sala_destino = sd.id_sala
                          WHERE m.id_movimentacao = %s""", (id_movimentacao,))
        mov = cursor.fetchone()
        if not mov:
            return jsonify({"erro": "Movimentação não encontrada."}), 404
        cursor.execute("""SELECT p.id_patrimonio, p.nome, p.numero_patrimonio
                          FROM item_movimentacao im
                          INNER JOIN Patrimonio p ON im.id_patrimonio = p.id_patrimonio
                          WHERE im.id_movimentacao = %s ORDER BY p.nome ASC""", (id_movimentacao,))
        mov["itens"] = cursor.fetchall()
        return jsonify(mov)
    except mysql.connector.Error as err:
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close(); conn.close()


@app.route("/api/movimentacoes", methods=["POST"])
@admin_required
def api_criar_movimentacao():
    id_sala_origem = request.form.get("id_sala_origem") or None
    id_sala_destino = request.form.get("id_sala_destino")
    observacao = (request.form.get("observacao") or "").strip()
    itens_raw = request.form.get("itens")

    if not id_sala_destino:
        return jsonify({"erro": "Selecione a sala de destino."}), 400
    if id_sala_origem and id_sala_origem == id_sala_destino:
        return jsonify({"erro": "Origem e destino não podem ser iguais."}), 400
    try:
        itens = json.loads(itens_raw) if itens_raw else []
        if not isinstance(itens, list) or len(itens) == 0:
            raise ValueError()
    except (ValueError, json.JSONDecodeError):
        return jsonify({"erro": "Selecione pelo menos um patrimônio."}), 400

    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""INSERT INTO Movimentacao (data_movimentacao, id_sala_origem, id_sala_destino)
                          VALUES (NOW(), %s, %s)""",
                       (int(id_sala_origem) if id_sala_origem else None, int(id_sala_destino)))
        id_mov = cursor.lastrowid
        for id_pat in itens:
            cursor.execute("INSERT INTO item_movimentacao (id_movimentacao, id_patrimonio) VALUES (%s, %s)",
                           (id_mov, int(id_pat)))
            cursor.execute("UPDATE Patrimonio SET id_sala = %s WHERE id_patrimonio = %s",
                           (int(id_sala_destino), int(id_pat)))
        cursor.execute("""INSERT INTO Log_auditoria (acao, descricao, id_usuario)
                          VALUES ('UPDATE', %s, %s)""",
                       (f"Movimentação #{id_mov}: {len(itens)} item(ns). Obs: {observacao[:80]}", session['id_usuario']))
        conn.commit()
        return jsonify({"sucesso": True, "mensagem": f"Movimentação registrada! {len(itens)} item(ns).",
                        "id_movimentacao": id_mov}), 201
    except mysql.connector.Error as err:
        conn.rollback()
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close(); conn.close()


@app.route("/api/movimentacoes/resumo", methods=["GET"])
@login_required
def api_movimentacoes_resumo():
    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    resumo = {"total_movimentacoes": 0, "total_itens_movimentados": 0, "salas_envolvidas": 0, "ultima_movimentacao": None}
    try:
        cursor.execute("SELECT COUNT(*) AS total FROM Movimentacao")
        resumo["total_movimentacoes"] = cursor.fetchone()["total"] or 0
        cursor.execute("SELECT COUNT(*) AS total FROM item_movimentacao")
        resumo["total_itens_movimentados"] = cursor.fetchone()["total"] or 0
        cursor.execute("""SELECT COUNT(DISTINCT id_sala) AS total FROM (
                            SELECT id_sala_origem AS id_sala FROM Movimentacao WHERE id_sala_origem IS NOT NULL
                            UNION
                            SELECT id_sala_destino AS id_sala FROM Movimentacao WHERE id_sala_destino IS NOT NULL
                          ) AS salas""")
        resumo["salas_envolvidas"] = cursor.fetchone()["total"] or 0
        cursor.execute("SELECT DATE_FORMAT(MAX(data_movimentacao), '%d/%m/%Y %H:%i') AS data FROM Movimentacao")
        resumo["ultima_movimentacao"] = cursor.fetchone()["data"]
    except mysql.connector.Error:
        pass
    finally:
        cursor.close(); conn.close()
    return jsonify(resumo)


@app.route("/api/movimentacoes/<int:id_movimentacao>", methods=["DELETE"])
@admin_required
def api_excluir_movimentacao(id_movimentacao):
    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id_movimentacao FROM Movimentacao WHERE id_movimentacao = %s", (id_movimentacao,))
        if not cursor.fetchone():
            return jsonify({"erro": "Movimentação não encontrada."}), 404
        cursor.execute("DELETE FROM item_movimentacao WHERE id_movimentacao = %s", (id_movimentacao,))
        cursor.execute("DELETE FROM Movimentacao WHERE id_movimentacao = %s", (id_movimentacao,))
        cursor.execute("""INSERT INTO Log_auditoria (acao, descricao, id_usuario)
                          VALUES ('DELETE', %s, %s)""",
                       (f"Movimentação #{id_movimentacao} excluída", session['id_usuario']))
        conn.commit()
        return jsonify({"sucesso": True, "mensagem": "Movimentação excluída!"})
    except mysql.connector.Error as err:
        conn.rollback()
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close(); conn.close()


# ==========================================
# MÓDULO - BAIXA
# ==========================================
@app.route("/api/baixa/verificar/<int:id_patrimonio>", methods=["GET"])
@admin_required
def api_baixa_verificar(id_patrimonio):
    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""SELECT p.id_patrimonio, p.nome, p.numero_patrimonio, p.valor_atual,
                                 p.data_aquisicao, p.taxa_depreciacao, p.processo_baixa, p.id_status,
                                 IFNULL(s.nome, 'Ativo') AS nome_status
                          FROM Patrimonio p LEFT JOIN _status s ON p.id_status = s.id_status
                          WHERE p.id_patrimonio = %s""", (id_patrimonio,))
        bem = cursor.fetchone()
        if not bem:
            return jsonify({"erro": "Patrimônio não encontrado."}), 404
        if bem["processo_baixa"]:
            return jsonify({"pode_baixar": False, "motivo": "Este patrimônio já foi baixado.", "patrimonio": bem})
        cursor.execute("""SELECT c.id_chamado, DATE_FORMAT(c.data_abertura, '%d/%m/%Y') AS data_abertura,
                                 c.descricao_problema, c.id_status,
                                 CASE c.id_status WHEN 1 THEN 'Aberto' WHEN 2 THEN 'Em Atendimento' ELSE 'Outro' END AS nome_status
                          FROM Chamado c WHERE c.id_patrimonio = %s AND c.id_status IN (1, 2)
                          ORDER BY c.id_chamado DESC""", (id_patrimonio,))
        chamados = cursor.fetchall()
        if chamados:
            return jsonify({"pode_baixar": False,
                            "motivo": f"Existem {len(chamados)} chamado(s) ativo(s) vinculado(s).",
                            "chamados_ativos": chamados, "patrimonio": bem})
        cursor.execute("""SELECT m.id_manutencao, DATE_FORMAT(m.data_inicio, '%d/%m/%Y') AS data_inicio,
                                 DATE_FORMAT(m.data_fim, '%d/%m/%Y') AS data_fim, m.observacao
                          FROM Manutencao m INNER JOIN Chamado c ON m.id_chamado = c.id_chamado
                          WHERE c.id_patrimonio = %s ORDER BY m.data_inicio DESC LIMIT 5""", (id_patrimonio,))
        bem["historico_manutencoes"] = cursor.fetchall()
        return jsonify({"pode_baixar": True, "patrimonio": bem})
    except mysql.connector.Error as err:
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close(); conn.close()


@app.route("/api/baixa/registrar", methods=["POST"])
@admin_required
def api_baixa_registrar():
    id_patrimonio = request.form.get("id_patrimonio")
    motivo = (request.form.get("motivo") or "").strip()
    laudo = (request.form.get("laudo") or "").strip()
    processo = (request.form.get("processo") or "").strip()

    if not id_patrimonio: return jsonify({"erro": "Patrimônio não informado."}), 400
    if not motivo: return jsonify({"erro": "Selecione o motivo."}), 400
    if motivo not in {"Obsoleto", "Danificado", "Perdido", "Doado", "Outro"}:
        return jsonify({"erro": "Motivo inválido."}), 400
    if not laudo or len(laudo) < 10:
        return jsonify({"erro": "Laudo precisa ter ≥10 caracteres."}), 400

    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT COUNT(*) AS total FROM Chamado WHERE id_patrimonio = %s AND id_status IN (1,2)",
                       (id_patrimonio,))
        if cursor.fetchone()["total"] > 0:
            return jsonify({"erro": "Existem chamados ativos vinculados."}), 400
        cursor.execute("SELECT processo_baixa FROM Patrimonio WHERE id_patrimonio = %s", (id_patrimonio,))
        row = cursor.fetchone()
        if not row: return jsonify({"erro": "Patrimônio não encontrado."}), 404
        if row["processo_baixa"]: return jsonify({"erro": "Patrimônio já foi baixado."}), 400

        cursor.execute("""UPDATE Patrimonio
                          SET processo_baixa = CURDATE(), id_status = 3,
                              descricao = CONCAT(IFNULL(descricao, ''),
                                  '\n\n--- BAIXA EM ', DATE_FORMAT(CURDATE(), '%d/%m/%Y'), ' ---\n',
                                  'Motivo: ', %s, '\n', 'Laudo: ', %s,
                                  IF(%s <> '', CONCAT('\nProcesso: ', %s), ''))
                          WHERE id_patrimonio = %s""",
                       (motivo, laudo, processo, processo, id_patrimonio))
        cursor.execute("""INSERT INTO Log_auditoria (acao, descricao, id_usuario)
                          VALUES ('UPDATE', %s, %s)""",
                       (f"BAIXA do patrimônio #{id_patrimonio}: {motivo} - {laudo[:100]}", session['id_usuario']))
        conn.commit()
        return jsonify({"sucesso": True, "mensagem": f"Baixa registrada! Motivo: {motivo}."})
    except mysql.connector.Error as err:
        conn.rollback()
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close(); conn.close()


@app.route("/api/baixa/listar", methods=["GET"])
@admin_required
def api_baixa_listar():
    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""SELECT p.id_patrimonio, p.nome, p.numero_patrimonio, p.valor_atual,
                                 p.descricao,
                                 DATE_FORMAT(p.data_aquisicao, '%d/%m/%Y') AS data_aquisicao,
                                 DATE_FORMAT(p.processo_baixa, '%d/%m/%Y') AS data_baixa,
                                 IFNULL(s.numero_sala, '—') AS nome_sala, s.bloco AS bloco_sala,
                                 IFNULL(cat.nome, '—') AS nome_categoria
                          FROM Patrimonio p
                          LEFT JOIN Sala s ON p.id_sala = s.id_sala
                          LEFT JOIN Categoria cat ON p.id_categoria = cat.id_categoria
                          WHERE p.processo_baixa IS NOT NULL
                          ORDER BY p.processo_baixa DESC, p.id_patrimonio DESC""")
        bens = cursor.fetchall()
        for b in bens:
            b["valor_atual"] = float(b["valor_atual"] or 0)
            # Extrai o motivo do texto "Motivo: XXX"
            desc = b.get("descricao") or ""
            m = re.search(r"Motivo:\s*([^\n]+)", desc)
            b["motivo"] = m.group(1).strip() if m else "—"
            b.pop("descricao", None)  # não envia descrição inteira
        return jsonify(bens)
    except mysql.connector.Error as err:
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close(); conn.close()


@app.route("/api/baixa/resumo", methods=["GET"])
@admin_required
def api_baixa_resumo():
    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    resumo = {"total_baixados": 0, "valor_total_perdido": 0.0, "baixas_mes_atual": 0, "ultima_baixa": None}
    try:
        cursor.execute("""SELECT COUNT(*) AS total, IFNULL(SUM(valor_atual), 0) AS valor
                          FROM Patrimonio WHERE processo_baixa IS NOT NULL""")
        row = cursor.fetchone()
        resumo["total_baixados"] = row["total"] or 0
        resumo["valor_total_perdido"] = float(row["valor"] or 0)
        cursor.execute("""SELECT COUNT(*) AS total FROM Patrimonio
                          WHERE processo_baixa IS NOT NULL
                            AND MONTH(processo_baixa) = MONTH(CURDATE())
                            AND YEAR(processo_baixa) = YEAR(CURDATE())""")
        resumo["baixas_mes_atual"] = cursor.fetchone()["total"] or 0
        cursor.execute("SELECT DATE_FORMAT(MAX(processo_baixa), '%d/%m/%Y') AS data FROM Patrimonio WHERE processo_baixa IS NOT NULL")
        resumo["ultima_baixa"] = cursor.fetchone()["data"]
    except mysql.connector.Error:
        pass
    finally:
        cursor.close(); conn.close()
    return jsonify(resumo)


# ==========================================
# MÓDULO - BENS ALUGADOS
# ==========================================
@app.route("/api/alugados/listar", methods=["GET"])
@admin_required
def api_alugados_listar():
    busca = request.args.get("busca", "").strip()
    fornecedor = request.args.get("fornecedor", "").strip()
    vencendo = request.args.get("vencendo", "")
    incluir_vencidos = request.args.get("incluir_vencidos", "1") == "1"

    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    query = """
        SELECT p.id_patrimonio, p.nome, p.numero_patrimonio, p.valor_atual,
               p.data_aquisicao, DATE_FORMAT(p.data_aquisicao, '%d/%m/%Y') AS data_aquisicao_formatada,
               p.taxa_depreciacao, p.descricao, p.nota_fiscal AS fornecedor, p.origem AS tipo_posse,
               DATE_FORMAT(p.processo_baixa, '%Y-%m-%d') AS data_inicio_contrato_iso,
               DATE_FORMAT(p.processo_baixa, '%d/%m/%Y') AS data_inicio_contrato,
               p.id_sala, IFNULL(s.numero_sala, 'Não Alocado') AS nome_sala,
               s.bloco AS bloco_sala, IFNULL(cat.nome, '—') AS nome_categoria
        FROM Patrimonio p
        LEFT JOIN Sala s ON p.id_sala = s.id_sala
        LEFT JOIN Categoria cat ON p.id_categoria = cat.id_categoria
        WHERE (LOWER(IFNULL(p.origem, '')) LIKE '%%alugado%%'
               OR LOWER(IFNULL(p.origem, '')) LIKE '%%terceiriz%%'
               OR LOWER(IFNULL(p.origem, '')) LIKE '%%locad%%')
    """
    params = []
    if busca:
        query += """ AND (p.nome LIKE %s OR p.numero_patrimonio LIKE %s OR p.nota_fiscal LIKE %s OR p.descricao LIKE %s)"""
        params.extend([f"%{busca}%"] * 4)
    if fornecedor:
        query += " AND p.nota_fiscal LIKE %s"
        params.append(f"%{fornecedor}%")
    query += " ORDER BY p.processo_baixa DESC, p.id_patrimonio DESC"

    try:
        cursor.execute(query, params)
        bens = cursor.fetchall()
        hoje = datetime.now().date()
        for b in bens:
            b["valor_atual"] = float(b["valor_atual"] or 0)
            b["valor_mensal"] = b["valor_atual"]
            data_fim_str = _extrair_data_fim_contrato(b.get("descricao") or "")
            b["data_fim_contrato_iso"] = data_fim_str
            b["data_fim_contrato"] = None
            b["dias_restantes"] = None
            b["status_contrato"] = "Sem data"
            if data_fim_str:
                try:
                    dt_fim = datetime.strptime(data_fim_str, "%Y-%m-%d").date()
                    b["data_fim_contrato"] = dt_fim.strftime("%d/%m/%Y")
                    dias = (dt_fim - hoje).days
                    b["dias_restantes"] = dias
                    if dias < 0: b["status_contrato"] = "Vencido"
                    elif dias <= 30: b["status_contrato"] = "Vencendo"
                    elif dias <= 90: b["status_contrato"] = "Atenção"
                    else: b["status_contrato"] = "Vigente"
                except ValueError:
                    pass
        if vencendo:
            lim = {"30d": 30, "60d": 60, "90d": 90}.get(vencendo)
            if lim:
                bens = [b for b in bens if b["dias_restantes"] is not None and 0 <= b["dias_restantes"] <= lim]
        if not incluir_vencidos:
            bens = [b for b in bens if b["status_contrato"] != "Vencido"]
        return jsonify(bens)
    except mysql.connector.Error as err:
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close(); conn.close()


@app.route("/api/alugados/resumo", methods=["GET"])
@admin_required
def api_alugados_resumo():
    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    resumo = {"total_locados": 0, "total_alugados": 0, "total_terceirizados": 0,
              "custo_mensal_total": 0.0, "contratos_vencendo_30d": 0, "contratos_vencidos": 0}
    try:
        cursor.execute("""SELECT id_patrimonio, valor_atual, origem, descricao FROM Patrimonio
                          WHERE (LOWER(IFNULL(origem, '')) LIKE '%%alugado%%'
                                 OR LOWER(IFNULL(origem, '')) LIKE '%%terceiriz%%'
                                 OR LOWER(IFNULL(origem, '')) LIKE '%%locad%%')""")
        hoje = datetime.now().date()
        for b in cursor.fetchall():
            resumo["total_locados"] += 1
            resumo["custo_mensal_total"] += float(b["valor_atual"] or 0)
            origem = (b.get("origem") or "").lower()
            if "alugado" in origem or "locad" in origem: resumo["total_alugados"] += 1
            elif "terceiriz" in origem: resumo["total_terceirizados"] += 1
            data_fim_str = _extrair_data_fim_contrato(b.get("descricao") or "")
            if data_fim_str:
                try:
                    dt = datetime.strptime(data_fim_str, "%Y-%m-%d").date()
                    dias = (dt - hoje).days
                    if dias < 0: resumo["contratos_vencidos"] += 1
                    elif dias <= 30: resumo["contratos_vencendo_30d"] += 1
                except ValueError:
                    pass
        resumo["custo_mensal_total"] = round(resumo["custo_mensal_total"], 2)
    except mysql.connector.Error:
        pass
    finally:
        cursor.close(); conn.close()
    return jsonify(resumo)


@app.route("/api/alugados/cadastrar", methods=["POST"])
@admin_required
def api_alugados_cadastrar():
    nome = (request.form.get("nome") or "").strip()
    numero_patrimonio = (request.form.get("numero_patrimonio") or "").strip()
    tipo_posse = (request.form.get("tipo_posse") or "Alugado").strip()
    fornecedor = (request.form.get("fornecedor") or "").strip()
    valor_mensal_raw = (request.form.get("valor_mensal") or "0").replace(",", ".")
    data_inicio = (request.form.get("data_inicio") or "").strip()
    data_fim = (request.form.get("data_fim") or "").strip()
    id_sala = request.form.get("id_sala") or None
    descricao = (request.form.get("descricao") or "").strip()

    if not nome: return jsonify({"erro": "Informe o nome."}), 400
    if not numero_patrimonio: return jsonify({"erro": "Informe o número."}), 400
    if not fornecedor: return jsonify({"erro": "Informe o fornecedor."}), 400
    if not data_inicio: return jsonify({"erro": "Informe a data de início."}), 400
    try:
        valor_mensal = float(valor_mensal_raw)
        if valor_mensal < 0: raise ValueError()
    except ValueError:
        return jsonify({"erro": "Valor mensal inválido."}), 400
    if tipo_posse not in ("Alugado", "Terceirizado"):
        return jsonify({"erro": "Tipo inválido."}), 400

    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id_patrimonio FROM Patrimonio WHERE numero_patrimonio = %s", (numero_patrimonio,))
        if cursor.fetchone():
            return jsonify({"erro": f"Já existe nº {numero_patrimonio}."}), 400
        cursor.execute("SELECT id_categoria FROM Categoria LIMIT 1")
        cat = cursor.fetchone()
        if not cat: return jsonify({"erro": "Nenhuma categoria cadastrada."}), 400

        descricao_final = _montar_descricao_com_contrato(descricao, data_fim)
        cursor.execute("""INSERT INTO Patrimonio (nome, numero_patrimonio, valor_atual, data_aquisicao,
                                                    taxa_depreciacao, id_sala, id_categoria, id_status,
                                                    origem, nota_fiscal, processo_baixa, descricao)
                          VALUES (%s, %s, %s, %s, 0.00, %s, %s, 1, %s, %s, %s, %s)""",
                       (nome, numero_patrimonio, valor_mensal, data_inicio,
                        int(id_sala) if id_sala else None, cat["id_categoria"],
                        tipo_posse, fornecedor, data_inicio, descricao_final))
        id_novo = cursor.lastrowid

        if valor_mensal > 0:
            try:
                cursor.execute("""INSERT INTO verba (nome, descricao, ano_referencia, saldo_inicial, saldo_atual, id_tipo_verba)
                                  VALUES (%s, %s, YEAR(CURDATE()), 0, 0, (SELECT id_tipo_verba FROM tipo_verba LIMIT 1))""",
                               (f"Locação: {nome}", f"{tipo_posse} - {fornecedor} - R$ {valor_mensal:.2f}/mês"))
            except mysql.connector.Error:
                pass

        cursor.execute("""INSERT INTO Log_auditoria (acao, descricao, id_usuario)
                          VALUES ('INSERT', %s, %s)""",
                       (f"Bem {tipo_posse}: {nome} (Nº {numero_patrimonio}) - {fornecedor}", session['id_usuario']))
        conn.commit()
        return jsonify({"sucesso": True, "mensagem": f"{tipo_posse} cadastrado!", "id_patrimonio": id_novo}), 201
    except mysql.connector.Error as err:
        conn.rollback()
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close(); conn.close()


@app.route("/api/alugados/<int:id_patrimonio>", methods=["PUT", "POST"])
@admin_required
def api_alugados_editar(id_patrimonio):
    nome = (request.form.get("nome") or "").strip()
    fornecedor = (request.form.get("fornecedor") or "").strip()
    valor_mensal_raw = (request.form.get("valor_mensal") or "0").replace(",", ".")
    data_inicio = (request.form.get("data_inicio") or "").strip()
    data_fim = (request.form.get("data_fim") or "").strip()
    descricao = (request.form.get("descricao") or "").strip()

    if not nome or not fornecedor:
        return jsonify({"erro": "Nome e fornecedor obrigatórios."}), 400
    try:
        valor_mensal = float(valor_mensal_raw)
    except ValueError:
        return jsonify({"erro": "Valor inválido."}), 400

    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id_patrimonio FROM Patrimonio WHERE id_patrimonio = %s", (id_patrimonio,))
        if not cursor.fetchone():
            return jsonify({"erro": "Bem não encontrado."}), 404
        descricao_final = _montar_descricao_com_contrato(descricao, data_fim)
        cursor.execute("""UPDATE Patrimonio SET nome = %s, valor_atual = %s, nota_fiscal = %s,
                                                 processo_baixa = %s, data_aquisicao = %s, descricao = %s
                          WHERE id_patrimonio = %s""",
                       (nome, valor_mensal, fornecedor, data_inicio, data_inicio, descricao_final, id_patrimonio))
        cursor.execute("""INSERT INTO Log_auditoria (acao, descricao, id_usuario)
                          VALUES ('UPDATE', %s, %s)""",
                       (f"Bem alugado #{id_patrimonio} editado", session['id_usuario']))
        conn.commit()
        return jsonify({"sucesso": True, "mensagem": "Bem atualizado!"})
    except mysql.connector.Error as err:
        conn.rollback()
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close(); conn.close()


@app.route("/api/alugados/<int:id_patrimonio>", methods=["DELETE"])
@admin_required
def api_alugados_excluir(id_patrimonio):
    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT COUNT(*) AS total FROM Chamado WHERE id_patrimonio = %s AND id_status IN (1,2)",
                       (id_patrimonio,))
        if cursor.fetchone()["total"] > 0:
            return jsonify({"erro": "Existem chamados ativos."}), 400
        cursor.execute("DELETE FROM Patrimonio WHERE id_patrimonio = %s", (id_patrimonio,))
        cursor.execute("""INSERT INTO Log_auditoria (acao, descricao, id_usuario)
                          VALUES ('DELETE', %s, %s)""",
                       (f"Bem alugado #{id_patrimonio} excluído", session['id_usuario']))
        conn.commit()
        return jsonify({"sucesso": True, "mensagem": "Bem removido!"})
    except mysql.connector.Error as err:
        conn.rollback()
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close(); conn.close()

@app.route("/api/patrimonio/<int:id_patrimonio>", methods=["DELETE"])
@admin_required
def api_excluir_patrimonio(id_patrimonio):
    """
    Exclui DEFINITIVAMENTE um patrimônio.
    Só funciona se:
    - O usuário é ADM
    - O patrimônio NÃO tem chamados ativos (status 1 ou 2)
    - O patrimônio NÃO tem movimentações com outros itens
    - O patrimônio NÃO tem manutenções vinculadas
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # 1. Verifica se existe
        cursor.execute("""
            SELECT p.id_patrimonio, p.nome, p.numero_patrimonio
            FROM Patrimonio p
            WHERE p.id_patrimonio = %s
        """, (id_patrimonio,))
        bem = cursor.fetchone()
        if not bem:
            return jsonify({"erro": "Patrimônio não encontrado."}), 404

        # 2. Bloqueia se tem chamados ativos
        cursor.execute("""
            SELECT COUNT(*) AS total FROM Chamado
            WHERE id_patrimonio = %s AND id_status IN (1, 2)
        """, (id_patrimonio,))
        if cursor.fetchone()["total"] > 0:
            return jsonify({
                "erro": "Existem chamados ativos vinculados. Conclua ou cancele antes de excluir."
            }), 400

        # 3. Bloqueia se tem chamados (qualquer status) — preserva histórico
        cursor.execute("SELECT COUNT(*) AS total FROM Chamado WHERE id_patrimonio = %s", (id_patrimonio,))
        if cursor.fetchone()["total"] > 0:
            return jsonify({
                "erro": "Este patrimônio possui histórico de chamados. Use a 'Baixa' em vez de excluir."
            }), 400

        # 4. Registra no Log de Auditoria antes de excluir
        cursor.execute("""
            INSERT INTO Log_auditoria (acao, descricao, id_usuario)
            VALUES ('DELETE', %s, %s)
        """, (f"EXCLUSÃO do patrimônio #{id_patrimonio}: {bem['nome']} (Nº {bem['numero_patrimonio']})",
              session['id_usuario']))

        # 5. Exclui
        cursor.execute("DELETE FROM Patrimonio WHERE id_patrimonio = %s", (id_patrimonio,))
        conn.commit()

        return jsonify({
            "sucesso": True,
            "mensagem": f"Patrimônio \"{bem['nome']}\" excluído com sucesso."
        })
    except mysql.connector.Error as err:
        conn.rollback()
        return jsonify({"erro": f"Erro ao excluir: {str(err)}"}), 500
    finally:
        cursor.close(); conn.close()
# ==========================================
# MÓDULO - REPAROS
# ==========================================
# ==========================================
# MÓDULO - REPAROS
# ==========================================

# ==========================================
# MÓDULO - REPAROS
# ==========================================

@app.route("/api/reparos/ranking", methods=["GET"])
def api_reparos_ranking():
    limite = request.args.get("limite", 20, type=int)
    periodo = request.args.get("periodo", "365", type=int)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT p.id_patrimonio, p.nome, p.numero_patrimonio,
                   IFNULL(s.numero_sala, 'Não Alocado') AS nome_sala,
                   s.bloco AS bloco_sala,
                   IFNULL(cat.nome, '—') AS nome_categoria,
                   COUNT(DISTINCT c.id_chamado) AS total_chamados,
                   COUNT(DISTINCT CASE WHEN c.id_status = 3 THEN c.id_chamado END) AS chamados_concluidos,
                   COUNT(DISTINCT CASE WHEN c.id_status IN (1, 2) THEN c.id_chamado END) AS chamados_ativos,
                   COUNT(DISTINCT m.id_manutencao) AS total_manutencoes,
                   IFNULL(SUM(CASE WHEN v.descricao LIKE CONCAT('%Chamado #', c.id_chamado, '%')
                                   THEN v.saldo_inicial ELSE 0 END), 0) AS valor_total_gasto,
                   DATE_FORMAT(MAX(c.data_abertura), '%d/%m/%Y') AS ultimo_chamado,
                   DATE_FORMAT(MIN(c.data_abertura), '%d/%m/%Y') AS primeiro_chamado
            FROM Patrimonio p
            LEFT JOIN Sala s ON p.id_sala = s.id_sala
            LEFT JOIN Categoria cat ON p.id_categoria = cat.id_categoria
            LEFT JOIN Chamado c ON c.id_patrimonio = p.id_patrimonio
                AND c.data_abertura >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
            LEFT JOIN Manutencao m ON m.id_chamado = c.id_chamado
            LEFT JOIN verba v ON v.descricao LIKE CONCAT('%Chamado #', c.id_chamado, '%')
            GROUP BY p.id_patrimonio, p.nome, p.numero_patrimonio,
                     s.numero_sala, s.bloco, cat.nome
            HAVING total_chamados > 0
            ORDER BY total_chamados DESC, valor_total_gasto DESC
            LIMIT %s
        """, (periodo, limite))

        dados = cursor.fetchall()
        for d in dados:
            d["valor_total_gasto"] = float(d["valor_total_gasto"] or 0)
            if d["total_chamados"] >= 5:
                d["nivel_reincidencia"] = "Crítico"
            elif d["total_chamados"] >= 3:
                d["nivel_reincidencia"] = "Alto"
            elif d["total_chamados"] >= 2:
                d["nivel_reincidencia"] = "Médio"
            else:
                d["nivel_reincidencia"] = "Baixo"
        return jsonify(dados)
    except mysql.connector.Error as err:
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/api/reparos/resumo", methods=["GET"])
def api_reparos_resumo():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    resumo = {"total_reparos": 0, "bens_com_reparo": 0, "bens_criticos": 0,
              "custo_total_manutencoes": 0.0, "tempo_medio_reparo_dias": 0}
    try:
        cursor.execute("SELECT COUNT(*) AS total FROM Manutencao")
        resumo["total_reparos"] = cursor.fetchone()["total"] or 0

        cursor.execute("""SELECT COUNT(DISTINCT c.id_patrimonio) AS total
                          FROM Manutencao m INNER JOIN Chamado c ON m.id_chamado = c.id_chamado
                          WHERE c.id_patrimonio IS NOT NULL""")
        resumo["bens_com_reparo"] = cursor.fetchone()["total"] or 0

        cursor.execute("""SELECT COUNT(*) AS total FROM (
                            SELECT c.id_patrimonio FROM Chamado c
                            WHERE c.data_abertura >= DATE_SUB(CURDATE(), INTERVAL 365 DAY)
                              AND c.id_patrimonio IS NOT NULL
                            GROUP BY c.id_patrimonio HAVING COUNT(*) >= 3
                          ) AS criticos""")
        resumo["bens_criticos"] = cursor.fetchone()["total"] or 0

        cursor.execute("""SELECT IFNULL(SUM(saldo_inicial), 0) AS total FROM verba
                          WHERE descricao LIKE '%Manutenção do Chamado%' OR nome LIKE '%Manutenção #%'""")
        resumo["custo_total_manutencoes"] = float(cursor.fetchone()["total"] or 0)

        cursor.execute("""SELECT AVG(DATEDIFF(c.data_abertura, m.data_inicio)) AS media
                          FROM Manutencao m INNER JOIN Chamado c ON m.id_chamado = c.id_chamado
                          WHERE m.data_inicio IS NOT NULL""")
        media = cursor.fetchone()["media"]
        resumo["tempo_medio_reparo_dias"] = round(float(media), 1) if media else 0
    except mysql.connector.Error:
        pass
    finally:
        cursor.close()
        conn.close()
    return jsonify(resumo)


@app.route("/api/reparos/patrimonio/<int:id_patrimonio>", methods=["GET"])
def api_reparos_por_patrimonio(id_patrimonio):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # 1) Busca dados do patrimônio
        cursor.execute("""
            SELECT p.id_patrimonio, p.nome, p.numero_patrimonio, p.valor_atual,
                   DATE_FORMAT(p.data_aquisicao, '%d/%m/%Y') AS data_aquisicao,
                   p.taxa_depreciacao, p.descricao,
                   IFNULL(s.numero_sala, 'Não Alocado') AS nome_sala,
                   s.bloco AS bloco_sala,
                   IFNULL(cat.nome, '—') AS nome_categoria
            FROM Patrimonio p
            LEFT JOIN Sala s ON p.id_sala = s.id_sala
            LEFT JOIN Categoria cat ON p.id_categoria = cat.id_categoria
            WHERE p.id_patrimonio = %s
        """, (id_patrimonio,))

        bem = cursor.fetchone()
        if not bem:
            return jsonify({"erro": "Patrimônio não encontrado."}), 404

        # 2) Busca todos os chamados vinculados
        cursor.execute("""
            SELECT c.id_chamado,
                   DATE_FORMAT(c.data_abertura, '%d/%m/%Y %H:%i') AS data_abertura,
                   DATE_FORMAT(c.data_abertura, '%Y-%m-%d') AS data_abertura_iso,
                   c.descricao_problema, c.prioridade, c.id_status,
                   CASE c.id_status WHEN 1 THEN 'Aberto' WHEN 2 THEN 'Em Atendimento'
                                    WHEN 3 THEN 'Concluído' WHEN 4 THEN 'Cancelado'
                                    ELSE 'Aberto' END AS nome_status,
                   IFNULL(u.nome, 'Sistema') AS nome_solicitante,
                   IFNULL(tc.nome, '—') AS tipo_chamado,
                   m.id_manutencao,
                   DATE_FORMAT(m.data_inicio, '%d/%m/%Y') AS data_inicio_manutencao,
                   DATE_FORMAT(m.data_fim, '%d/%m/%Y') AS data_fim_manutencao,
                   m.observacao AS observacao_manutencao,
                   DATEDIFF(m.data_fim, m.data_inicio) AS duracao_dias
            FROM Chamado c
            LEFT JOIN Usuario u ON c.id_usuario = u.id_usuario
            LEFT JOIN Tipo_chamado tc ON c.id_tipo_chamado = tc.id_tipo_chamado
            LEFT JOIN Manutencao m ON m.id_chamado = c.id_chamado
            WHERE c.id_patrimonio = %s
            ORDER BY c.data_abertura DESC
        """, (id_patrimonio,))

        chamados = cursor.fetchall()

        # 3) Busca anexos de todos os chamados
        anexos_por_chamado = {}
        if chamados:
            ids = [str(c["id_chamado"]) for c in chamados]
            placeholders = ",".join(["%s"] * len(ids))
            cursor.execute(f"""
                SELECT id_anexo, id_chamado, caminho,
                       DATE_FORMAT(data_upload, '%d/%m/%Y') AS data_upload
                FROM Anexo
                WHERE id_chamado IN ({placeholders})
                ORDER BY id_anexo DESC
            """, ids)
            for a in cursor.fetchall():
                anexos_por_chamado.setdefault(a["id_chamado"], []).append(a)

        # 4) Monta lista de reparos (chamados com manutenção)
        reparos = []
        for c in chamados:
            c["anexos"] = anexos_por_chamado.get(c["id_chamado"], [])
            if c["id_manutencao"]:
                reparos.append(c)

        total_chamados = len(chamados)
        total_reparos = len(reparos)
        valores_gastos = 0.0
        duracoes = [r["duracao_dias"] for r in reparos if r.get("duracao_dias") is not None]

        # 5) Soma valores gastos por chamado
        for c in chamados:
            cursor.execute(
                "SELECT IFNULL(SUM(saldo_inicial), 0) AS total FROM verba WHERE descricao LIKE %s",
                (f"%Chamado #{c['id_chamado']}%",)
            )
            valores_gastos += float(cursor.fetchone()["total"] or 0)

        tempo_medio = round(sum(duracoes) / len(duracoes), 1) if duracoes else 0
        if total_reparos >= 5:
            nivel = "Crítico"
        elif total_reparos >= 3:
            nivel = "Alto"
        elif total_reparos >= 2:
            nivel = "Médio"
        else:
            nivel = "Baixo"

        return jsonify({
            "patrimonio": bem,
            "estatisticas": {
                "total_chamados": total_chamados,
                "total_reparos": total_reparos,
                "valor_total_gasto": round(valores_gastos, 2),
                "tempo_medio_reparo_dias": tempo_medio,
                "nivel_reincidencia": nivel,
                "ultimo_reparo": reparos[0]["data_abertura"] if reparos else None,
                "primeiro_chamado": chamados[-1]["data_abertura"] if chamados else None
            },
            "reparos": reparos,
            "todos_chamados": chamados
        })
    except mysql.connector.Error as err:
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/api/reparos/patrimonio/<int:id_patrimonio>/pdf", methods=["GET"])
@admin_required
def api_reparos_patrimonio_pdf(id_patrimonio):
    from xml.sax.saxutils import escape as _esc

    resp = api_reparos_por_patrimonio(id_patrimonio)   # mesmos dados da tela
    if isinstance(resp, tuple):
        return resp
    dados = resp.get_json()
    p, est, reparos = dados["patrimonio"], dados["estatisticas"], dados["reparos"]

    def t(v):
        return _esc(str(v)) if v not in (None, "") else "—"

    def brl(v):
        try:
            s = f"{float(v or 0):,.2f}"
        except (TypeError, ValueError):
            s = "0.00"
        return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            leftMargin=1.6 * cm, rightMargin=1.6 * cm,
                            topMargin=1.6 * cm, bottomMargin=1.6 * cm,
                            title=f"Histórico de Reparos - {p['numero_patrimonio']}")
    base = getSampleStyleSheet()
    escuro = colors.HexColor("#152937")
    st_titulo = ParagraphStyle("rt", parent=base["Title"], fontSize=16, textColor=escuro, alignment=TA_LEFT, spaceAfter=2)
    st_sub = ParagraphStyle("rs", parent=base["Normal"], fontSize=9, textColor=colors.HexColor("#5b6670"))
    st_h2 = ParagraphStyle("rh", parent=base["Heading2"], fontSize=12, textColor=escuro, spaceBefore=12, spaceAfter=6)
    st_txt = ParagraphStyle("rx", parent=base["Normal"], fontSize=9, leading=12)

    sala = t(p.get("nome_sala")) + (f" · {t(p.get('bloco_sala'))}" if p.get("bloco_sala") else "")
    el = [
        Paragraph("Histórico de Reparos", st_titulo),
        Paragraph(f"{t(p['nome'])} — Nº {t(p['numero_patrimonio'])}", st_sub),
        Paragraph(f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}", st_sub),
        Spacer(1, 10),
    ]

    ficha = Table([
        ["Sala", Paragraph(sala, st_txt), "Categoria", Paragraph(t(p.get("nome_categoria")), st_txt)],
        ["Aquisição", Paragraph(t(p.get("data_aquisicao")), st_txt), "Valor original", brl(p.get("valor_atual"))],
    ], colWidths=[2.4 * cm, 6.2 * cm, 2.8 * cm, 6.0 * cm])
    ficha.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fafafa")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 5),
    ]))
    el.append(ficha)

    el.append(Paragraph("Resumo", st_h2))
    resumo = Table([
        ["Chamados", "Reparos", "Custo total", "Tempo médio", "Reincidência"],
        [str(est["total_chamados"]), str(est["total_reparos"]), brl(est["valor_total_gasto"]),
         f"{est['tempo_medio_reparo_dias']} dia(s)", est["nivel_reincidencia"]],
    ], colWidths=[3.2 * cm] * 5)
    resumo.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F29310")),
        ("TEXTCOLOR", (0, 0), (-1, 0), escuro),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 5),
    ]))
    el.append(resumo)

    el.append(Paragraph("Reparos registrados", st_h2))
    if not reparos:
        el.append(Paragraph("Nenhum reparo registrado para este equipamento.", st_txt))
    for r in reparos:
        linhas = [
            [Paragraph(f"<b>Chamado #{r['id_chamado']}</b> — {t(r.get('tipo_chamado'))}", st_txt),
             Paragraph(f"<b>{t(r.get('nome_status'))}</b> · {t(r.get('data_abertura'))}", st_txt)],
            [Paragraph(f"<b>Problema:</b> {t(r.get('descricao_problema'))}", st_txt), ""],
        ]
        if r.get("observacao_manutencao"):
            linhas.append([Paragraph(f"<b>Serviço realizado:</b> {t(r['observacao_manutencao'])}", st_txt), ""])
        meta = [f"Prioridade: {t(r.get('prioridade'))}", f"Solicitante: {t(r.get('nome_solicitante'))}"]
        if r.get("data_inicio_manutencao"):
            meta.append(f"Início: {t(r['data_inicio_manutencao'])}")
        if r.get("data_fim_manutencao"):
            meta.append(f"Fim: {t(r['data_fim_manutencao'])}")
        if r.get("duracao_dias") is not None:
            meta.append(f"Duração: {r['duracao_dias']} dia(s)")
        linhas.append([Paragraph(" · ".join(meta), st_sub), ""])
        bloco = Table(linhas, colWidths=[11.4 * cm, 6.0 * cm])
        estilo = [
            ("SPAN", (0, i), (1, i)) for i in range(1, len(linhas))
        ] + [
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#fafafa")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 4),
        ]
        bloco.setStyle(TableStyle(estilo))
        el.append(bloco)
        el.append(Spacer(1, 6))

    doc.build(el)
    buffer.seek(0)
    nome = f"reparos_{p['numero_patrimonio']}_{datetime.now().strftime('%Y%m%d')}.pdf"
    return send_file(buffer, mimetype="application/pdf", as_attachment=False, download_name=nome)


# ==========================================
# MÓDULO - NOTIFICAÇÕES (SINO)
# ==========================================
# ==========================================
# MÓDULO - NOTIFICAÇÕES (SINO)
# ==========================================
@app.route("/api/notificacoes", methods=["GET"])
def api_notificacoes():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    notificacoes = []
    try:
        # ---- 1) Alertas ativos ----
        cursor.execute("""
            SELECT a.id_alerta, a.mensagem,
                   DATE_FORMAT(a.data_vencimento, '%d/%m/%Y') AS data_vencimento,
                   a.id_tipo_alerta, IFNULL(t.nome, 'Alerta') AS tipo_alerta,
                   DATEDIFF(a.data_vencimento, CURDATE()) AS dias_restantes
            FROM Alerta a
            LEFT JOIN Tipo_alerta t ON a.id_tipo_alerta = t.id_tipo_alerta
            WHERE a.data_vencimento >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
            ORDER BY a.data_vencimento DESC
            LIMIT 20
        """)
        for a in cursor.fetchall():
            tipo = "sla" if a["id_tipo_alerta"] == 1 else "garantia"
            if a["dias_restantes"] is not None and a["dias_restantes"] < 0:
                urg = "vencido"
            elif a["dias_restantes"] is not None and a["dias_restantes"] <= 3:
                urg = "urgente"
            else:
                urg = "info"
            notificacoes.append({
                "id": f"alerta-{a['id_alerta']}",
                "tipo": tipo,
                "urgencia": urg,
                "titulo": a["tipo_alerta"],
                "mensagem": a["mensagem"],
                "data": a["data_vencimento"],
                "link": "/admin.html",
                "origem": "Alerta",
            })

        # ---- 2) Chamados abertos há 7+ dias ----
        cursor.execute("""
            SELECT c.id_chamado, c.descricao_problema, c.prioridade,
                   DATE_FORMAT(c.data_abertura, '%d/%m/%Y') AS data_abertura,
                   DATEDIFF(CURDATE(), c.data_abertura) AS dias_aberto,
                   IFNULL(p.nome, 'Sem patrimônio') AS nome_patrimonio
            FROM Chamado c
            LEFT JOIN Patrimonio p ON c.id_patrimonio = p.id_patrimonio
            WHERE c.id_status IN (1, 2)
              AND DATEDIFF(CURDATE(), c.data_abertura) >= 7
            ORDER BY c.data_abertura ASC
            LIMIT 15
        """)
        for c in cursor.fetchall():
            if c["dias_aberto"] >= 30:
                urg = "vencido"
            elif c["dias_aberto"] >= 14:
                urg = "urgente"
            else:
                urg = "info"
            notificacoes.append({
                "id": f"chamado-{c['id_chamado']}",
                "tipo": "chamado",
                "urgencia": urg,
                "titulo": f"Chamado #{c['id_chamado']} aberto há {c['dias_aberto']} dias",
                "mensagem": f"{c['nome_patrimonio']}: {c['descricao_problema'][:80]}...",
                "data": c["data_abertura"],
                "link": "/chamados.html",
                "origem": "Chamado",
            })

        # ---- 3) Contratos de locação vencendo/vencidos ----
        cursor.execute("""
            SELECT p.id_patrimonio, p.nome, p.numero_patrimonio,
                   p.nota_fiscal AS fornecedor, p.descricao
            FROM Patrimonio p
            WHERE (LOWER(IFNULL(p.origem, '')) LIKE '%%alugado%%'
                   OR LOWER(IFNULL(p.origem, '')) LIKE '%%terceiriz%%')
        """)
        hoje = datetime.now().date()
        for b in cursor.fetchall():
            desc = b.get("descricao") or ""
            data_fim_str = _extrair_data_fim_contrato(desc)
            if not data_fim_str:
                continue
            try:
                dt_fim = datetime.strptime(data_fim_str, "%Y-%m-%d").date()
                dias = (dt_fim - hoje).days
                if -30 <= dias <= 30:
                    if dias < 0:
                        urg = "vencido"
                    elif dias <= 7:
                        urg = "urgente"
                    else:
                        urg = "info"
                    notificacoes.append({
                        "id": f"contrato-{b['id_patrimonio']}",
                        "tipo": "contrato",
                        "urgencia": urg,
                        "titulo": f"Contrato {'vencido' if dias < 0 else 'vence'} em {abs(dias)} dia(s)",
                        "mensagem": f"{b['nome']} — {b['fornecedor']}",
                        "data": dt_fim.strftime("%d/%m/%Y"),
                        "link": "/alugados.html",
                        "origem": "Locação",
                    })
            except (ValueError, IndexError):
                continue

        # ---- 4) Manutenções paradas há 5+ dias ----
        cursor.execute("""
            SELECT m.id_manutencao,
                   DATE_FORMAT(m.data_inicio, '%d/%m/%Y') AS data_inicio,
                   DATEDIFF(CURDATE(), m.data_inicio) AS dias_parado,
                   c.id_chamado,
                   IFNULL(p.nome, 'Sem patrimônio') AS nome_patrimonio
            FROM Manutencao m
            INNER JOIN Chamado c ON m.id_chamado = c.id_chamado
            LEFT JOIN Patrimonio p ON c.id_patrimonio = p.id_patrimonio
            WHERE c.id_status = 2
              AND DATEDIFF(CURDATE(), m.data_inicio) >= 5
            ORDER BY m.data_inicio ASC
            LIMIT 10
        """)
        for m in cursor.fetchall():
            notificacoes.append({
                "id": f"manut-{m['id_manutencao']}",
                "tipo": "manutencao",
                "urgencia": "urgente" if m["dias_parado"] >= 10 else "info",
                "titulo": f"Manutenção parada há {m['dias_parado']} dias",
                "mensagem": f"Chamado #{m['id_chamado']}: {m['nome_patrimonio']}",
                "data": m["data_inicio"],
                "link": "/chamados.html",
                "origem": "Manutenção",
            })
    except mysql.connector.Error:
        pass
    finally:
        cursor.close()
        conn.close()

    # ---- Ordenação final: urgência primeiro, depois data decrescente ----
    ordem = {"vencido": 0, "urgente": 1, "info": 2}

    def _chave_ordenacao(n):
        # Converte "dd/mm/yyyy" -> "yyyy-mm-dd" para ordenar cronologicamente
        data = n.get("data", "") or ""
        try:
            d, m, a = data.split("/")
            return (ordem.get(n["urgencia"], 3), f"{a}-{m}-{d}")
        except (ValueError, AttributeError):
            return (ordem.get(n["urgencia"], 3), "0000-00-00")

    # Ordena ascendente por urgência, mas decrescente por data DENTRO de cada grupo
    grupos = {}
    for n in notificacoes:
        grupos.setdefault(n["urgencia"], []).append(n)

    notificacoes_ordenadas = []
    for urg in ("vencido", "urgente", "info"):
        notificacoes_ordenadas.extend(
            sorted(grupos.get(urg, []), key=_chave_ordenacao, reverse=True)
        )
    # urgências não listadas (se houver) vão para o fim
    for urg, itens in grupos.items():
        if urg not in ("vencido", "urgente", "info"):
            notificacoes_ordenadas.extend(
                sorted(itens, key=_chave_ordenacao, reverse=True)
            )

    notificacoes = notificacoes_ordenadas

    return jsonify({"total": len(notificacoes), "notificacoes": notificacoes})


@app.route("/api/inventario/buscar", methods=["GET"])
def api_inventario_buscar():
    busca = request.args.get("busca", "").strip()
    categoria = request.args.get("categoria", "").strip()
    sala = request.args.get("sala", type=int)
    status = request.args.get("status", type=int)
    valor_min = request.args.get("valor_min", type=float)
    valor_max = request.args.get("valor_max", type=float)
    data_ini = request.args.get("data_ini", "").strip()
    data_fim = request.args.get("data_fim", "").strip()
    ordem = request.args.get("ordem", "numero").strip()
    direcao = request.args.get("direcao", "desc").strip().lower()
    incluir_baixados = request.args.get("incluir_baixados", "0") == "1"

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    from_join = """
        FROM Patrimonio p
        LEFT JOIN Sala s ON p.id_sala = s.id_sala
        LEFT JOIN Categoria cat ON p.id_categoria = cat.id_categoria
        LEFT JOIN _status st ON p.id_status = st.id_status
    """

    where = " WHERE 1=1"
    params = []

    if not incluir_baixados:
        where += " AND p.processo_baixa IS NULL"

    if busca:
        where += (" AND (p.nome LIKE %s OR p.numero_patrimonio LIKE %s"
                  " OR p.nota_fiscal LIKE %s OR p.descricao LIKE %s)")
        params.extend([f"%{busca}%"] * 4)

    if categoria:
        if categoria.startswith("cge::"):
            nome_cge = categoria.replace("cge::", "", 1)
            where += " AND cat.nome = %s"
            params.append(nome_cge)
        else:
            try:
                where += " AND p.id_categoria = %s"
                params.append(int(categoria))
            except ValueError:
                pass

    if sala:
        where += " AND p.id_sala = %s"; params.append(sala)
    if status:
        where += " AND p.id_status = %s"; params.append(status)
    if valor_min is not None:
        where += " AND p.valor_atual >= %s"; params.append(valor_min)
    if valor_max is not None:
        where += " AND p.valor_atual <= %s"; params.append(valor_max)
    if data_ini:
        where += " AND DATE(p.data_aquisicao) >= %s"; params.append(data_ini)
    if data_fim:
        where += " AND DATE(p.data_aquisicao) <= %s"; params.append(data_fim)

    campos = {"numero": "p.numero_patrimonio", "nome": "p.nome", "valor": "p.valor_atual",
              "data": "p.data_aquisicao", "categoria": "cat.nome", "sala": "s.numero_sala",
              "status": "st.nome"}
    campo_sql = campos.get(ordem, "p.numero_patrimonio")
    direcao_sql = "DESC" if direcao == "desc" else "ASC"

    try:
        # Total de registros (para info)
        cursor.execute(f"SELECT COUNT(*) AS total {from_join} {where}", params)
        total = int(cursor.fetchone()["total"] or 0)

        # Busca TODOS os registros (sem LIMIT/OFFSET)
        cursor.execute(
            f"""SELECT p.id_patrimonio, p.nome, p.numero_patrimonio,
                       p.valor_atual AS valor_compra,
                       DATE_FORMAT(p.data_aquisicao, '%Y-%m-%d') AS data_aquisicao,
                       DATE_FORMAT(p.data_aquisicao, '%d/%m/%Y') AS data_aquisicao_formatada,
                       p.taxa_depreciacao, p.descricao, p.nota_fiscal,
                       p.processo_baixa, p.origem, p.id_categoria, p.id_sala, p.id_status,
                       IFNULL(s.numero_sala, 'Não Alocado') AS nome_sala, s.bloco AS bloco_sala,
                       IFNULL(cat.nome, '—') AS nome_categoria,
                       IFNULL(st.nome, 'Ativo') AS nome_status
                {from_join} {where}
                ORDER BY {campo_sql} {direcao_sql}""",
            params
        )
        bens = cursor.fetchall() or []

        # Totais agregados
        cursor.execute(
            f"""SELECT IFNULL(SUM(p.valor_atual), 0) AS vtc,
                       IFNULL(SUM(p.valor_atual), 0) AS vta,
                       COUNT(DISTINCT p.id_categoria) AS cats
                {from_join} {where}""",
            params
        )
        agg = cursor.fetchone() or {"vtc": 0, "vta": 0, "cats": 0}

        fotos_db = _ler_fotos_json()
        for bem in bens:
            extra, desc_limpa = _extrair_extra_descricao(bem.get("descricao") or "")
            bem["codigo_nacional"] = extra.get("codigo_nacional", "")
            bem["responsavel"] = extra.get("responsavel", "")
            bem["contato_responsavel"] = extra.get("contato", "")
            bem["descricao"] = desc_limpa
            bem["valor_atual"] = patrimonio_service.calcular_depreciacao(
                bem["valor_compra"], bem["data_aquisicao"], bem["taxa_depreciacao"]
            )
            bem["valor_compra"] = float(bem["valor_compra"] or 0)
            bem["valor_atual"] = float(bem["valor_atual"] or 0)
            bem["foi_baixado"] = bem["processo_baixa"] is not None
            chave = str(bem["id_patrimonio"])
            fotos = fotos_db.get(chave, [])
            bem["total_fotos"] = len(fotos)
            bem["primeira_foto"] = fotos[0]["caminho"] if fotos else None

        return jsonify({
            "total": total,
            "valor_total_compra": round(float(agg["vtc"] or 0), 2),
            "valor_total_atual": round(float(agg["vta"] or 0), 2),
            "categorias_distintas": int(agg["cats"] or 0),
            "bens": bens,
        })

    except mysql.connector.Error as err:
        import traceback
        traceback.print_exc()
        return jsonify({"erro": str(err), "codigo": getattr(err, "errno", None)}), 500
    finally:
        cursor.close()
        conn.close()


# ==========================================
# MÓDULO - FOTOS E EXTRAS DO PATRIMÔNIO
# ==========================================
@app.route("/api/patrimonio/<int:id_patrimonio>/detalhes", methods=["GET"])
def api_patrimonio_detalhes(id_patrimonio):
    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""SELECT p.id_patrimonio, p.nome, p.numero_patrimonio, p.valor_atual,
                                 p.descricao, p.nota_fiscal, p.data_aquisicao, p.taxa_depreciacao,
                                 p.processo_baixa, p.origem,
                                 DATE_FORMAT(p.data_aquisicao, '%Y-%m-%d') AS data_iso,
                                 DATE_FORMAT(p.data_aquisicao, '%d/%m/%Y') AS data_formatada,
                                 IFNULL(s.numero_sala, 'Não Alocado') AS nome_sala,
                                 s.bloco AS bloco_sala,
                                 IFNULL(cat.nome, '—') AS nome_categoria,
                                 IFNULL(st.nome, 'Ativo') AS nome_status
                          FROM Patrimonio p
                          LEFT JOIN Sala s ON p.id_sala = s.id_sala
                          LEFT JOIN Categoria cat ON p.id_categoria = cat.id_categoria
                          LEFT JOIN _status st ON p.id_status = st.id_status
                          WHERE p.id_patrimonio = %s""", (id_patrimonio,))
        bem = cursor.fetchone()
        if not bem:
            return jsonify({"erro": "Patrimônio não encontrado."}), 404
        extra, desc_limpa = _extrair_extra_descricao(bem.get("descricao") or "")
        bem["codigo_nacional"] = extra.get("codigo_nacional", "")
        bem["responsavel"] = extra.get("responsavel", "")
        bem["contato_responsavel"] = extra.get("contato", "")
        bem["descricao_limpa"] = desc_limpa
        bem["descricao"] = desc_limpa
        bem["valor_atual"] = float(bem["valor_atual"] or 0)
        fotos_db = _ler_fotos_json()
        bem["fotos"] = fotos_db.get(str(id_patrimonio), [])
        return jsonify(bem)
    except mysql.connector.Error as err:
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close(); conn.close()


@app.route("/api/patrimonio/<int:id_patrimonio>/foto", methods=["POST"])
@admin_required
def api_patrimonio_upload_foto(id_patrimonio):
    if "foto" not in request.files:
        return jsonify({"erro": "Nenhum arquivo enviado."}), 400
    foto = request.files["foto"]
    if foto.filename == "":
        return jsonify({"erro": "Arquivo vazio."}), 400

    ext = os.path.splitext(foto.filename)[1].lower()
    if ext not in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
        return jsonify({"erro": "Formato não aceito."}), 400

    # 🆕 Valida o conteúdo REAL do arquivo
    if not _validar_imagem_real(foto.stream):
        return jsonify({"erro": "Arquivo não é uma imagem válida."}), 400
    foto.seek(0)

    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id_patrimonio, numero_patrimonio FROM Patrimonio WHERE id_patrimonio = %s", (id_patrimonio,))
        bem = cursor.fetchone()
        if not bem:
            return jsonify({"erro": "Patrimônio não encontrado."}), 404
    finally:
        cursor.close(); conn.close()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    nome_unico = f"{id_patrimonio}_{bem['numero_patrimonio']}_{timestamp}_{uuid.uuid4().hex[:6]}{ext}"
    caminho_fisico = os.path.join(PASTA_FOTOS, nome_unico)
    foto.save(caminho_fisico)

    fotos_db = _ler_fotos_json()
    chave = str(id_patrimonio)
    if chave not in fotos_db:
        fotos_db[chave] = []
    fotos_db[chave].append({"id": uuid.uuid4().hex, "arquivo": nome_unico,
                            "caminho": f"uploads/patrimonios/{nome_unico}",
                            "nome_original": foto.filename,
                            "data_upload": datetime.now().strftime("%d/%m/%Y %H:%M"),
                            "tamanho_kb": round(os.path.getsize(caminho_fisico) / 1024, 1)})
    _salvar_fotos_json(fotos_db)

    try:
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("""INSERT INTO Log_auditoria (acao, descricao, id_usuario)
                          VALUES ('INSERT', %s, %s)""",
                       (f"Foto adicionada ao patrimônio #{id_patrimonio}", session['id_usuario']))
        conn.commit(); cursor.close(); conn.close()
    except Exception:
        pass

    return jsonify({"sucesso": True, "mensagem": "Foto adicionada!", "foto": fotos_db[chave][-1]})


@app.route("/api/patrimonio/<int:id_patrimonio>/foto/<foto_id>", methods=["DELETE"])
@admin_required
def api_patrimonio_excluir_foto(id_patrimonio, foto_id):
    fotos_db = _ler_fotos_json()
    chave = str(id_patrimonio)
    if chave not in fotos_db:
        return jsonify({"erro": "Nenhuma foto encontrada."}), 404
    encontrada = None
    restantes = []
    for f in fotos_db[chave]:
        if f["id"] == foto_id: encontrada = f
        else: restantes.append(f)
    if not encontrada:
        return jsonify({"erro": "Foto não encontrada."}), 404
    cam = os.path.join(PASTA_FOTOS, encontrada["arquivo"])
    if os.path.exists(cam):
        try: os.remove(cam)
        except OSError: pass
    fotos_db[chave] = restantes
    _salvar_fotos_json(fotos_db)
    return jsonify({"sucesso": True, "mensagem": "Foto removida!"})


@app.route("/api/patrimonio/<int:id_patrimonio>/extra", methods=["POST"])
@admin_required
def api_patrimonio_salvar_extra(id_patrimonio):
    codigo_nacional = (request.form.get("codigo_nacional") or "").strip()
    responsavel = (request.form.get("responsavel") or "").strip()
    contato = (request.form.get("contato") or "").strip()

    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT descricao FROM Patrimonio WHERE id_patrimonio = %s", (id_patrimonio,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"erro": "Patrimônio não encontrado."}), 404
        extra_atual, desc_limpa = _extrair_extra_descricao(row.get("descricao") or "")
        extra_atual["codigo_nacional"] = codigo_nacional
        extra_atual["responsavel"] = responsavel
        extra_atual["contato"] = contato
        nova_descricao = _montar_descricao_com_extra(desc_limpa, extra_atual)
        cursor.execute("UPDATE Patrimonio SET descricao = %s WHERE id_patrimonio = %s",
                       (nova_descricao, id_patrimonio))
        cursor.execute("""INSERT INTO Log_auditoria (acao, descricao, id_usuario)
                          VALUES ('UPDATE', %s, %s)""",
                       (f"Extras atualizados no patrimônio #{id_patrimonio}", session['id_usuario']))
        conn.commit()
        return jsonify({"sucesso": True, "mensagem": "Informações salvas!"})
    except mysql.connector.Error as err:
        conn.rollback()
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close(); conn.close()


# ==========================================
# MÓDULO - IMPORTAÇÃO EM LOTE (CSV)
# ==========================================
@app.route("/api/inventario/modelo-csv", methods=["GET"])
def api_inventario_modelo_csv():
    output = io.StringIO()
    output.write("# MODELO DE IMPORTAÇÃO EM LOTE - IPE\n")
    output.write("# Colunas OBRIGATÓRIAS: nome, numero_patrimonio, valor_compra, data_aquisicao\n")
    output.write("# Colunas OPCIONAIS: taxa_depreciacao, id_sala, id_categoria, codigo_nacional, responsavel, contato, nota_fiscal, descricao\n")
    output.write("# Formato de data: AAAA-MM-DD\n\n")

    cabecalho = ["nome", "numero_patrimonio", "valor_compra", "data_aquisicao",
                 "taxa_depreciacao", "id_sala", "id_categoria",
                 "codigo_nacional", "responsavel", "contato",
                 "nota_fiscal", "descricao"]
    output.write(";".join(cabecalho) + "\n")

    exemplos = [
        ["Projetor Epson EB-2250U", "20261001", "4500.00", "2026-01-15", "15.0", "10", "5", "INEP-12345", "João Silva", "joao@ipe.edu.br", "NF-99441", "Projetor da sala 101"],
        ["Notebook Dell Inspiron", "20261002", "3500.00", "2026-02-20", "20.0", "20", "6", "INEP-12346", "Maria Oliveira", "maria@ipe.edu.br", "NF-99500", "Notebook do laboratório"],
    ]
    for linha in exemplos:
        output.write(";".join(linha) + "\n")

    csv_bytes = output.getvalue().encode("utf-8-sig")
    return send_file(io.BytesIO(csv_bytes), mimetype="text/csv", as_attachment=True,
                     download_name=f"modelo_importacao_ipe_{datetime.now().strftime('%Y%m%d')}.csv")


@app.route("/api/inventario/importar-validar", methods=["POST"])
@admin_required
def api_inventario_importar_validar():
    if "arquivo" not in request.files:
        return jsonify({"erro": "Nenhum arquivo enviado."}), 400
    arquivo = request.files["arquivo"]
    if arquivo.filename == "":
        return jsonify({"erro": "Arquivo vazio."}), 400

    try:
        conteudo = arquivo.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            conteudo = arquivo.read().decode("latin-1")
        except Exception as e:
            return jsonify({"erro": f"Erro ao ler: {e}"}), 400

    primeira = conteudo.split("\n")[0] if conteudo else ""
    separador = ";" if primeira.count(";") >= primeira.count(",") else ","

    linhas = [l.strip() for l in conteudo.split("\n") if l.strip() and not l.strip().startswith("#")]
    if len(linhas) < 2:
        return jsonify({"erro": "Precisa ter cabeçalho + 1 linha."}), 400

    leitor = csv.DictReader(io.StringIO("\n".join(linhas)), delimiter=separador)
    cabecalho_original = leitor.fieldnames or []
    cabecalho = [c.strip().lower() for c in cabecalho_original]
    obrigatorias = ["nome", "numero_patrimonio", "valor_compra", "data_aquisicao"]

    faltando = [c for c in obrigatorias if c not in cabecalho]
    if faltando:
        return jsonify({"erro": f"Faltando: {', '.join(faltando)}", "cabecalho_encontrado": cabecalho}), 400

    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id_sala, numero_sala, bloco FROM Sala")
        salas_db = {s["id_sala"]: f"{s['numero_sala']}{(' · ' + s['bloco']) if s['bloco'] else ''}" for s in cursor.fetchall()}
        cursor.execute("SELECT id_categoria, nome FROM Categoria")
        cats_db = {c["id_categoria"]: c["nome"] for c in cursor.fetchall()}
        cursor.execute("SELECT numero_patrimonio FROM Patrimonio")
        existentes = {str(r["numero_patrimonio"]) for r in cursor.fetchall()}
        cursor.execute("SELECT id_categoria FROM Categoria LIMIT 1")
        cat_p = cursor.fetchone()
        id_cat_padrao = cat_p["id_categoria"] if cat_p else None
    finally:
        cursor.close(); conn.close()

    linhas_validadas = []
    erros = []
    avisos = []
    nums_no_csv = set()

    for idx, row in enumerate(leitor, start=2):
        dados = {}
        for k_orig, k_norm in zip(cabecalho_original, cabecalho):
            dados[k_norm] = (row.get(k_orig) or "").strip()
        erros_l = []
        avisos_l = []

        if not dados.get("nome"): erros_l.append("Nome vazio")

        num_str = dados.get("numero_patrimonio", "")
        if not num_str: erros_l.append("Nº vazio")
        else:
            num_limpo = ''.join(filter(str.isdigit, num_str))
            if not num_limpo: erros_l.append(f"Nº '{num_str}' inválido")
            else:
                dados["numero_patrimonio"] = int(num_limpo)
                if num_limpo in nums_no_csv: erros_l.append(f"Nº {num_limpo} duplicado no CSV")
                nums_no_csv.add(num_limpo)

        valor_str = dados.get("valor_compra", "").replace(",", ".")
        try:
            valor = float(valor_str)
            if valor < 0: raise ValueError()
            dados["valor_compra"] = valor
        except (ValueError, TypeError):
            erros_l.append(f"Valor '{valor_str}' inválido")

        data_str = dados.get("data_aquisicao", "")
        try:
            datetime.strptime(data_str, "%Y-%m-%d")
            dados["data_aquisicao"] = data_str
        except ValueError:
            try:
                dt = datetime.strptime(data_str, "%d/%m/%Y")
                dados["data_aquisicao"] = dt.strftime("%Y-%m-%d")
                avisos_l.append(f"Data convertida de {data_str}")
            except ValueError:
                erros_l.append(f"Data '{data_str}' inválida")

        taxa_str = dados.get("taxa_depreciacao", "").replace(",", ".")
        if taxa_str:
            try:
                taxa = float(taxa_str)
                if taxa < 0 or taxa > 100: raise ValueError()
                dados["taxa_depreciacao"] = taxa
            except ValueError:
                avisos_l.append("Taxa inválida, usando 10.0")
                dados["taxa_depreciacao"] = 10.0
        else:
            dados["taxa_depreciacao"] = 10.0

        sala_str = dados.get("id_sala", "")
        if sala_str:
            try:
                id_sala = int(sala_str)
                if id_sala in salas_db:
                    dados["id_sala"] = id_sala
                    dados["sala_nome"] = salas_db[id_sala]
                else:
                    avisos_l.append(f"Sala #{id_sala} não existe")
                    dados["id_sala"] = None
                    dados["sala_nome"] = "Não Alocado"
            except ValueError:
                avisos_l.append("Sala inválida")
                dados["id_sala"] = None
                dados["sala_nome"] = "Não Alocado"
        else:
            dados["id_sala"] = None
            dados["sala_nome"] = "Não Alocado"

        cat_str = dados.get("id_categoria", "")
        if cat_str:
            try:
                id_cat = int(cat_str)
                if id_cat in cats_db:
                    dados["id_categoria"] = id_cat
                    dados["categoria_nome"] = cats_db[id_cat]
                else:
                    avisos_l.append(f"Categoria #{id_cat} não existe")
                    dados["id_categoria"] = id_cat_padrao
                    dados["categoria_nome"] = cats_db.get(id_cat_padrao, "—")
            except ValueError:
                avisos_l.append("Categoria inválida")
                dados["id_categoria"] = id_cat_padrao
                dados["categoria_nome"] = cats_db.get(id_cat_padrao, "—")
        else:
            dados["id_categoria"] = id_cat_padrao
            dados["categoria_nome"] = cats_db.get(id_cat_padrao, "—")

        if dados.get("numero_patrimonio"):
            if str(dados["numero_patrimonio"]) in existentes:
                dados["ja_existe"] = True
                avisos_l.append(f"Nº {dados['numero_patrimonio']} já existe — será ATUALIZADO")
            else:
                dados["ja_existe"] = False

        status = "erro" if erros_l else ("aviso" if avisos_l else "ok")
        linhas_validadas.append({"linha": idx, "status": status, "dados": dados,
                                 "erros": erros_l, "avisos": avisos_l})
        if erros_l: erros.append({"linha": idx, "mensagem": "; ".join(erros_l)})
        if avisos_l: avisos.append({"linha": idx, "mensagem": "; ".join(avisos_l)})

    total = len(linhas_validadas)
    com_erro = sum(1 for l in linhas_validadas if l["status"] == "erro")
    com_aviso = sum(1 for l in linhas_validadas if l["status"] == "aviso")
    ok = sum(1 for l in linhas_validadas if l["status"] == "ok")

    return jsonify({"sucesso": True, "separador_detectado": separador,
                    "total_linhas": total, "linhas_ok": ok,
                    "linhas_com_aviso": com_aviso, "linhas_com_erro": com_erro,
                    "pode_importar": com_erro == 0,
                    "linhas": linhas_validadas, "erros": erros, "avisos": avisos})


@app.route("/api/inventario/importar-confirmar", methods=["POST"])
@admin_required
def api_inventario_importar_confirmar():
    dados = request.get_json(silent=True) or {}
    linhas = dados.get("linhas", [])
    if not linhas:
        return jsonify({"erro": "Nenhuma linha para importar."}), 400

    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    inseridos = 0
    atualizados = 0
    erros_gravacao = []

    try:
        for item in linhas:
            if item.get("status") == "erro": continue
            d = item.get("dados", {})
            num = d.get("numero_patrimonio")
            if not num: continue

            extra_dict = {}
            if d.get("codigo_nacional"): extra_dict["codigo_nacional"] = d["codigo_nacional"]
            if d.get("responsavel"): extra_dict["responsavel"] = d["responsavel"]
            if d.get("contato"): extra_dict["contato"] = d["contato"]

            desc_base = d.get("descricao", "")
            desc_final = _montar_descricao_com_extra(desc_base, extra_dict)

            try:
                if d.get("ja_existe"):
                    cursor.execute("""UPDATE Patrimonio
                                      SET nome = %s, valor_atual = %s, data_aquisicao = %s,
                                          taxa_depreciacao = %s, id_sala = %s, id_categoria = %s,
                                          nota_fiscal = %s, descricao = %s
                                      WHERE numero_patrimonio = %s""",
                                   (d["nome"], d["valor_compra"], d["data_aquisicao"],
                                    d["taxa_depreciacao"], d.get("id_sala"), d["id_categoria"],
                                    d.get("nota_fiscal") or None, desc_final, num))
                    atualizados += 1
                else:
                    cursor.execute("""INSERT INTO Patrimonio (nome, numero_patrimonio, valor_atual,
                                                                data_aquisicao, taxa_depreciacao,
                                                                id_sala, id_categoria, id_status,
                                                                nota_fiscal, descricao)
                                      VALUES (%s, %s, %s, %s, %s, %s, %s, 1, %s, %s)""",
                                   (d["nome"], num, d["valor_compra"], d["data_aquisicao"],
                                    d["taxa_depreciacao"], d.get("id_sala"), d["id_categoria"],
                                    d.get("nota_fiscal") or None, desc_final))
                    inseridos += 1
            except mysql.connector.Error as e:
                erros_gravacao.append({"linha": item.get("linha"), "numero": num, "mensagem": str(e)})

        cursor.execute("""INSERT INTO Log_auditoria (acao, descricao, id_usuario)
                          VALUES ('INSERT', %s, %s)""",
                       (f"Importação em lote: {inseridos} criado(s), {atualizados} atualizado(s)",
                        session['id_usuario']))
        conn.commit()
        return jsonify({"sucesso": True, "inseridos": inseridos, "atualizados": atualizados,
                        "erros": erros_gravacao,
                        "mensagem": f"Importação concluída! {inseridos} criado(s), {atualizados} atualizado(s)."})
    except mysql.connector.Error as err:
        conn.rollback()
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close(); conn.close()


# ==========================================
# MÓDULO - RELATÓRIOS
# ==========================================
@app.route("/api/relatorios/resumo", methods=["GET"])
@patrimonio_required
def api_relatorios_resumo():
    ano = request.args.get("ano", datetime.now().year, type=int)
    periodo = request.args.get("periodo", "bimestral").lower()

    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    resultado = {"ano": ano, "periodo": periodo,
                 "resumo_geral": {"total_entradas": 0.0, "total_saidas": 0.0, "saldo": 0.0, "total_movimentacoes": 0},
                 "por_origem": [], "por_categoria": [], "por_periodo": [], "detalhamento": []}
    try:
        cursor.execute("""SELECT SUM(CASE WHEN tipo_movimento = 'Receita' THEN valor ELSE 0 END) AS entradas,
                                 SUM(CASE WHEN tipo_movimento = 'Despesa' THEN valor ELSE 0 END) AS saidas,
                                 COUNT(*) AS total
                          FROM Lancamento_caixa WHERE YEAR(data_lancamento) = %s""", (ano,))
        row = cursor.fetchone()
        resultado["resumo_geral"]["total_entradas"] = float(row["entradas"] or 0)
        resultado["resumo_geral"]["total_saidas"] = float(row["saidas"] or 0)
        resultado["resumo_geral"]["saldo"] = round(resultado["resumo_geral"]["total_entradas"] -
                                                   resultado["resumo_geral"]["total_saidas"], 2)
        resultado["resumo_geral"]["total_movimentacoes"] = int(row["total"] or 0)

        cursor.execute("""SELECT MONTH(data_lancamento) AS mes,
                                 SUM(CASE WHEN tipo_movimento = 'Receita' THEN valor ELSE 0 END) AS entradas,
                                 SUM(CASE WHEN tipo_movimento = 'Despesa' THEN valor ELSE 0 END) AS saidas,
                                 COUNT(*) AS total
                          FROM Lancamento_caixa WHERE YEAR(data_lancamento) = %s
                          GROUP BY MONTH(data_lancamento) ORDER BY mes ASC""", (ano,))
        meses = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
        for m in cursor.fetchall():
            resultado["por_periodo"].append({"mes": m["mes"], "mes_nome": meses[m["mes"]-1],
                                              "entradas": float(m["entradas"] or 0),
                                              "saidas": float(m["saidas"] or 0),
                                              "saldo": round(float(m["entradas"] or 0) - float(m["saidas"] or 0), 2),
                                              "total_movimentacoes": int(m["total"] or 0)})

        cursor.execute("""SELECT lc.tipo_movimento, lc.valor, v.nome AS verba_nome
                          FROM Lancamento_caixa lc
                          LEFT JOIN Despesa d ON d.id_lancamento = lc.id_lancamento
                          LEFT JOIN verba v ON v.id_verba = d.id_verba
                          WHERE YEAR(lc.data_lancamento) = %s""", (ano,))
        od = {}
        for l in cursor.fetchall():
            origem, _ = _extrair_origem_verba(l.get("verba_nome") or "")
            chave = origem if origem in ORIGENS_VALIDAS else "SEM_ORIGEM"
            if chave not in od:
                info = ORIGENS_VALIDAS.get(origem, {})
                od[chave] = {"id": chave, "nome": info.get("nome", "Sem Origem"),
                             "cor": info.get("cor", "#9ca3af"), "icone": info.get("icone", "❓"),
                             "entradas": 0.0, "saidas": 0.0}
            val = float(l["valor"] or 0)
            if l["tipo_movimento"] == "Receita": od[chave]["entradas"] += val
            else: od[chave]["saidas"] += val
        for o in od.values():
            o["saldo"] = round(o["entradas"] - o["saidas"], 2)
            o["entradas"] = round(o["entradas"], 2)
            o["saidas"] = round(o["saidas"], 2)
        resultado["por_origem"] = list(od.values())

        cursor.execute("""SELECT IFNULL(d.categoria, 'Sem categoria') AS categoria,
                                 SUM(lc.valor) AS total, COUNT(*) AS qtd
                          FROM Lancamento_caixa lc
                          LEFT JOIN Despesa d ON d.id_lancamento = lc.id_lancamento
                          WHERE YEAR(lc.data_lancamento) = %s AND lc.tipo_movimento = 'Despesa'
                          GROUP BY d.categoria ORDER BY total DESC LIMIT 15""", (ano,))
        for c in cursor.fetchall():
            resultado["por_categoria"].append({"categoria": c["categoria"] or "Sem categoria",
                                                "total": float(c["total"] or 0),
                                                "quantidade": int(c["qtd"] or 0)})

        if periodo == "mensal": np, div = 12, 1
        elif periodo == "bimestral": np, div = 6, 2
        elif periodo == "trimestral": np, div = 4, 3
        elif periodo == "semestral": np, div = 2, 6
        else: np, div = 1, 12

        for i in range(np):
            mi, mf = (i * div) + 1, (i + 1) * div
            if periodo == "anual": label = f"Ano {ano}"
            elif periodo == "semestral": label = f"{i+1}º Semestre"
            elif periodo == "trimestral": label = f"{i+1}º Trimestre"
            elif periodo == "bimestral": label = f"{i+1}º Bimestre"
            else: label = meses[mi - 1]

            cursor.execute("""SELECT SUM(CASE WHEN tipo_movimento = 'Receita' THEN valor ELSE 0 END) AS entradas,
                                     SUM(CASE WHEN tipo_movimento = 'Despesa' THEN valor ELSE 0 END) AS saidas,
                                     COUNT(*) AS qtd
                              FROM Lancamento_caixa
                              WHERE YEAR(data_lancamento) = %s AND MONTH(data_lancamento) BETWEEN %s AND %s""",
                           (ano, mi, mf))
            r = cursor.fetchone()
            ent, sai = float(r["entradas"] or 0), float(r["saidas"] or 0)
            resultado["detalhamento"].append({"label": label, "mes_ini": mi, "mes_fim": mf,
                                               "entradas": round(ent, 2), "saidas": round(sai, 2),
                                               "saldo": round(ent - sai, 2),
                                               "movimentacoes": int(r["qtd"] or 0)})
    except mysql.connector.Error as err:
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close(); conn.close()
    return jsonify(resultado)


@app.route("/api/relatorios/exportar-csv", methods=["GET"])
@patrimonio_required
def api_relatorios_exportar_csv():
    ano = request.args.get("ano", datetime.now().year, type=int)
    periodo = request.args.get("periodo", "bimestral").lower()

    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    output = io.StringIO()
    try:
        output.write(f"RELATORIO FINANCEIRO IPE - {periodo.upper()} - {ano}\n")
        output.write(f"Gerado em;{datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n")
        cursor.execute("""SELECT SUM(CASE WHEN tipo_movimento = 'Receita' THEN valor ELSE 0 END) AS entradas,
                                 SUM(CASE WHEN tipo_movimento = 'Despesa' THEN valor ELSE 0 END) AS saidas,
                                 COUNT(*) AS total
                          FROM Lancamento_caixa WHERE YEAR(data_lancamento) = %s""", (ano,))
        r = cursor.fetchone()
        ent, sai = float(r["entradas"] or 0), float(r["saidas"] or 0)
        output.write("RESUMO GERAL\nItem;Valor\n")
        output.write(f"Total de Entradas;{ent:.2f}\nTotal de Saídas;{sai:.2f}\n")
        output.write(f"Saldo;{(ent-sai):.2f}\nTotal de Movimentações;{r['total']}\n\n")

        cursor.execute("""SELECT MONTH(data_lancamento) AS mes,
                                 SUM(CASE WHEN tipo_movimento = 'Receita' THEN valor ELSE 0 END) AS entradas,
                                 SUM(CASE WHEN tipo_movimento = 'Despesa' THEN valor ELSE 0 END) AS saidas,
                                 COUNT(*) AS qtd
                          FROM Lancamento_caixa WHERE YEAR(data_lancamento) = %s
                          GROUP BY MONTH(data_lancamento) ORDER BY mes ASC""", (ano,))
        output.write("DETALHAMENTO MENSAL\nMes;Entradas;Saidas;Saldo;Movimentacoes\n")
        meses = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
                 "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
        for m in cursor.fetchall():
            e, s = float(m["entradas"] or 0), float(m["saidas"] or 0)
            output.write(f"{meses[m['mes']-1]};{e:.2f};{s:.2f};{(e-s):.2f};{m['qtd']}\n")
    except mysql.connector.Error as err:
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close(); conn.close()

    csv_bytes = output.getvalue().encode("utf-8-sig")
    nome = f"relatorio_{periodo}_{ano}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    try:
        with open(os.path.join(app.config['BACKUP_FOLDER'], nome), "wb") as f:
            f.write(csv_bytes)
    except Exception:
        pass
    return send_file(io.BytesIO(csv_bytes), mimetype="text/csv", as_attachment=True, download_name=nome)



def _gerar_excel_relatorio(dados, lancamentos=None):
    """
    Monta o relatório financeiro IPE em Excel.
    dados: retorno de api_relatorios_resumo() (dict).
    lancamentos: lista de dicts com data(datetime), tipo, descricao, origem, verba,
                 categoria, forma, doc, status, valor. Pode ser None/vazia.
    Retorna os bytes do .xlsx.
    """
    import io
    from datetime import datetime
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.chart import BarChart, LineChart, Reference
    from openpyxl.formatting.rule import DataBarRule, ColorScaleRule, CellIsRule, FormulaRule
    from openpyxl.worksheet.properties import PageSetupProperties

    lancamentos = lancamentos or []
    ano, periodo = dados["ano"], dados["periodo"]
    MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
             "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]

    # ---------------- PALETA ----------------
    NAVY, NAVY_LIGHT, BORDER, ZEBRA, WHITE = "1F2937", "374151", "D1D5DB", "F9FAFB", "FFFFFF"
    GREEN, GREEN_BG = "047857", "ECFDF5"
    RED, RED_BG = "B91C1C", "FEF2F2"
    BLUE, BLUE_BG = "1D4ED8", "EFF6FF"
    AMBER, AMBER_BG = "B45309", "FFFBEB"
    GRAY, GRAY_BG = "6B7280", "F3F4F6"
    ACCENT = "F29310"   # laranja IPE

    FONT = "Calibri"
    fmt_brl = 'R$ #,##0.00;[Red]-R$ #,##0.00;"–"'
    fmt_brl_plain = 'R$ #,##0.00;[Red]-R$ #,##0.00'
    fmt_pct = '0.0%'
    fmt_int = '#,##0;-#,##0;"–"'
    fmt_date = 'dd/mm/yyyy'

    thin = Side(style="thin", color=BORDER)
    borda = Border(left=thin, right=thin, top=thin, bottom=thin)

    # ---------------- HELPERS ----------------
    def fill(c):
        return PatternFill("solid", fgColor=c)

    def header_cell(cell, value=None):
        if value is not None:
            cell.value = value
        cell.fill = fill(NAVY)
        cell.font = Font(name=FONT, size=10, bold=True, color=WHITE)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = borda

    def body_cell(cell, value=None, fmt=None, align="left", zebra=False, bold=False, color=None):
        if value is not None:
            cell.value = value
        cell.font = Font(name=FONT, size=10, bold=bold, color=color or "111827")
        cell.alignment = Alignment(horizontal=align, vertical="center",
                                   indent=1 if align == "left" else 0)
        cell.border = borda
        cell.fill = fill(ZEBRA if zebra else WHITE)
        if fmt:
            cell.number_format = fmt

    def total_cell(cell, value=None, fmt=None, align="right"):
        if fmt == fmt_brl_plain:
            fmt = 'R$ #,##0.00;-R$ #,##0.00'   # sem [Red]: vermelho some no fundo escuro
        if value is not None:
            cell.value = value
        cell.fill = fill(NAVY)
        cell.font = Font(name=FONT, size=10, bold=True, color=WHITE)
        cell.border = borda
        cell.alignment = Alignment(horizontal=align, vertical="center",
                                   indent=1 if align == "left" else 0)
        if fmt:
            cell.number_format = fmt

    def widths(ws, ws_widths):
        for i, w in enumerate(ws_widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w

    def title_block(ws, col_ini, col_fim, titulo, subtitulo=""):
        ws.merge_cells(start_row=1, start_column=col_ini, end_row=1, end_column=col_fim)
        c = ws.cell(row=1, column=col_ini, value=titulo)
        c.fill = fill(NAVY)
        c.font = Font(name=FONT, size=15, bold=True, color=WHITE)
        c.alignment = Alignment(horizontal="left", vertical="center", indent=1)
        for col in range(col_ini, col_fim + 1):
            ws.cell(row=1, column=col).fill = fill(NAVY)
            ws.cell(row=2, column=col).border = Border(top=Side(style="medium", color=ACCENT))
        ws.row_dimensions[1].height = 32
        if subtitulo:
            ws.merge_cells(start_row=2, start_column=col_ini, end_row=2, end_column=col_fim)
            c2 = ws.cell(row=2, column=col_ini, value=subtitulo)
            c2.font = Font(name=FONT, size=9, italic=True, color=GRAY)
            c2.alignment = Alignment(horizontal="left", vertical="center", indent=1)
            ws.row_dimensions[2].height = 20

    def section(ws, row, col_ini, col_fim, texto):
        ws.merge_cells(start_row=row, start_column=col_ini, end_row=row, end_column=col_fim)
        c = ws.cell(row=row, column=col_ini, value=texto)
        c.font = Font(name=FONT, size=11, bold=True, color=NAVY)
        c.alignment = Alignment(horizontal="left", vertical="center")
        for col in range(col_ini, col_fim + 1):
            ws.cell(row=row, column=col).border = Border(bottom=Side(style="medium", color=ACCENT))
        ws.row_dimensions[row].height = 22

    def kpi(ws, row, col_ini, col_fim, titulo, valor, fmt, cor, bg, size=16):
        if col_fim > col_ini:
            ws.merge_cells(start_row=row, start_column=col_ini, end_row=row, end_column=col_fim)
            ws.merge_cells(start_row=row + 1, start_column=col_ini, end_row=row + 1, end_column=col_fim)
        ct = ws.cell(row=row, column=col_ini, value=titulo)
        cv = ws.cell(row=row + 1, column=col_ini, value=valor)
        for col in range(col_ini, col_fim + 1):
            ws.cell(row=row, column=col).fill = fill(NAVY_LIGHT)
            ws.cell(row=row, column=col).border = borda
            ws.cell(row=row + 1, column=col).fill = fill(bg)
            ws.cell(row=row + 1, column=col).border = borda
        ct.font = Font(name=FONT, size=8, bold=True, color=WHITE)
        ct.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cv.font = Font(name=FONT, size=size, bold=True, color=cor)
        cv.alignment = Alignment(horizontal="center", vertical="center")
        if fmt:
            cv.number_format = fmt
        ws.row_dimensions[row].height = 22
        ws.row_dimensions[row + 1].height = 34

    def imprimir(ws, titulo_linhas=None):
        ws.page_setup.orientation = "landscape"
        ws.page_setup.paperSize = ws.PAPERSIZE_A4
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
        ws.print_options.horizontalCentered = True
        ws.page_margins.left = ws.page_margins.right = 0.4
        ws.page_margins.top = 0.6
        ws.page_margins.bottom = 0.7
        ws.oddFooter.left.text = f"IPE — Relatório Financeiro {ano}"
        ws.oddFooter.left.size = 8
        ws.oddFooter.right.text = "Página &P de &N"
        ws.oddFooter.right.size = 8
        if titulo_linhas:
            ws.print_title_rows = titulo_linhas

    gerado_em = datetime.now().strftime("%d/%m/%Y %H:%M")
    rotulo_periodo = {"mensal": "Mensal", "bimestral": "Bimestral", "trimestral": "Trimestral",
                      "semestral": "Semestral", "anual": "Anual"}.get(periodo, periodo.capitalize())

    # ======================================================================
    # WORKBOOK + ABAS (criadas na ordem de exibição)
    # ======================================================================
    wb = Workbook()
    ws1 = wb.active
    ws1.title = "Resumo Executivo"
    ws3 = wb.create_sheet("Análise Mensal")
    ws2 = wb.create_sheet("Detalhamento")
    por_origem = sorted(dados.get("por_origem") or [],
                        key=lambda o: o["entradas"] + o["saidas"], reverse=True)
    por_categoria = dados.get("por_categoria") or []
    ws4 = wb.create_sheet("Por Origem") if por_origem else None
    ws5 = wb.create_sheet("Por Categoria") if por_categoria else None
    ws6 = wb.create_sheet("Lançamentos") if lancamentos else None

    for ws, cor in ((ws1, NAVY), (ws3, BLUE), (ws2, GRAY), (ws4, "6B21A8"), (ws5, GREEN), (ws6, ACCENT)):
        if ws is not None:
            ws.sheet_view.showGridLines = False
            ws.sheet_properties.tabColor = cor

    wb.properties.title = f"IPE — Relatório Financeiro {ano}"
    wb.properties.creator = "IPE - Sistema de Inventário"
    wb.calculation.fullCalcOnLoad = True

    # ======================================================================
    # ABA ANÁLISE MENSAL  (12 meses sempre; fonte dos KPIs do Resumo)
    # ======================================================================
    M_HDR = 11
    M_INI = M_HDR + 1
    M_FIM = M_INI + 11
    M_TOT = M_FIM + 1
    SM = "'Análise Mensal'!"

    widths(ws3, [2, 16, 18, 18, 18, 18, 15, 14, 12, 2])
    title_block(ws3, 2, 9, "ANÁLISE MENSAL", f"Comparativo mês a mês · Exercício {ano} · Gerado em {gerado_em}")

    rg = lambda col: f"{col}{M_INI}:{col}{M_FIM}"
    ativo = f'{rg("G")},">0"'

    kpi(ws3, 4, 2, 3, "MÉDIA MENSAL DE ENTRADAS",
        f'=IFERROR(AVERAGEIF({rg("G")},">0",{rg("C")}),0)', fmt_brl_plain, GREEN, GREEN_BG, 13)
    kpi(ws3, 4, 4, 5, "MÉDIA MENSAL DE SAÍDAS",
        f'=IFERROR(AVERAGEIF({rg("G")},">0",{rg("D")}),0)', fmt_brl_plain, RED, RED_BG, 13)
    kpi(ws3, 4, 6, 7, "SALDO DO ANO", f"=E{M_TOT}", fmt_brl_plain, BLUE, BLUE_BG, 13)
    kpi(ws3, 4, 8, 9, "MESES NO AZUL",
        f'=IFERROR(COUNTIFS({rg("G")},">0",{rg("E")},">=0")/COUNTIF({rg("G")},">0"),0)',
        fmt_pct, GREEN, GREEN_BG, 13)
    kpi(ws3, 7, 2, 3, "MELHOR MÊS (SALDO)",
        f'=IF(COUNTIF({rg("G")},">0")=0,"—",INDEX({rg("B")},MATCH(_xlfn.MAXIFS({rg("E")},{rg("G")},">0"),{rg("E")},0)))',
        None, GREEN, GREEN_BG, 13)
    kpi(ws3, 7, 4, 5, "PIOR MÊS (SALDO)",
        f'=IF(COUNTIF({rg("G")},">0")=0,"—",INDEX({rg("B")},MATCH(_xlfn.MINIFS({rg("E")},{rg("G")},">0"),{rg("E")},0)))',
        None, RED, RED_BG, 13)
    kpi(ws3, 7, 6, 7, "MÊS DE MAIOR GASTO",
        f'=IF(COUNTIF({rg("G")},">0")=0,"—",INDEX({rg("B")},MATCH(MAX({rg("D")}),{rg("D")},0)))',
        None, AMBER, AMBER_BG, 13)
    kpi(ws3, 7, 8, 9, "SAÍDAS ÷ ENTRADAS", f"=IF(C{M_TOT}=0,0,D{M_TOT}/C{M_TOT})",
        fmt_pct, AMBER, AMBER_BG, 13)
    for r in (4, 7):
        ws3.row_dimensions[r].height = 20
        ws3.row_dimensions[r + 1].height = 28

    for i, h in enumerate(["Mês", "Entradas", "Saídas", "Saldo", "Saldo acumulado",
                           "Movimentações", "Saídas ÷ Entradas", "Tendência"], start=2):
        header_cell(ws3.cell(row=M_HDR, column=i, value=h))
    ws3.row_dimensions[M_HDR].height = 30

    por_mes = {m["mes"]: m for m in (dados.get("por_periodo") or [])}
    for idx in range(12):
        r = M_INI + idx
        m = por_mes.get(idx + 1, {"entradas": 0.0, "saidas": 0.0, "total_movimentacoes": 0})
        z = idx % 2 == 1
        body_cell(ws3.cell(row=r, column=2), MESES[idx], align="left", zebra=z, bold=True)
        body_cell(ws3.cell(row=r, column=3), m["entradas"], fmt_brl, "right", z, color=GREEN)
        body_cell(ws3.cell(row=r, column=4), m["saidas"], fmt_brl, "right", z, color=RED)
        body_cell(ws3.cell(row=r, column=5), f"=C{r}-D{r}", fmt_brl, "right", z, bold=True)
        body_cell(ws3.cell(row=r, column=6), f"=E{r}" if idx == 0 else f"=F{r-1}+E{r}",
                  fmt_brl, "right", z)
        body_cell(ws3.cell(row=r, column=7), m["total_movimentacoes"], fmt_int, "center", z, color=BLUE)
        body_cell(ws3.cell(row=r, column=8), f'=IF(C{r}=0,"—",D{r}/C{r})', fmt_pct, "center", z)
        if idx == 0:
            body_cell(ws3.cell(row=r, column=9), "—", align="center", zebra=z, bold=True, color=GRAY)
        else:
            body_cell(ws3.cell(row=r, column=9),
                      f'=IF(OR(G{r}=0,G{r-1}=0),"—",IF(E{r}>E{r-1},"▲",IF(E{r}<E{r-1},"▼","►")))',
                      align="center", zebra=z, bold=True, color=GRAY)
        ws3.row_dimensions[r].height = 22

    total_cell(ws3.cell(row=M_TOT, column=2), "TOTAL", align="left")
    total_cell(ws3.cell(row=M_TOT, column=3), f"=SUM({rg('C')})", fmt_brl_plain)
    total_cell(ws3.cell(row=M_TOT, column=4), f"=SUM({rg('D')})", fmt_brl_plain)
    total_cell(ws3.cell(row=M_TOT, column=5), f"=C{M_TOT}-D{M_TOT}", fmt_brl_plain)
    total_cell(ws3.cell(row=M_TOT, column=6), f"=F{M_FIM}", fmt_brl_plain)
    total_cell(ws3.cell(row=M_TOT, column=7), f"=SUM({rg('G')})", '#,##0', "center")
    total_cell(ws3.cell(row=M_TOT, column=8), f'=IF(C{M_TOT}=0,"—",D{M_TOT}/C{M_TOT})', fmt_pct, "center")
    total_cell(ws3.cell(row=M_TOT, column=9), "", None, "center")
    ws3.row_dimensions[M_TOT].height = 26

    # formatação condicional
    ws3.conditional_formatting.add(rg("C"), DataBarRule(start_type="num", start_value=0,
                                                         end_type="max", color="34D399", showValue=True))
    ws3.conditional_formatting.add(rg("D"), DataBarRule(start_type="num", start_value=0,
                                                         end_type="max", color="F87171", showValue=True))
    ws3.conditional_formatting.add(rg("E"), ColorScaleRule(start_type="min", start_color="FECACA",
                                                            mid_type="num", mid_value=0, mid_color="FFFFFF",
                                                            end_type="max", end_color="BBF7D0"))
    ws3.conditional_formatting.add(rg("I"), CellIsRule(operator="equal", formula=['"▲"'], font=Font(color=GREEN, bold=True)))
    ws3.conditional_formatting.add(rg("I"), CellIsRule(operator="equal", formula=['"▼"'], font=Font(color=RED, bold=True)))
    ws3.conditional_formatting.add(f"B{M_INI}:B{M_FIM}",
                                   FormulaRule(formula=[f"$G{M_INI}=0"], font=Font(color="9CA3AF")))
    ws3.freeze_panes = f"C{M_INI}"
    ws3.auto_filter.ref = f"B{M_HDR}:I{M_FIM}"

    # gráficos (dados 100% visíveis: Excel não plota colunas ocultas)
    cats = Reference(ws3, min_col=2, min_row=M_INI, max_row=M_FIM)
    ch = BarChart()
    ch.type, ch.style = "col", 10
    ch.title = f"Entradas × Saídas por mês ({ano})"
    ch.y_axis.title = "R$"
    ch.y_axis.number_format = 'R$ #,##0'
    ch.y_axis.delete = False
    ch.x_axis.delete = False
    ch.height, ch.width, ch.gapWidth, ch.overlap = 9, 22, 60, -10
    ch.add_data(Reference(ws3, min_col=3, max_col=4, min_row=M_HDR, max_row=M_FIM), titles_from_data=True)
    ch.set_categories(cats)
    for s, cor in zip(ch.series, (GREEN, RED)):
        s.graphicalProperties.solidFill = cor
        s.graphicalProperties.line.solidFill = cor
    ch.legend.position = "b"
    ws3.add_chart(ch, f"B{M_TOT + 2}")

    ln = LineChart()
    ln.title = f"Evolução do saldo acumulado ({ano})"
    ln.style = 12
    ln.y_axis.title = "R$"
    ln.y_axis.number_format = 'R$ #,##0'
    ln.y_axis.delete = False
    ln.x_axis.delete = False
    ln.height, ln.width = 8, 22
    ln.add_data(Reference(ws3, min_col=6, min_row=M_HDR, max_row=M_FIM), titles_from_data=True)
    ln.set_categories(cats)
    s = ln.series[0]
    s.graphicalProperties.line.solidFill = NAVY
    s.graphicalProperties.line.width = 28000
    s.smooth = False
    s.marker.symbol, s.marker.size = "circle", 6
    s.marker.graphicalProperties.solidFill = ACCENT
    s.marker.graphicalProperties.line.solidFill = WHITE
    ln.x_axis.tickLblPos = "low"   # rótulos dos meses embaixo mesmo com saldo negativo
    ln.legend = None
    ws3.add_chart(ln, f"B{M_TOT + 21}")
    imprimir(ws3, f"{M_HDR}:{M_HDR}")

    # ======================================================================
    # ABA DETALHAMENTO (período escolhido)
    # ======================================================================
    widths(ws2, [2, 24, 18, 18, 18, 16, 16, 2])
    title_block(ws2, 2, 7, f"DETALHAMENTO {rotulo_periodo.upper()}",
                f"Entradas, saídas e saldo por período · Exercício {ano}")
    for i, h in enumerate(["Período", "Entradas", "Saídas", "Saldo", "Saídas ÷ Entradas", "Movimentações"], start=2):
        header_cell(ws2.cell(row=4, column=i, value=h))
    ws2.row_dimensions[4].height = 30
    det = dados.get("detalhamento") or []
    d_ini = 5
    for idx, d in enumerate(det):
        r = d_ini + idx
        z = idx % 2 == 1
        body_cell(ws2.cell(row=r, column=2), d["label"], align="left", zebra=z, bold=True)
        body_cell(ws2.cell(row=r, column=3), d["entradas"], fmt_brl, "right", z, color=GREEN)
        body_cell(ws2.cell(row=r, column=4), d["saidas"], fmt_brl, "right", z, color=RED)
        body_cell(ws2.cell(row=r, column=5), f"=C{r}-D{r}", fmt_brl, "right", z, bold=True)
        body_cell(ws2.cell(row=r, column=6), f'=IF(C{r}=0,"—",D{r}/C{r})', fmt_pct, "center", z)
        body_cell(ws2.cell(row=r, column=7), d["movimentacoes"], fmt_int, "center", z, color=BLUE)
        ws2.row_dimensions[r].height = 22
    d_fim = d_ini + max(len(det), 1) - 1
    d_tot = d_fim + 1
    total_cell(ws2.cell(row=d_tot, column=2), "TOTAL", align="left")
    total_cell(ws2.cell(row=d_tot, column=3), f"=SUM(C{d_ini}:C{d_fim})", fmt_brl_plain)
    total_cell(ws2.cell(row=d_tot, column=4), f"=SUM(D{d_ini}:D{d_fim})", fmt_brl_plain)
    total_cell(ws2.cell(row=d_tot, column=5), f"=C{d_tot}-D{d_tot}", fmt_brl_plain)
    total_cell(ws2.cell(row=d_tot, column=6), f'=IF(C{d_tot}=0,"—",D{d_tot}/C{d_tot})', fmt_pct, "center")
    total_cell(ws2.cell(row=d_tot, column=7), f"=SUM(G{d_ini}:G{d_fim})", '#,##0', "center")
    ws2.row_dimensions[d_tot].height = 26
    if det:
        ws2.conditional_formatting.add(f"E{d_ini}:E{d_fim}", ColorScaleRule(
            start_type="min", start_color="FECACA", mid_type="num", mid_value=0, mid_color="FFFFFF",
            end_type="max", end_color="BBF7D0"))
        chd = BarChart()
        chd.type, chd.style = "col", 10
        chd.title = f"Resultado por período — {rotulo_periodo} ({ano})"
        chd.y_axis.number_format = 'R$ #,##0'
        chd.y_axis.delete = False
        chd.x_axis.delete = False
        chd.height, chd.width, chd.gapWidth = 8.5, 18, 80
        chd.add_data(Reference(ws2, min_col=3, max_col=4, min_row=4, max_row=d_fim), titles_from_data=True)
        chd.set_categories(Reference(ws2, min_col=2, min_row=d_ini, max_row=d_fim))
        for s_, cor in zip(chd.series, (GREEN, RED)):
            s_.graphicalProperties.solidFill = cor
            s_.graphicalProperties.line.solidFill = cor
        chd.legend.position = "b"
        ws2.add_chart(chd, f"B{d_tot + 2}")
    ws2.freeze_panes = f"A{d_ini}"
    imprimir(ws2, "4:4")

    # ======================================================================
    # ABA POR ORIGEM
    # ======================================================================
    O_INI, O_FIM, O_TOT = 5, 4 + len(por_origem), 5 + len(por_origem)
    if ws4 is not None:
        widths(ws4, [2, 30, 18, 18, 18, 14, 14, 2])
        title_block(ws4, 2, 7, "DISTRIBUIÇÃO POR ORIGEM DA VERBA",
                    "Recursos por fonte: PDDE, CITI, Recursos Próprios, Doações, Convênios")
        for i, h in enumerate(["Origem", "Entradas", "Saídas", "Saldo", "% das entradas", "% das saídas"], start=2):
            header_cell(ws4.cell(row=4, column=i, value=h))
        ws4.row_dimensions[4].height = 30
        for idx, o in enumerate(por_origem):
            r = O_INI + idx
            z = idx % 2 == 1
            body_cell(ws4.cell(row=r, column=2), o["nome"], align="left", zebra=z, bold=True)
            body_cell(ws4.cell(row=r, column=3), o["entradas"], fmt_brl, "right", z, color=GREEN)
            body_cell(ws4.cell(row=r, column=4), o["saidas"], fmt_brl, "right", z, color=RED)
            body_cell(ws4.cell(row=r, column=5), f"=C{r}-D{r}", fmt_brl, "right", z, bold=True)
            body_cell(ws4.cell(row=r, column=6), f"=IF(C${O_TOT}=0,0,C{r}/C${O_TOT})", fmt_pct, "center", z, color=BLUE)
            body_cell(ws4.cell(row=r, column=7), f"=IF(D${O_TOT}=0,0,D{r}/D${O_TOT})", fmt_pct, "center", z, color=BLUE)
            ws4.row_dimensions[r].height = 22
        total_cell(ws4.cell(row=O_TOT, column=2), "TOTAL", align="left")
        total_cell(ws4.cell(row=O_TOT, column=3), f"=SUM(C{O_INI}:C{O_FIM})", fmt_brl_plain)
        total_cell(ws4.cell(row=O_TOT, column=4), f"=SUM(D{O_INI}:D{O_FIM})", fmt_brl_plain)
        total_cell(ws4.cell(row=O_TOT, column=5), f"=C{O_TOT}-D{O_TOT}", fmt_brl_plain)
        total_cell(ws4.cell(row=O_TOT, column=6), f"=SUM(F{O_INI}:F{O_FIM})", fmt_pct, "center")
        total_cell(ws4.cell(row=O_TOT, column=7), f"=SUM(G{O_INI}:G{O_FIM})", fmt_pct, "center")
        ws4.row_dimensions[O_TOT].height = 26
        ws4.conditional_formatting.add(f"F{O_INI}:F{O_FIM}", DataBarRule(start_type="num", start_value=0, end_type="num", end_value=1, color="93C5FD", showValue=True))
        ws4.conditional_formatting.add(f"G{O_INI}:G{O_FIM}", DataBarRule(start_type="num", start_value=0, end_type="num", end_value=1, color="FCA5A5", showValue=True))
        cho = BarChart()
        cho.type, cho.style = "col", 10
        cho.title = f"Entradas × Saídas por origem ({ano})"
        cho.y_axis.number_format = 'R$ #,##0'
        cho.y_axis.delete = False
        cho.x_axis.delete = False
        cho.height, cho.width, cho.gapWidth = 8.5, 18, 80
        cho.add_data(Reference(ws4, min_col=3, max_col=4, min_row=4, max_row=O_FIM), titles_from_data=True)
        cho.set_categories(Reference(ws4, min_col=2, min_row=O_INI, max_row=O_FIM))
        for s_, cor in zip(cho.series, (GREEN, RED)):
            s_.graphicalProperties.solidFill = cor
            s_.graphicalProperties.line.solidFill = cor
        cho.legend.position = "b"
        ws4.add_chart(cho, f"B{O_TOT + 2}")
        ws4.freeze_panes = f"A{O_INI}"
        imprimir(ws4, "4:4")

    # ======================================================================
    # ABA POR CATEGORIA
    # ======================================================================
    C_INI, C_FIM, C_TOT = 5, 4 + len(por_categoria), 5 + len(por_categoria)
    if ws5 is not None:
        widths(ws5, [2, 34, 18, 10, 18, 16, 16, 2])
        title_block(ws5, 2, 7, "DESPESAS POR CATEGORIA",
                    f"Ranking das {len(por_categoria)} categorias com maior gasto · % calculado sobre o total deste ranking")
        for i, h in enumerate(["Categoria", "Total gasto", "Qtd", "Ticket médio", "% das despesas", "% acumulado"], start=2):
            header_cell(ws5.cell(row=4, column=i, value=h))
        ws5.row_dimensions[4].height = 30
        for idx, c in enumerate(por_categoria):
            r = C_INI + idx
            z = idx % 2 == 1
            body_cell(ws5.cell(row=r, column=2), c["categoria"], align="left", zebra=z, bold=True)
            body_cell(ws5.cell(row=r, column=3), c["total"], fmt_brl, "right", z, color=RED)
            body_cell(ws5.cell(row=r, column=4), c["quantidade"], fmt_int, "center", z, color=BLUE)
            body_cell(ws5.cell(row=r, column=5), f"=IF(D{r}=0,0,C{r}/D{r})", fmt_brl, "right", z)
            body_cell(ws5.cell(row=r, column=6), f"=IF(C${C_TOT}=0,0,C{r}/C${C_TOT})", fmt_pct, "center", z, bold=True, color=AMBER)
            body_cell(ws5.cell(row=r, column=7), f"=SUM(F${C_INI}:F{r})", fmt_pct, "center", z, color=GRAY)
            ws5.row_dimensions[r].height = 22
        total_cell(ws5.cell(row=C_TOT, column=2), "TOTAL", align="left")
        total_cell(ws5.cell(row=C_TOT, column=3), f"=SUM(C{C_INI}:C{C_FIM})", fmt_brl_plain)
        total_cell(ws5.cell(row=C_TOT, column=4), f"=SUM(D{C_INI}:D{C_FIM})", '#,##0', "center")
        total_cell(ws5.cell(row=C_TOT, column=5), f"=IF(D{C_TOT}=0,0,C{C_TOT}/D{C_TOT})", fmt_brl_plain)
        total_cell(ws5.cell(row=C_TOT, column=6), f"=SUM(F{C_INI}:F{C_FIM})", fmt_pct, "center")
        total_cell(ws5.cell(row=C_TOT, column=7), "", None, "center")
        ws5.row_dimensions[C_TOT].height = 26
        ws5.conditional_formatting.add(f"C{C_INI}:C{C_FIM}", DataBarRule(start_type="num", start_value=0, end_type="max", color="FCA5A5", showValue=True))
        chc = BarChart()
        chc.type, chc.style = "bar", 10
        chc.title = f"Maiores despesas por categoria ({ano})"
        chc.x_axis.scaling.orientation = "maxMin"   # maior no topo
        chc.y_axis.number_format = 'R$ #,##0'
        chc.y_axis.delete = False
        chc.x_axis.delete = False
        chc.height, chc.width, chc.gapWidth = max(7, 0.8 * len(por_categoria) + 3), 18, 50
        chc.add_data(Reference(ws5, min_col=3, min_row=4, max_row=C_FIM), titles_from_data=True)
        chc.set_categories(Reference(ws5, min_col=2, min_row=C_INI, max_row=C_FIM))
        chc.series[0].graphicalProperties.solidFill = RED
        chc.legend = None
        ws5.add_chart(chc, f"B{C_TOT + 2}")
        ws5.freeze_panes = f"A{C_INI}"
        imprimir(ws5, "4:4")

    # ======================================================================
    # ABA LANÇAMENTOS (base de dados, auditável e filtrável)
    # ======================================================================
    L_HDR, L_INI = 6, 7
    L_FIM = L_INI + len(lancamentos) - 1
    SL = "'Lançamentos'!"
    if ws6 is not None:
        widths(ws6, [2, 12, 11, 40, 20, 26, 22, 16, 16, 12, 16, 16, 2])
        title_block(ws6, 2, 12, "LANÇAMENTOS DO EXERCÍCIO",
                    f"Base completa de {len(lancamentos)} lançamento(s) · use os filtros do cabeçalho · Exercício {ano}")
        ws6.merge_cells("B4:K4")
        c = ws6["B4"]
        c.value = "Saldo dos lançamentos visíveis (acompanha os filtros aplicados):"
        c.font = Font(name=FONT, size=10, bold=True, color=NAVY)
        c.alignment = Alignment(horizontal="right", vertical="center")
        ws6["L4"].value = f"=SUBTOTAL(109,L{L_INI}:L{L_FIM})"
        ws6["L4"].number_format = fmt_brl_plain
        ws6["L4"].font = Font(name=FONT, size=11, bold=True, color=BLUE)
        ws6["L4"].fill = fill(BLUE_BG)
        ws6["L4"].border = borda
        ws6["L4"].alignment = Alignment(horizontal="right", vertical="center")
        ws6.row_dimensions[4].height = 24
        for i, h in enumerate(["Data", "Tipo", "Descrição", "Origem", "Verba", "Categoria",
                               "Forma pgto.", "Nº documento", "Status", "Valor", "Impacto no caixa"], start=2):
            header_cell(ws6.cell(row=L_HDR, column=i, value=h))
        ws6.row_dimensions[L_HDR].height = 30
        for idx, l in enumerate(lancamentos):
            r = L_INI + idx
            z = idx % 2 == 1
            eh_rec = l["tipo"] == "Receita"
            body_cell(ws6.cell(row=r, column=2), l["data"], fmt_date, "center", z)
            body_cell(ws6.cell(row=r, column=3), l["tipo"], align="center", zebra=z, bold=True,
                      color=GREEN if eh_rec else RED)
            body_cell(ws6.cell(row=r, column=4), l.get("descricao") or "—", align="left", zebra=z)
            body_cell(ws6.cell(row=r, column=5), l.get("origem") or "—", align="left", zebra=z)
            body_cell(ws6.cell(row=r, column=6), l.get("verba") or "—", align="left", zebra=z)
            body_cell(ws6.cell(row=r, column=7), l.get("categoria") or "—", align="left", zebra=z)
            body_cell(ws6.cell(row=r, column=8), l.get("forma") or "—", align="center", zebra=z)
            body_cell(ws6.cell(row=r, column=9), l.get("doc") or "—", align="center", zebra=z)
            body_cell(ws6.cell(row=r, column=10), l.get("status") or "—", align="center", zebra=z)
            body_cell(ws6.cell(row=r, column=11), float(l["valor"] or 0), fmt_brl_plain, "right", z)
            body_cell(ws6.cell(row=r, column=12), f'=IF(C{r}="Receita",K{r},-K{r})', fmt_brl_plain, "right", z, bold=True)
        ws6.conditional_formatting.add(f"J{L_INI}:J{L_FIM}", CellIsRule(operator="equal", formula=['"Pendente"'], font=Font(color=AMBER, bold=True)))
        ws6.conditional_formatting.add(f"J{L_INI}:J{L_FIM}", CellIsRule(operator="equal", formula=['"Aprovado"'], font=Font(color=GREEN, bold=True)))
        ws6.freeze_panes = f"C{L_INI}"
        ws6.auto_filter.ref = f"B{L_HDR}:L{L_FIM}"
        imprimir(ws6, f"{L_HDR}:{L_HDR}")

    # ======================================================================
    # ABA RESUMO EXECUTIVO (dashboard — tudo por fórmulas)
    # ======================================================================
    widths(ws1, [2, 28, 20, 20, 20, 20, 2])
    title_block(ws1, 2, 6, "IPE — RELATÓRIO FINANCEIRO",
                f"{rotulo_periodo} · Exercício {ano} · Gerado em {gerado_em}")

    kpi(ws1, 4, 2, 2, "TOTAL DE ENTRADAS", f"={SM}C{M_TOT}", fmt_brl_plain, GREEN, GREEN_BG, 15)
    kpi(ws1, 4, 3, 3, "TOTAL DE SAÍDAS", f"={SM}D{M_TOT}", fmt_brl_plain, RED, RED_BG, 15)
    kpi(ws1, 4, 4, 4, "SALDO DO EXERCÍCIO", f"={SM}E{M_TOT}", fmt_brl_plain, BLUE, BLUE_BG, 15)
    kpi(ws1, 4, 5, 5, "MOVIMENTAÇÕES", f"={SM}G{M_TOT}", '#,##0', NAVY, GRAY_BG, 15)
    kpi(ws1, 4, 6, 6, "SAÍDAS ÷ ENTRADAS", f"={SM}H{M_TOT}", fmt_pct, AMBER, AMBER_BG, 15)
    # saldo muda de cor conforme sinal
    ws1.conditional_formatting.add("D5", CellIsRule(operator="lessThan", formula=["0"], font=Font(color=RED, bold=True, size=15)))
    ws1.conditional_formatting.add("D5", CellIsRule(operator="greaterThanOrEqual", formula=["0"], font=Font(color=GREEN, bold=True, size=15)))

    section(ws1, 7, 2, 6, "DESTAQUES DO EXERCÍCIO")
    for i, h in enumerate(["Indicador", "Mês", "Valor"], start=2):
        header_cell(ws1.cell(row=8, column=i, value=h))
    E, S, SD, G = (f"{SM}$C${M_INI}:$C${M_FIM}", f"{SM}$D${M_INI}:$D${M_FIM}",
                   f"{SM}$E${M_INI}:$E${M_FIM}", f"{SM}$G${M_INI}:$G${M_FIM}")
    B_ = f"{SM}$B${M_INI}:$B${M_FIM}"
    destaques = [
        ("Maior receita mensal", f"MAX({E})", E, GREEN),
        ("Maior despesa mensal", f"MAX({S})", S, RED),
        ("Melhor saldo mensal", f'_xlfn.MAXIFS({SD},{G},">0")', SD, GREEN),
        ("Pior saldo mensal", f'_xlfn.MINIFS({SD},{G},">0")', SD, RED),
    ]
    for idx, (nome, formula_val, rng_busca, cor) in enumerate(destaques):
        r = 9 + idx
        z = idx % 2 == 1
        body_cell(ws1.cell(row=r, column=2), nome, align="left", zebra=z, bold=True)
        body_cell(ws1.cell(row=r, column=4), f'=IF(COUNTIF({G},">0")=0,0,{formula_val})', fmt_brl_plain, "right", z, bold=True, color=cor)
        body_cell(ws1.cell(row=r, column=3), f'=IF(COUNTIF({G},">0")=0,"—",INDEX({B_},MATCH(D{r},{rng_busca},0)))', align="center", zebra=z)
        ws1.row_dimensions[r].height = 22

    prox = 14
    if ws4 is not None:
        section(ws1, prox, 2, 6, "ORIGEM DAS VERBAS")
        for i, h in enumerate(["Origem", "Entradas", "Saídas", "Saldo", "% das entradas"], start=2):
            header_cell(ws1.cell(row=prox + 1, column=i, value=h))
        SO = "'Por Origem'!"
        for idx in range(len(por_origem)):
            r = prox + 2 + idx
            src = O_INI + idx
            z = idx % 2 == 1
            body_cell(ws1.cell(row=r, column=2), f"={SO}B{src}", align="left", zebra=z, bold=True)
            body_cell(ws1.cell(row=r, column=3), f"={SO}C{src}", fmt_brl, "right", z, color=GREEN)
            body_cell(ws1.cell(row=r, column=4), f"={SO}D{src}", fmt_brl, "right", z, color=RED)
            body_cell(ws1.cell(row=r, column=5), f"={SO}E{src}", fmt_brl, "right", z, bold=True)
            body_cell(ws1.cell(row=r, column=6), f"={SO}F{src}", fmt_pct, "center", z, color=BLUE)
            ws1.row_dimensions[r].height = 22
        r_tot = prox + 2 + len(por_origem)
        total_cell(ws1.cell(row=r_tot, column=2), "TOTAL", align="left")
        total_cell(ws1.cell(row=r_tot, column=3), f"={SO}C{O_TOT}", fmt_brl_plain)
        total_cell(ws1.cell(row=r_tot, column=4), f"={SO}D{O_TOT}", fmt_brl_plain)
        total_cell(ws1.cell(row=r_tot, column=5), f"={SO}E{O_TOT}", fmt_brl_plain)
        total_cell(ws1.cell(row=r_tot, column=6), f"={SO}F{O_TOT}", fmt_pct, "center")
        ws1.row_dimensions[r_tot].height = 26
        prox = r_tot + 2

    # conferência cruzada com a base de lançamentos
    if ws6 is not None:
        ws1.merge_cells(start_row=prox, start_column=2, end_row=prox, end_column=3)
        ws1.cell(row=prox, column=2, value="Conferência com a aba Lançamentos:").font = Font(name=FONT, size=9, italic=True, color=GRAY)
        ws1.merge_cells(start_row=prox, start_column=4, end_row=prox, end_column=6)
        ck = ws1.cell(row=prox, column=4)
        ck.value = (f'=IF(AND(ABS(SUMIFS({SL}$K${L_INI}:$K${L_FIM},{SL}$C${L_INI}:$C${L_FIM},"Receita")-{SM}C{M_TOT})<0.01,'
                    f'ABS(SUMIFS({SL}$K${L_INI}:$K${L_FIM},{SL}$C${L_INI}:$C${L_FIM},"Despesa")-{SM}D{M_TOT})<0.01),'
                    f'"✔ Totais conferem","✖ Divergência — verifique os lançamentos")')
        ck.font = Font(name=FONT, size=9, bold=True, color=GREEN)
        ck.alignment = Alignment(horizontal="left", vertical="center", indent=1)
        ws1.conditional_formatting.add(f"D{prox}", FormulaRule(formula=[f'LEFT($D${prox},1)="✖"'], font=Font(color=RED, bold=True)))
        prox += 2

    chr_ = BarChart()
    chr_.type, chr_.style = "col", 10
    chr_.title = f"Entradas × Saídas por mês ({ano})"
    chr_.y_axis.number_format = 'R$ #,##0'
    chr_.y_axis.delete = False
    chr_.x_axis.delete = False
    chr_.height, chr_.width, chr_.gapWidth, chr_.overlap = 8.5, 20.5, 60, -10
    chr_.add_data(Reference(ws3, min_col=3, max_col=4, min_row=M_HDR, max_row=M_FIM), titles_from_data=True)
    chr_.set_categories(Reference(ws3, min_col=2, min_row=M_INI, max_row=M_FIM))
    for s_, cor in zip(chr_.series, (GREEN, RED)):
        s_.graphicalProperties.solidFill = cor
        s_.graphicalProperties.line.solidFill = cor
    chr_.legend.position = "b"
    ws1.add_chart(chr_, f"B{prox}")
    imprimir(ws1)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@app.route("/api/relatorios/exportar-excel", methods=["GET"])
@patrimonio_required
def api_relatorios_exportar_excel():
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        return jsonify({"erro": "A biblioteca openpyxl não está instalada. Rode: pip install openpyxl"}), 501

    resp = api_relatorios_resumo()
    if isinstance(resp, tuple):
        return resp
    dados = resp.get_json()
    ano, periodo = dados["ano"], dados["periodo"]

    # Base de lançamentos do exercício (aba "Lançamentos"). Se falhar, o relatório sai sem ela.
    lancamentos = []
    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""SELECT lc.data_lancamento, lc.tipo_movimento, lc.descricao, lc.valor,
                                 lc.forma_pagamento, lc.numero_documento,
                                 d.categoria AS categoria_despesa, d.aprovacao, v.nome AS verba_nome
                          FROM Lancamento_caixa lc
                          LEFT JOIN Despesa d ON d.id_lancamento = lc.id_lancamento
                          LEFT JOIN verba v ON v.id_verba = d.id_verba
                          WHERE YEAR(lc.data_lancamento) = %s
                          ORDER BY lc.data_lancamento ASC, lc.id_lancamento ASC""", (ano,))
        for l in cursor.fetchall():
            origem, verba_limpa = _extrair_origem_verba(l.get("verba_nome") or "")
            lancamentos.append({
                "data": l["data_lancamento"],
                "tipo": l["tipo_movimento"],
                "descricao": l.get("descricao"),
                "origem": ORIGENS_VALIDAS.get(origem, {}).get("nome") if origem else None,
                "verba": verba_limpa or None,
                "categoria": l.get("categoria_despesa"),
                "forma": l.get("forma_pagamento"),
                "doc": l.get("numero_documento"),
                "status": ("Aprovado" if l.get("aprovacao") == 1 else
                           "Pendente" if l.get("aprovacao") == 0 else None),
                "valor": float(l["valor"] or 0),
            })
    except mysql.connector.Error:
        lancamentos = []
    finally:
        cursor.close(); conn.close()

    conteudo = _gerar_excel_relatorio(dados, lancamentos)
    nome = f"relatorio_{periodo}_{ano}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    try:
        with open(os.path.join(app.config['BACKUP_FOLDER'], nome), "wb") as f:
            f.write(conteudo)
    except Exception:
        pass
    return send_file(
        io.BytesIO(conteudo),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=nome,
    )


    
# ==========================================
# MÓDULO - NOTIFICAÇÕES FUNCIONAIS (SMTP)
# ==========================================
@app.route("/api/notificacoes/config-smtp", methods=["GET", "POST"])
@admin_required
def api_notificacoes_config_smtp():
    if request.method == "POST":
        dados = request.get_json(silent=True) or {}
        anterior = _ler_config_smtp()
        senha_nova = _limpar_senha_smtp(dados.get("senha"))
        if not senha_nova or set(senha_nova) <= set("•*"):
            senha_nova = anterior.get("senha", "")
        config = {"servidor": (dados.get("servidor") or "smtp.gmail.com").strip(),
                  "porta": int(dados.get("porta") or 587),
                  "usuario": (dados.get("usuario") or "").strip(),
                  "senha": senha_nova,
                  "remetente_nome": (dados.get("remetente_nome") or "IPE - Sistema de Inventário").strip(),
                  "ativo": bool(dados.get("ativo"))}
        _salvar_config_smtp(config)
        try:
            conn = get_db_connection(); cursor = conn.cursor()
            cursor.execute("""INSERT INTO Log_auditoria (acao, descricao, id_usuario)
                              VALUES ('UPDATE', 'Configuração SMTP atualizada', %s)""", (session['id_usuario'],))
            conn.commit(); cursor.close(); conn.close()
        except Exception:
            pass
        return jsonify({"sucesso": True, "mensagem": "Configuração salva!"})

    config = _ler_config_smtp()
    cfg = {**config}
    if cfg.get("senha"): cfg["senha"] = MASCARA_SENHA
    return jsonify(cfg)


@app.route("/api/notificacoes/testar-smtp", methods=["POST"])
@admin_required
def api_notificacoes_testar_smtp():
    dados = request.get_json(silent=True) or {}
    dest = (dados.get("email") or "").strip()
    if not dest: return jsonify({"erro": "Informe um e-mail."}), 400

    corpo_html = f"""
    <html><body style="font-family: Arial, sans-serif; background: #f7f7f5; padding: 20px;">
        <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 12px; padding: 30px;">
            <h1 style="color: #152937;">📦 IPE - Teste de E-mail</h1>
            <p>Este é um e-mail de teste. A configuração SMTP está funcionando!</p>
            <p style="color: #999; font-size: 0.8rem;">Enviado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}</p>
        </div>
    </body></html>
    """
    ok, msg = _enviar_email([dest], "✅ Teste de configuração SMTP - IPE", corpo_html,
                            f"IPE - Teste de configuração SMTP\n\nEnviado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    if ok: return jsonify({"sucesso": True, "mensagem": msg})
    return jsonify({"erro": msg}), 500


@app.route("/api/notificacoes/destinatarios", methods=["GET"])
@admin_required
def api_notificacoes_destinatarios():
    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""SELECT id_usuario, nome, e_mail, id_perfil FROM Usuario
                          WHERE e_mail IS NOT NULL AND e_mail <> '' ORDER BY nome ASC""")
        usuarios = cursor.fetchall()
        for u in usuarios:
            u["nome_perfil"] = NOMES_PERFIL.get(u["id_perfil"], "Usuário")
        return jsonify(usuarios)
    except mysql.connector.Error as err:
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close(); conn.close()


@app.route("/api/notificacoes/enviar", methods=["POST"])
@admin_required
def api_notificacoes_enviar():
    dados = request.get_json(silent=True) or {}
    assunto = (dados.get("assunto") or "").strip()
    mensagem = (dados.get("mensagem") or "").strip()
    dest_input = dados.get("destinatarios", [])
    tipo = (dados.get("tipo") or "info").lower()
    link = (dados.get("link") or "").strip()

    if not assunto: return jsonify({"erro": "Informe o assunto."}), 400
    if not mensagem: return jsonify({"erro": "Informe a mensagem."}), 400
    if tipo not in ("info", "alerta", "urgente"): tipo = "info"

    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    try:
        if dest_input in ("todos", ["todos"]):
            cursor.execute("SELECT e_mail FROM Usuario WHERE e_mail IS NOT NULL AND e_mail <> ''")
            emails = [r["e_mail"] for r in cursor.fetchall()]
        elif dest_input in ("admins", ["admins"]):
            cursor.execute("SELECT e_mail FROM Usuario WHERE id_perfil = 1 AND e_mail IS NOT NULL")
            emails = [r["e_mail"] for r in cursor.fetchall()]
        elif isinstance(dest_input, list) and len(dest_input) > 0:
            emails = [e.strip() for e in dest_input if e.strip()]
        else:
            return jsonify({"erro": "Selecione pelo menos um destinatário."}), 400
        if not emails:
            return jsonify({"erro": "Nenhum e-mail válido."}), 400
    finally:
        cursor.close(); conn.close()

    cores = {"info": {"bg": "#dbeafe", "border": "#1e40af", "texto": "ℹ️ Informação"},
             "alerta": {"bg": "#fef3c7", "border": "#b45309", "texto": "⚠️ Alerta"},
             "urgente": {"bg": "#fee2e2", "border": "#991b1b", "texto": "🚨 Urgente"}}
    cor = cores[tipo]
    link_html = ""
    if link:
        link_html = f'<div style="text-align:center; margin-top:25px;"><a href="{link}" style="display:inline-block; background:linear-gradient(135deg, #FFD730, #F29310); color:#152937; text-decoration:none; padding:14px 30px; border-radius:10px; font-weight:600;">🔗 Acessar no Sistema</a></div>'

    corpo_html = f"""
    <html><body style="font-family: Arial, sans-serif; background: #f7f7f5; padding: 20px;">
        <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 12px; overflow: hidden;">
            <div style="background: linear-gradient(135deg, #FFD730, #F29310); padding: 25px; text-align: center;">
                <h1 style="margin: 0; color: #152937;">📦 IPE</h1>
            </div>
            <div style="padding: 30px;">
                <div style="display: inline-block; background: {cor['bg']}; color: {cor['border']};
                     padding: 5px 15px; border-radius: 999px; font-size: 0.78rem; font-weight: 600;
                     margin-bottom: 15px;">{cor['texto']}</div>
                <h2 style="color: #152937;">{assunto}</h2>
                <div style="color: #333; line-height: 1.7;">{mensagem.replace(chr(10), '<br>')}</div>
                {link_html}
                <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 30px 0;">
                <p style="color: #999; font-size: 0.78rem; text-align: center;">
                    Enviado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}
                </p>
            </div>
        </div>
    </body></html>
    """
    corpo_texto = f"IPE - {assunto}\n\n{mensagem}\n\n{('Acesse: ' + link) if link else ''}"

    ok, msg_r = _enviar_email(emails, assunto, corpo_html, corpo_texto)

    try:
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("""INSERT INTO Log_auditoria (acao, descricao, id_usuario)
                          VALUES ('INSERT', %s, %s)""",
                       (f"Notificação enviada ({tipo}) para {len(emails)} destinatário(s): {assunto[:80]}",
                        session['id_usuario']))
        conn.commit(); cursor.close(); conn.close()
    except Exception:
        pass

    if ok:
        return jsonify({"sucesso": True, "mensagem": f"Notificação enviada para {len(emails)} destinatário(s)!",
                        "total_enviados": len(emails)})
    return jsonify({"erro": msg_r}), 500


@app.route("/api/notificacoes/historico", methods=["GET"])
@admin_required
def api_notificacoes_historico():
    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""SELECT l.id_log, DATE_FORMAT(l.data, '%d/%m/%Y %H:%i') AS data_formatada,
                                 l.descricao, IFNULL(u.nome, 'Sistema') AS nome_usuario
                          FROM Log_auditoria l
                          LEFT JOIN Usuario u ON l.id_usuario = u.id_usuario
                          WHERE l.descricao LIKE 'Notificação enviada%'
                          ORDER BY l.id_log DESC LIMIT 50""")
        return jsonify(cursor.fetchall())
    except mysql.connector.Error as err:
        return jsonify({"erro": str(err)}), 500
    finally:
        cursor.close(); conn.close()

# ==========================================
# MÓDULO - PDF DO INVENTÁRIO
# ==========================================
@app.route("/api/inventario/pdf", methods=["GET"])
@admin_required
def api_inventario_pdf():
    """
    Gera um PDF do inventário com os mesmos filtros da tela.
    Query params (todos opcionais):
      - busca, categoria, sala, status
      - valor_min, valor_max
      - data_ini, data_fim
      - incluir_baixados (0 ou 1)
      - ordem, direcao
    """
    from io import BytesIO

    busca = request.args.get("busca", "").strip()
    categoria = request.args.get("categoria", "").strip()
    sala = request.args.get("sala", type=int)
    status = request.args.get("status", type=int)
    valor_min = request.args.get("valor_min", type=float)
    valor_max = request.args.get("valor_max", type=float)
    data_ini = request.args.get("data_ini", "").strip()
    data_fim = request.args.get("data_fim", "").strip()
    ordem = request.args.get("ordem", "numero").strip()
    direcao = request.args.get("direcao", "desc").strip().lower()
    incluir_baixados = request.args.get("incluir_baixados", "0") == "1"

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    from_join = """
        FROM Patrimonio p
        LEFT JOIN Sala s ON p.id_sala = s.id_sala
        LEFT JOIN Categoria cat ON p.id_categoria = cat.id_categoria
        LEFT JOIN _status st ON p.id_status = st.id_status
    """

    where = " WHERE 1=1"
    params = []

    if not incluir_baixados:
        where += " AND p.processo_baixa IS NULL"

    if busca:
        where += (" AND (p.nome LIKE %s OR p.numero_patrimonio LIKE %s"
                  " OR p.nota_fiscal LIKE %s OR p.descricao LIKE %s)")
        params.extend([f"%{busca}%"] * 4)

    if categoria:
        if categoria.startswith("cge::"):
            where += " AND cat.nome = %s"
            params.append(categoria.replace("cge::", "", 1))
        else:
            try:
                where += " AND p.id_categoria = %s"
                params.append(int(categoria))
            except ValueError:
                pass

    if sala:
        where += " AND p.id_sala = %s"; params.append(sala)
    if status:
        where += " AND p.id_status = %s"; params.append(status)
    if valor_min is not None:
        where += " AND p.valor_atual >= %s"; params.append(valor_min)
    if valor_max is not None:
        where += " AND p.valor_atual <= %s"; params.append(valor_max)
    if data_ini:
        where += " AND DATE(p.data_aquisicao) >= %s"; params.append(data_ini)
    if data_fim:
        where += " AND DATE(p.data_aquisicao) <= %s"; params.append(data_fim)

    campos = {"numero": "p.numero_patrimonio", "nome": "p.nome", "valor": "p.valor_atual",
              "data": "p.data_aquisicao", "categoria": "cat.nome", "sala": "s.numero_sala",
              "status": "st.nome"}
    campo_sql = campos.get(ordem, "p.numero_patrimonio")
    direcao_sql = "DESC" if direcao == "desc" else "ASC"

    try:
        cursor.execute(
            f"""SELECT p.id_patrimonio, p.nome, p.numero_patrimonio,
                       p.valor_atual AS valor_compra,
                       DATE_FORMAT(p.data_aquisicao, '%d/%m/%Y') AS data_aquisicao,
                       DATE_FORMAT(p.data_aquisicao, '%Y-%m-%d') AS data_aquisicao_iso,
                       p.taxa_depreciacao, p.processo_baixa,
                       IFNULL(s.numero_sala, 'Não Alocado') AS nome_sala,
                       s.bloco AS bloco_sala,
                       IFNULL(cat.nome, '—') AS nome_categoria,
                       IFNULL(st.nome, 'Ativo') AS nome_status
                {from_join} {where}
                ORDER BY {campo_sql} {direcao_sql}""",
            params
        )
        bens = cursor.fetchall() or []

        # Calcula valor atual (depreciação) e total
        total_compra = 0.0
        total_atual = 0.0
        for b in bens:
            b["valor_atual_calc"] = patrimonio_service.calcular_depreciacao(
                b["valor_compra"], b["data_aquisicao_iso"], b["taxa_depreciacao"]
            )
            b["valor_compra"] = float(b["valor_compra"] or 0)
            b["valor_atual_calc"] = float(b["valor_atual_calc"] or 0)
            total_compra += b["valor_compra"]
            total_atual += b["valor_atual_calc"]
    except mysql.connector.Error as err:
        cursor.close()
        conn.close()
        return jsonify({"erro": str(err)}), 500
    finally:
        try:
            cursor.close()
            conn.close()
        except Exception:
            pass

    # ---------- GERA O PDF ----------
    buffer = BytesIO()

    # Layout: A4 paisagem para caber mais colunas
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=1.2 * cm,
        rightMargin=1.2 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.2 * cm,
        title="Inventário IPE",
        author="IPE - Sistema de Inventário",
    )

    styles = getSampleStyleSheet()

    # Estilos customizados
    titulo_style = ParagraphStyle(
        "TituloIPE",
        parent=styles["Title"],
        fontSize=18,
        textColor=colors.HexColor("#152937"),
        spaceAfter=4,
        alignment=TA_CENTER,
        fontName="Helvetica-Bold",
    )
    subtitulo_style = ParagraphStyle(
        "SubtituloIPE",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#5b6670"),
        spaceAfter=12,
        alignment=TA_CENTER,
        fontName="Helvetica",
    )
    celula_style = ParagraphStyle(
        "Celula",
        parent=styles["Normal"],
        fontSize=7.5,
        leading=9,
        textColor=colors.HexColor("#152937"),
        fontName="Helvetica",
    )
    celula_center = ParagraphStyle(
        "CelulaCenter",
        parent=celula_style,
        alignment=TA_CENTER,
    )
    celula_right = ParagraphStyle(
        "CelulaRight",
        parent=celula_style,
        alignment=TA_RIGHT,
    )
    header_style = ParagraphStyle(
        "Header",
        parent=celula_style,
        fontSize=7.5,
        textColor=colors.white,
        fontName="Helvetica-Bold",
        alignment=TA_CENTER,
    )

    story = []

    # Cabeçalho
    story.append(Paragraph("📦 IPE — Relatório de Inventário", titulo_style))
    data_geracao = datetime.now().strftime("%d/%m/%Y às %H:%M")
    filtros_aplicados = []
    if busca: filtros_aplicados.append(f'busca="{busca}"')
    if categoria: filtros_aplicados.append(f"categoria={categoria}")
    if sala: filtros_aplicados.append(f"sala={sala}")
    if status: filtros_aplicados.append(f"status={status}")
    if valor_min is not None: filtros_aplicados.append(f"valor≥{valor_min}")
    if valor_max is not None: filtros_aplicados.append(f"valor≤{valor_max}")
    if data_ini: filtros_aplicados.append(f"de {data_ini}")
    if data_fim: filtros_aplicados.append(f"até {data_fim}")
    if incluir_baixados: filtros_aplicados.append("inclui baixados")

    linha_filtros = " · ".join(filtros_aplicados) if filtros_aplicados else "Nenhum filtro aplicado"
    story.append(Paragraph(
        f"Gerado em {data_geracao} · {len(bens)} patrimônio(s) · Filtros: {linha_filtros}",
        subtitulo_style
    ))

    # Cabeçalho da tabela
    headers = ["Nº", "Nome", "Categoria", "Sala / Bloco", "Aquisição", "V. Compra", "V. Atual", "Status"]
    rows = [[Paragraph(h, header_style) for h in headers]]

    # Linhas
    for b in bens:
        local = b["nome_sala"]
        if b["bloco_sala"]:
            local += f" ({b['bloco_sala']})"
        status_mostrar = "BAIXADO" if b["processo_baixa"] else b["nome_status"]

        rows.append([
            Paragraph(str(b["numero_patrimonio"]), celula_center),
            Paragraph(str(b["nome"] or "—"), celula_style),
            Paragraph(str(b["nome_categoria"] or "—"), celula_style),
            Paragraph(str(local), celula_style),
            Paragraph(str(b["data_aquisicao"] or "—"), celula_center),
            Paragraph(f"R$ {b['valor_compra']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."), celula_right),
            Paragraph(f"R$ {b['valor_atual_calc']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."), celula_right),
            Paragraph(str(status_mostrar), celula_center),
        ])

    # Larguras (em cm) — total ~26.9cm (A4 paisagem útil)
    larguras = [1.6 * cm, 5.5 * cm, 4.5 * cm, 3.5 * cm, 2.2 * cm, 2.8 * cm, 2.8 * cm, 2.5 * cm]

    tabela = Table(rows, colWidths=larguras, repeatRows=1)
    tabela.setStyle(TableStyle([
        # Cabeçalho
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#152937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        # Linhas
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 7.5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        # Zebra
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafbfc")]),
        # Bordas
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d1d5db")),
        ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#F29310")),
    ]))

    if len(rows) == 1:
        # Nenhum resultado
        story.append(Paragraph(
            "<i>Nenhum patrimônio encontrado com os filtros aplicados.</i>",
            ParagraphStyle("vazio", parent=styles["Normal"], fontSize=10, textColor=colors.HexColor("#6b7280"), alignment=TA_CENTER)
        ))
    else:
        story.append(tabela)

    # Rodapé com totais
    story.append(Spacer(1, 10))
    total_compra_str = f"R$ {total_compra:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    total_atual_str = f"R$ {total_atual:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    story.append(Paragraph(
        f"<b>Total de Compra:</b> {total_compra_str} &nbsp;&nbsp;|&nbsp;&nbsp; "
        f"<b>Total Atual (com depreciação):</b> {total_atual_str} &nbsp;&nbsp;|&nbsp;&nbsp; "
        f"<b>Itens:</b> {len(bens)}",
        ParagraphStyle("totais", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#152937"), alignment=TA_RIGHT)
    ))

    # Função de numeração das páginas
    def _footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#6b7280"))
        canvas.drawString(1.2 * cm, 0.7 * cm, "IPE — Sistema de Inventário")
        canvas.drawRightString(
            landscape(A4)[0] - 1.2 * cm, 0.7 * cm,
            f"Página {canvas.getPageNumber()}"
        )
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)

    pdf_bytes = buffer.getvalue()
    buffer.close()

    nome_arquivo = f"inventario_ipe_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"

    # Log de auditoria (opcional, mas útil)
    try:
        conn2 = get_db_connection()
        cur2 = conn2.cursor()
        cur2.execute(
            "INSERT INTO Log_auditoria (acao, descricao, id_usuario) VALUES ('EXPORT', %s, %s)",
            (f"PDF do inventário gerado ({len(bens)} itens). Filtros: {linha_filtros[:200]}", session["id_usuario"])
        )
        conn2.commit()
        cur2.close()
        conn2.close()
    except Exception:
        pass

    return send_file(
        BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=nome_arquivo,
    )
# ==========================================
# INICIALIZAÇÃO
# ==========================================
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)