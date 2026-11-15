# ============================================================================
# TIPO DE CHAMADO
# ============================================================================
from .base import BaseModel


class TipoChamado(BaseModel):
    TABELA = "Tipo_chamado"
    CHAVE_PRIMARIA = "id_tipo_chamado"

    @classmethod
    def cadastrar_novo_tipo(cls, nome):
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO Tipo_chamado (nome) VALUES (%s)", (nome,))
            conn.commit(); return cursor.lastrowid
        finally:
            cursor.close(); conn.close()

    @classmethod
    def listar_categorias(cls):
        return cls.listar_todos(ordem="nome")