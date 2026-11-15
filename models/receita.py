# ============================================================================
# RECEITA
# ============================================================================
from .base import BaseModel


class Receita(BaseModel):
    TABELA = "Receita"
    CHAVE_PRIMARIA = "id_receita"

    @classmethod
    def emitir_comprovante(cls, id_receita):
        return cls.buscar_por_id(id_receita)

    @classmethod
    def calcular_saldo_acumulado(cls):
        conn = cls._conectar(); cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("""SELECT IFNULL(SUM(lc.valor), 0) AS total
                              FROM Receita r
                              INNER JOIN Lancamento_caixa lc ON lc.id_lancamento = r.id_lancamento""")
            r = cursor.fetchone()
            return float(r["total"] or 0)
        finally:
            cursor.close(); conn.close()