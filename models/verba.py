# ============================================================================
# VERBA
# ============================================================================
from .base import BaseModel


class Verba(BaseModel):
    TABELA = "Verba"
    CHAVE_PRIMARIA = "id_verba"

    @classmethod
    def cadastrar(cls, nome, descricao, ano_referencia, saldo_inicial,
                  id_tipo_verba, num_alunos=0):
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            cursor.execute("""INSERT INTO Verba (nome, descricao, ano_referencia, saldo_inicial,
                                                saldo_atual, num_alunos, saldo_bloqueado, id_tipo_verba)
                              VALUES (%s, %s, %s, %s, %s, %s, 0, %s)""",
                           (nome, descricao, ano_referencia, saldo_inicial,
                            saldo_inicial, num_alunos, id_tipo_verba))
            conn.commit(); return cursor.lastrowid
        finally:
            cursor.close(); conn.close()

    @classmethod
    def calcular_saldo_disponivel(cls, id_verba):
        v = cls.buscar_por_id(id_verba)
        if not v: return 0.0
        return round(float(v.get("saldo_atual") or 0) - float(v.get("saldo_bloqueado") or 0), 2)

    @classmethod
    def verificar_saldo_disponivel(cls, id_verba, valor_necessario):
        return cls.calcular_saldo_disponivel(id_verba) >= float(valor_necessario)

    @classmethod
    def vincular_processo_compra(cls, id_verba, id_historico_compra):
        """Vincula uma compra do histórico à verba."""
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            cursor.execute("""UPDATE Historico_compra_item SET id_verba=%s
                              WHERE id_historico=%s""", (id_verba, id_historico_compra))
            conn.commit(); return cursor.rowcount > 0
        finally:
            cursor.close(); conn.close()

    @classmethod
    def gerar_historico_aplicacoes(cls, id_verba):
        conn = cls._conectar(); cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("""
                SELECT lc.id_lancamento, lc.descricao, lc.valor,
                       lc.data_lancamento, lc.tipo_movimento
                FROM Lancamento_caixa lc
                INNER JOIN Despesa d ON d.id_lancamento = lc.id_lancamento
                WHERE d.id_verba = %s
                ORDER BY lc.data_lancamento DESC
            """, (id_verba,))
            return [cls._linha_para_dict(l) for l in cursor.fetchall()]
        finally:
            cursor.close(); conn.close()

    @classmethod
    def importar_todas_origens(cls, origem):
        todas = cls.listar_todos(ordem="nome")
        return [v for v in todas if f"[ORIGEM:{origem}]" in (v.get("nome") or "")]

    @classmethod
    def gerar_relatorio_financeiro(cls, periodo="mensal"):
        conn = cls._conectar(); cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("""SELECT id_verba, nome, ano_referencia, saldo_inicial,
                                     saldo_atual, saldo_bloqueado, id_tipo_verba
                              FROM Verba ORDER BY ano_referencia DESC, nome ASC""")
            verbas = cursor.fetchall()
            ti = ta = tb = 0.0
            for v in verbas:
                v["saldo_inicial"] = float(v["saldo_inicial"] or 0)
                v["saldo_atual"] = float(v["saldo_atual"] or 0)
                v["saldo_bloqueado"] = float(v["saldo_bloqueado"] or 0)
                v["saldo_disponivel"] = round(v["saldo_atual"] - v["saldo_bloqueado"], 2)
                ti += v["saldo_inicial"]; ta += v["saldo_atual"]; tb += v["saldo_bloqueado"]
            return {"periodo": periodo, "total_verbas": len(verbas),
                    "total_inicial": round(ti, 2), "total_atual": round(ta, 2),
                    "total_bloqueado": round(tb, 2),
                    "total_disponivel": round(ta - tb, 2), "verbas": verbas}
        finally:
            cursor.close(); conn.close()

    @classmethod
    def atualizar_saldo(cls, id_verba, valor, operacao="debito"):
        if operacao not in ("debito", "credito"):
            raise ValueError("Operação inválida. Use 'debito' ou 'credito'.")
        conn = cls._conectar(); cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT saldo_atual FROM Verba WHERE id_verba=%s", (id_verba,))
            row = cursor.fetchone()
            if not row: return False
            novo = float(row["saldo_atual"] or 0)
            novo = novo - float(valor) if operacao == "debito" else novo + float(valor)
            cursor.execute("UPDATE Verba SET saldo_atual=%s WHERE id_verba=%s",
                           (round(novo, 2), id_verba))
            conn.commit(); return True
        finally:
            cursor.close(); conn.close()