# ============================================================================
# MOVIMENTACAO
# ============================================================================
from .base import BaseModel


class Movimentacao(BaseModel):
    TABELA = "Movimentacao"
    CHAVE_PRIMARIA = "id_movimentacao"

    @classmethod
    def registrar_saida(cls, id_sala_origem, id_sala_destino):
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            cursor.execute("""INSERT INTO Movimentacao (data_movimentacao, id_sala_origem, id_sala_destino)
                              VALUES (NOW(), %s, %s)""", (id_sala_origem, id_sala_destino))
            conn.commit(); return cursor.lastrowid
        finally:
            cursor.close(); conn.close()

    @classmethod
    def transferir_item(cls, id_movimentacao, id_patrimonio, id_sala_destino):
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            cursor.execute("""INSERT INTO item_movimentacao (id_movimentacao, id_patrimonio)
                              VALUES (%s, %s)""", (id_movimentacao, id_patrimonio))
            cursor.execute("UPDATE Patrimonio SET id_sala=%s WHERE id_patrimonio=%s",
                           (id_sala_destino, id_patrimonio))
            conn.commit(); return True
        finally:
            cursor.close(); conn.close()

    @classmethod
    def rastrear_historico_local(cls, id_patrimonio):
        conn = cls._conectar(); cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("""
                SELECT m.id_movimentacao, m.data_movimentacao,
                       so.numero_sala AS origem, sd.numero_sala AS destino
                FROM Movimentacao m
                INNER JOIN item_movimentacao im ON im.id_movimentacao = m.id_movimentacao
                LEFT JOIN Sala so ON m.id_sala_origem = so.id_sala
                LEFT JOIN Sala sd ON m.id_sala_destino = sd.id_sala
                WHERE im.id_patrimonio = %s
                ORDER BY m.data_movimentacao DESC
            """, (id_patrimonio,))
            return [cls._linha_para_dict(l) for l in cursor.fetchall()]
        finally:
            cursor.close(); conn.close()