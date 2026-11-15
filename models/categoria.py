# ============================================================================
# CATEGORIA
# ============================================================================
from .base import BaseModel
from datetime import datetime


class Categoria(BaseModel):
    TABELA = "Categoria"
    CHAVE_PRIMARIA = "id_categoria"

    @classmethod
    def listar_todas(cls):
        return cls.listar_todos(ordem="nome")

    @classmethod
    def calcular_depreciacao_por_categoria(cls, id_categoria):
        conn = cls._conectar(); cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("""SELECT p.valor_atual, p.data_aquisicao, p.taxa_depreciacao
                              FROM Patrimonio p WHERE p.id_categoria=%s""", (id_categoria,))
            total = 0.0
            for p in cursor.fetchall():
                valor = float(p["valor_atual"] or 0)
                try:
                    anos = (datetime.now() - datetime.strptime(str(p["data_aquisicao"]), "%Y-%m-%d")).days / 365.25
                    taxa = float(p["taxa_depreciacao"] or 0) / 100
                    total += valor * (1 - (1 - taxa) ** anos)
                except Exception: pass
            return round(total, 2)
        finally:
            cursor.close(); conn.close()