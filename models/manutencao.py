# ============================================================================
# MANUTENCAO
# ============================================================================
from .base import BaseModel


class Manutencao(BaseModel):
    TABELA = "Manutencao"
    CHAVE_PRIMARIA = "id_manutencao"

    @classmethod
    def iniciar_reparo(cls, id_chamado):
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            cursor.execute("UPDATE Manutencao SET data_inicio=NOW() WHERE id_chamado=%s", (id_chamado,))
            cursor.execute("UPDATE Chamado SET id_status=2 WHERE id_chamado=%s", (id_chamado,))
            conn.commit(); return True
        finally:
            cursor.close(); conn.close()

    @classmethod
    def finalizar_com_sucesso(cls, id_chamado):
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            cursor.execute("UPDATE Manutencao SET data_fim=NOW() WHERE id_chamado=%s", (id_chamado,))
            cursor.execute("UPDATE Chamado SET id_status=3 WHERE id_chamado=%s", (id_chamado,))
            conn.commit(); return True
        finally:
            cursor.close(); conn.close()

    @classmethod
    def estimar_custo(cls, id_chamado, custo_estimado, descricao_servico=""):
        conn = cls._conectar(); cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT id_manutencao FROM Manutencao WHERE id_chamado=%s", (id_chamado,))
            existe = cursor.fetchone()
            if existe:
                cursor.execute("UPDATE Manutencao SET observacao=%s WHERE id_chamado=%s",
                               (descricao_servico, id_chamado))
            else:
                cursor.execute("""INSERT INTO Manutencao (id_chamado, data_inicio, data_fim, observacao, id_tipo_manutencao)
                                  VALUES (%s, CURDATE(), CURDATE(), %s, 1)""", (id_chamado, descricao_servico))
            conn.commit(); return True
        finally:
            cursor.close(); conn.close()

    @classmethod
    def definir_periodicidade(cls, id_tipo_manutencao, periodicidade_dias):
        from .tipo_manutencao import TipoManutencao
        return TipoManutencao.definir_periodicidade(id_tipo_manutencao, periodicidade_dias)

    @classmethod
    def definir_custo_por_tipo(cls, id_tipo_manutencao):
        from .tipo_manutencao import TipoManutencao
        return TipoManutencao.definir_custo_por_tipo(id_tipo_manutencao)