# ============================================================================
# DESPESA
# ============================================================================
from .base import BaseModel


class Despesa(BaseModel):
    TABELA = "Despesa"
    CHAVE_PRIMARIA = "id_despesa"

    @classmethod
    def listar_despesas(cls):
        conn = cls._conectar(); cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("""SELECT d.*, lc.descricao, lc.data_lancamento
                              FROM Despesa d
                              INNER JOIN Lancamento_caixa lc ON lc.id_lancamento = d.id_lancamento
                              ORDER BY lc.data_lancamento DESC""")
            return [cls._linha_para_dict(l) for l in cursor.fetchall()]
        finally:
            cursor.close(); conn.close()

    @classmethod
    def autorizar(cls, id_despesa):
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            cursor.execute("UPDATE Despesa SET aprovacao=1 WHERE id_despesa=%s", (id_despesa,))
            conn.commit(); return True
        finally:
            cursor.close(); conn.close()

    @classmethod
    def anexar_comprovante(cls, id_despesa, comprovante_blob):
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            cursor.execute("""UPDATE Lancamento_caixa lc
                              INNER JOIN Despesa d ON d.id_lancamento = lc.id_lancamento
                              SET lc.comprovante = %s
                              WHERE d.id_despesa = %s""", (comprovante_blob, id_despesa))
            conn.commit(); return True
        finally:
            cursor.close(); conn.close()