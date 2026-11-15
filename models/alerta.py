# ============================================================================
# ALERTA
# ============================================================================
from .base import BaseModel


class Alerta(BaseModel):
    TABELA = "Alerta"
    CHAVE_PRIMARIA = "id_alerta"

    @classmethod
    def criar(cls, data_vencimento, mensagem, id_tipo_alerta=1):
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            cursor.execute("""INSERT INTO Alerta (data_vencimento, mensagem, id_tipo_alerta)
                              VALUES (%s, %s, %s)""", (data_vencimento, mensagem, id_tipo_alerta))
            conn.commit(); return cursor.lastrowid
        finally:
            cursor.close(); conn.close()

    @classmethod
    def disparar_notificacao(cls, mensagem, id_tipo_alerta=1):
        from datetime import date, timedelta
        return cls.criar(date.today() + timedelta(days=1), mensagem, id_tipo_alerta)

    @classmethod
    def verificar_prazo(cls):
        conn = cls._conectar(); cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("""SELECT id_alerta, mensagem, data_vencimento
                              FROM Alerta WHERE data_vencimento <= CURDATE()""")
            return [cls._linha_para_dict(l) for l in cursor.fetchall()]
        finally:
            cursor.close(); conn.close()

    @classmethod
    def confirmar_vencimento_garantia(cls, id_patrimonio):
        return cls.disparar_notificacao(f"Verificar garantia do patrimônio #{id_patrimonio}",
                                        id_tipo_alerta=2)