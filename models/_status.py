# ============================================================================
# STATUS
# ============================================================================
from .base import BaseModel


class Status(BaseModel):
    TABELA = "_status"
    CHAVE_PRIMARIA = "id_status"

    @classmethod
    def alterar_status_novo(cls, id_patrimonio, id_status_novo):
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            cursor.execute("UPDATE Patrimonio SET id_status=%s WHERE id_patrimonio=%s",
                           (id_status_novo, id_patrimonio))
            conn.commit(); return True
        finally:
            cursor.close(); conn.close()