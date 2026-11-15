# ============================================================================
# TIPO DE ALERTA
# ============================================================================
from .base import BaseModel


class TipoAlerta(BaseModel):
    TABELA = "Tipo_alerta"
    CHAVE_PRIMARIA = "id_tipo_alerta"

    @classmethod
    def cadastrar_novo_tipo(cls, nome):
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO Tipo_alerta (nome) VALUES (%s)", (nome,))
            conn.commit(); return cursor.lastrowid
        finally:
            cursor.close(); conn.close()

    @classmethod
    def listar_categorias(cls):
        return cls.listar_todos(ordem="nome")