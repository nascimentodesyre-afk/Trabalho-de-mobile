# ============================================================================
# CHAMADO
# ============================================================================
from .base import BaseModel


class Chamado(BaseModel):
    TABELA = "Chamado"
    CHAVE_PRIMARIA = "id_chamado"

    @classmethod
    def adicionar_usuario(cls, id_chamado, id_usuario):
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            cursor.execute("UPDATE Chamado SET id_usuario=%s WHERE id_chamado=%s",
                           (id_usuario, id_chamado))
            conn.commit(); return True
        finally:
            cursor.close(); conn.close()

    @classmethod
    def adicionar_tecnico(cls, id_chamado, id_tecnico):
        """Registra o técnico no histórico (o schema não tem coluna de técnico)."""
        from .historico import Historico
        return Historico.registrar_alteracao(id_chamado, f"Técnico #{id_tecnico} designado")

    @classmethod
    def atualizar_status(cls, id_chamado, id_status):
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            cursor.execute("UPDATE Chamado SET id_status=%s WHERE id_chamado=%s",
                           (id_status, id_chamado))
            conn.commit(); return True
        finally:
            cursor.close(); conn.close()

    @classmethod
    def atribuir_patrimonio(cls, id_chamado, id_patrimonio):
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            cursor.execute("UPDATE Chamado SET id_patrimonio=%s WHERE id_chamado=%s",
                           (id_patrimonio, id_chamado))
            conn.commit(); return True
        finally:
            cursor.close(); conn.close()

    @classmethod
    def notificar_mudanca_status(cls, id_chamado, id_status_novo):
        from .historico import Historico
        from .status import Status
        s = Status.buscar_por_id(id_status_novo)
        nome = s["nome"] if s else f"ID {id_status_novo}"
        return Historico.registrar_alteracao(id_chamado, f'Status alterado para "{nome}"')