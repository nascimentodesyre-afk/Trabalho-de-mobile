# ============================================================================
# HISTORICO
# ============================================================================
from .base import BaseModel


class Historico(BaseModel):
    TABELA = "Historico"
    CHAVE_PRIMARIA = "id_historico"

    @classmethod
    def registrar_alteracao(cls, id_chamado, descricao):
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            cursor.execute("""INSERT INTO Historico (data_evento, descricao, id_chamado)
                              VALUES (NOW(), %s, %s)""", (descricao, id_chamado))
            conn.commit(); return cursor.lastrowid
        finally:
            cursor.close(); conn.close()

    @classmethod
    def registrar_evento(cls, tipo_evento, descricao, id_chamado):
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            cursor.execute("""INSERT INTO Historico (tipo_evento, data_evento, descricao, id_chamado)
                              VALUES (%s, NOW(), %s, %s)""", (tipo_evento, descricao, id_chamado))
            conn.commit(); return cursor.lastrowid
        finally:
            cursor.close(); conn.close()

    @classmethod
    def listar_historico_evento(cls, id_chamado):
        conn = cls._conectar(); cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("""SELECT * FROM Historico WHERE id_chamado=%s
                              ORDER BY id_historico DESC""", (id_chamado,))
            return [cls._linha_para_dict(l) for l in cursor.fetchall()]
        finally:
            cursor.close(); conn.close()