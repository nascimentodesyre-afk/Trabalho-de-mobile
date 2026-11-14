# ============================================================================
# LANCAMENTO DE CAIXA
# ============================================================================
from .base import BaseModel


class LancamentoCaixa(BaseModel):
    TABELA = "Lancamento_caixa"
    CHAVE_PRIMARIA = "id_lancamento"

    @classmethod
    def registrar(cls, tipo_movimento, descricao, valor, forma_pagamento,
                  numero_documento, id_formulario, bimestre=None):
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            cursor.execute("""INSERT INTO Lancamento_caixa
                              (data_lancamento, tipo_movimento, descricao, valor,
                               forma_pagamento, numero_documento, bimestre, id_formulario)
                              VALUES (NOW(), %s, %s, %s, %s, %s, %s, %s)""",
                           (tipo_movimento, descricao, valor, forma_pagamento,
                            numero_documento, bimestre, id_formulario))
            conn.commit(); return cursor.lastrowid
        finally:
            cursor.close(); conn.close()

    @classmethod
    def excluir_lancamento(cls, id_lancamento):
        return cls.excluir(id_lancamento)