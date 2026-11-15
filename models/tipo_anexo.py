# ============================================================================
# TIPO DE ANEXO
# ============================================================================
from .base import BaseModel


class TipoAnexo(BaseModel):
    TABELA = "Tipo_anexo"
    CHAVE_PRIMARIA = "id_tipo_anexo"

    @classmethod
    def cadastrar_novo_tipo(cls, nome):
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO Tipo_anexo (nome) VALUES (%s)", (nome,))
            conn.commit(); return cursor.lastrowid
        finally:
            cursor.close(); conn.close()

    @classmethod
    def listar_categorias(cls):
        return cls.listar_todos(ordem="nome")