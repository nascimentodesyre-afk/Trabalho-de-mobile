# ============================================================================
# FORMULARIO DE CAIXA
# ============================================================================
from .base import BaseModel


class FormularioCaixa(BaseModel):
    TABELA = "Formulario_caixa"
    CHAVE_PRIMARIA = "id_formulario"

    @classmethod
    def criar(cls, data_servico, forma_pagamento, objeto_servico,
              periodo_referencia, bimestre_referencia):
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            cursor.execute("""INSERT INTO Formulario_caixa
                              (data_servico, forma_pagamento, objeto_servico,
                               periodo_referencia, data_geracao, status, bimestre_referencia)
                              VALUES (%s, %s, %s, %s, NOW(), 'Aberto', %s)""",
                           (data_servico, forma_pagamento, objeto_servico,
                            periodo_referencia, bimestre_referencia))
            conn.commit(); return cursor.lastrowid
        finally:
            cursor.close(); conn.close()

    @classmethod
    def gerar_resumo(cls, id_formulario):
        conn = cls._conectar(); cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("""SELECT SUM(CASE WHEN tipo_movimento='Receita' THEN valor ELSE 0 END) AS entradas,
                                     SUM(CASE WHEN tipo_movimento='Despesa' THEN valor ELSE 0 END) AS saidas,
                                     COUNT(*) AS total
                              FROM Lancamento_caixa WHERE id_formulario=%s""", (id_formulario,))
            r = cursor.fetchone() or {}
            e, s = float(r.get("entradas") or 0), float(r.get("saidas") or 0)
            return {"entradas": e, "saidas": s, "saldo": round(e - s, 2),
                    "movimentacoes": int(r.get("total") or 0)}
        finally:
            cursor.close(); conn.close()

    @classmethod
    def listar_despesas(cls, id_formulario):
        conn = cls._conectar(); cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("""SELECT lc.*, d.categoria, d.aprovacao
                              FROM Lancamento_caixa lc
                              INNER JOIN Despesa d ON d.id_lancamento = lc.id_lancamento
                              WHERE lc.id_formulario = %s
                              ORDER BY lc.data_lancamento DESC""", (id_formulario,))
            return [cls._linha_para_dict(l) for l in cursor.fetchall()]
        finally:
            cursor.close(); conn.close()

    @classmethod
    def calcular_fluxo_caixa(cls, id_formulario=None):
        conn = cls._conectar(); cursor = conn.cursor(dictionary=True)
        try:
            if id_formulario:
                cursor.execute("""SELECT tipo_movimento, IFNULL(SUM(valor), 0) AS total
                                  FROM Lancamento_caixa WHERE id_formulario=%s
                                  GROUP BY tipo_movimento""", (id_formulario,))
            else:
                cursor.execute("""SELECT tipo_movimento, IFNULL(SUM(valor), 0) AS total
                                  FROM Lancamento_caixa GROUP BY tipo_movimento""")
            e = s = 0.0
            for r in cursor.fetchall():
                if r["tipo_movimento"] == "Receita": e += float(r["total"] or 0)
                else: s += float(r["total"] or 0)
            return {"entradas": e, "saidas": s, "saldo": round(e - s, 2)}
        finally:
            cursor.close(); conn.close()

    @classmethod
    def exportar_fluxo_caixa(cls, id_formulario=None):
        return cls.calcular_fluxo_caixa(id_formulario)

    @classmethod
    def gerar_receita(cls, id_formulario):
        conn = cls._conectar(); cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("""SELECT lc.id_lancamento, lc.descricao, lc.valor,
                                     DATE_FORMAT(lc.data_lancamento, '%d/%m/%Y') AS data_formatada,
                                     lc.forma_pagamento, lc.numero_documento
                              FROM Lancamento_caixa lc
                              INNER JOIN Receita r ON r.id_lancamento = lc.id_lancamento
                              WHERE lc.id_formulario=%s AND lc.tipo_movimento='Receita'
                              ORDER BY lc.data_lancamento DESC""", (id_formulario,))
            receitas = cursor.fetchall()
            for r in receitas: r["valor"] = float(r["valor"] or 0)
            return receitas
        finally:
            cursor.close(); conn.close()

    @classmethod
    def gerar_despesa(cls, id_formulario):
        conn = cls._conectar(); cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("""SELECT lc.id_lancamento, lc.descricao, lc.valor,
                                     DATE_FORMAT(lc.data_lancamento, '%d/%m/%Y') AS data_formatada,
                                     lc.forma_pagamento, lc.numero_documento,
                                     d.categoria, d.aprovacao
                              FROM Lancamento_caixa lc
                              INNER JOIN Despesa d ON d.id_lancamento = lc.id_lancamento
                              WHERE lc.id_formulario=%s AND lc.tipo_movimento='Despesa'
                              ORDER BY lc.data_lancamento DESC""", (id_formulario,))
            despesas = cursor.fetchall()
            for d in despesas: d["valor"] = float(d["valor"] or 0)
            return despesas
        finally:
            cursor.close(); conn.close()