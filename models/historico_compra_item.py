# ============================================================================
# HISTORICO DE COMPRA DE ITEM
# ============================================================================
from .base import BaseModel


class HistoricoCompraItem(BaseModel):
    TABELA = "Historico_compra_item"
    CHAVE_PRIMARIA = "id_historico"

    @classmethod
    def registrar(cls, data_compra, quantidade, valor_unitario, nota_fiscal=None,
                  fornecedor=None, categoria_item=None, status_entrega="ENTREGUE", id_verba=None):
        conn = cls._conectar()
        cursor = conn.cursor()
        try:
            cursor.execute("""INSERT INTO Historico_compra_item
                              (data_compra, quantidade, valor_unitario, nota_fiscal,
                               fornecedor, categoria_item, status_entrega, id_verba)
                              VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                           (data_compra, quantidade, valor_unitario, nota_fiscal,
                            fornecedor, categoria_item, status_entrega, id_verba))
            conn.commit()
            return cursor.lastrowid
        finally:
            cursor.close()
            conn.close()

    @classmethod
    def listar_por_verba(cls, id_verba):
        conn = cls._conectar()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("""SELECT * FROM Historico_compra_item WHERE id_verba=%s
                              ORDER BY data_compra DESC""", (id_verba,))
            return [cls._linha_para_dict(l) for l in cursor.fetchall()]
        finally:
            cursor.close()
            conn.close()

    @classmethod
    def gerar_extrato_periodo(cls, data_inicio, data_fim):
        conn = cls._conectar()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("""SELECT id_historico, data_compra, quantidade, valor_unitario,
                                     (quantidade * valor_unitario) AS valor_total,
                                     nota_fiscal, fornecedor, categoria_item, status_entrega, id_verba
                              FROM Historico_compra_item
                              WHERE data_compra BETWEEN %s AND %s
                              ORDER BY data_compra ASC""", (data_inicio, data_fim))
            linhas = cursor.fetchall()
            for l in linhas:
                l["valor_unitario"] = float(l["valor_unitario"] or 0)
                l["valor_total"] = float(l["valor_total"] or 0)
            return {"periodo": {"inicio": data_inicio, "fim": data_fim},
                    "total_itens": sum(l["quantidade"] for l in linhas),
                    "total_valor": round(sum(l["valor_total"] for l in linhas), 2),
                    "compras": linhas}
        finally:
            cursor.close()
            conn.close()

    @classmethod
    def listar_por_item(cls, id_patrimonio):
        """
        Busca compras do histórico que têm a mesma nota fiscal do patrimônio.
        Útil para rastrear qual compra trouxe um bem específico.
        """
        conn = cls._conectar()
        cursor = conn.cursor(dictionary=True)
        try:
            # 1) Descobre a nota fiscal do patrimônio
            cursor.execute("SELECT nota_fiscal FROM Patrimonio WHERE id_patrimonio = %s",
                           (id_patrimonio,))
            p = cursor.fetchone()
            if not p or not p.get("nota_fiscal"):
                return []

            # 2) Busca compras com a mesma NF
            cursor.execute("""
                SELECT id_historico, data_compra, quantidade, valor_unitario,
                       (quantidade * valor_unitario) AS valor_total,
                       nota_fiscal, fornecedor, categoria_item, status_entrega, id_verba
                FROM Historico_compra_item
                WHERE nota_fiscal = %s
                ORDER BY data_compra DESC
            """, (p["nota_fiscal"],))
            linhas = cursor.fetchall()

            for l in linhas:
                l["valor_unitario"] = float(l["valor_unitario"] or 0)
                l["valor_total"] = float(l["valor_total"] or 0)

            return linhas
        finally:
            cursor.close()
            conn.close()