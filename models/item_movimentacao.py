# ============================================================================
# ITEM DE MOVIMENTACAO
# ============================================================================
from .base import BaseModel


class ItemMovimentacao(BaseModel):
    TABELA = "item_movimentacao"
    CHAVE_PRIMARIA = "id_item_mov"

    @classmethod
    def validar_estoque(cls, id_patrimonio):
        from .patrimonio import Patrimonio
        p = Patrimonio.buscar_por_id(id_patrimonio)
        return bool(p and p.get("processo_baixa") is None)

    @classmethod
    def verificar_estoque(cls, id_patrimonio):
        return cls.validar_estoque(id_patrimonio)

    @classmethod
    def verificar_garantia(cls, id_patrimonio):
        from .patrimonio import Patrimonio
        from datetime import datetime, timedelta
        p = Patrimonio.buscar_por_id(id_patrimonio)
        if not p or not p.get("data_aquisicao"): return False
        try:
            data_aq = datetime.strptime(str(p["data_aquisicao"]), "%Y-%m-%d")
            return datetime.now() <= (data_aq + timedelta(days=365))
        except Exception:
            return False

    @classmethod
    def baixar_estoque(cls, id_movimentacao, id_patrimonio):
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            cursor.execute("""INSERT INTO item_movimentacao (id_movimentacao, id_patrimonio)
                              VALUES (%s, %s)""", (id_movimentacao, id_patrimonio))
            conn.commit(); return cursor.lastrowid
        finally:
            cursor.close(); conn.close()

    @classmethod
    def registrar_movimentacao(cls, id_movimentacao, id_patrimonio):
        return cls.baixar_estoque(id_movimentacao, id_patrimonio)

    @classmethod
    def vincular_item_movimentacao(cls, id_patrimonio, id_movimentacao):
        return cls.baixar_estoque(id_movimentacao, id_patrimonio)