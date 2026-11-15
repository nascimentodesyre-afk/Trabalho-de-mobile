# ============================================================================
# TIPO DE MANUTENÇÃO
# ============================================================================
from .base import BaseModel


class TipoManutencao(BaseModel):
    TABELA = "Tipo_manutencao"
    CHAVE_PRIMARIA = "id_tipo_manutencao"

    @classmethod
    def cadastrar_novo_tipo(cls, nome):
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO Tipo_manutencao (nome) VALUES (%s)", (nome,))
            conn.commit(); return cursor.lastrowid
        finally:
            cursor.close(); conn.close()

    @classmethod
    def definir_periodicidade(cls, id_tipo_manutencao, periodicidade_dias):
        """Retorna estatísticas de periodicidade dos reparos do tipo."""
        conn = cls._conectar(); cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("""
                SELECT COUNT(*) AS total,
                       IFNULL(AVG(DATEDIFF(m.data_fim, m.data_inicio)), 0) AS media_dias,
                       MIN(m.data_inicio) AS primeira,
                       MAX(m.data_fim) AS ultima
                FROM Manutencao m
                WHERE m.id_tipo_manutencao = %s
            """, (id_tipo_manutencao,))
            return cls._linha_para_dict(cursor.fetchone())
        finally:
            cursor.close(); conn.close()

    @classmethod
    def definir_custo_por_tipo(cls, id_tipo_manutencao):
        """Retorna o custo médio dos reparos desse tipo."""
        conn = cls._conectar(); cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("""
                SELECT IFNULL(AVG(v.saldo_inicial), 0) AS custo_medio,
                       IFNULL(SUM(v.saldo_inicial), 0) AS custo_total
                FROM Manutencao m
                INNER JOIN Chamado c ON c.id_chamado = m.id_chamado
                LEFT JOIN verba v ON v.descricao LIKE CONCAT('%%Chamado #', c.id_chamado, '%%')
                WHERE m.id_tipo_manutencao = %s
            """, (id_tipo_manutencao,))
            r = cursor.fetchone()
            return {"custo_medio": float(r["custo_medio"] or 0),
                    "custo_total": float(r["custo_total"] or 0)}
        finally:
            cursor.close(); conn.close()

    @classmethod
    def listar_categorias(cls):
        return cls.listar_todos(ordem="nome")