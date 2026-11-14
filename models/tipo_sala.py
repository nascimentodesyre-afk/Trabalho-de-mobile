# ============================================================================
# TIPO DE SALA
# ============================================================================
from .base import BaseModel


class TipoSala(BaseModel):
    TABELA = "Tipo_sala"
    CHAVE_PRIMARIA = "id_tipo_sala"

    @classmethod
    def cadastrar_novo_tipo(cls, nome):
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO Tipo_sala (nome) VALUES (%s)", (nome,))
            conn.commit(); return cursor.lastrowid
        finally:
            cursor.close(); conn.close()

    @classmethod
    def listar_categorias(cls):
        return cls.listar_todos(ordem="nome")