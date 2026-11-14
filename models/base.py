# ============================================================================
# CLASSE BASE
# ============================================================================
import mysql.connector
from decimal import Decimal
from datetime import datetime


class BaseModel:
    TABELA = None
    CHAVE_PRIMARIA = "id"

    DB_CONFIG = {
        'host': '127.0.0.1',
        'user': 'root',
        'password': '1234',
        'database': 'gestao_patrimonio',
    }

    @classmethod
    def _conectar(cls):
        return mysql.connector.connect(**cls.DB_CONFIG)

    @staticmethod
    def _serializar(valor):
        if isinstance(valor, Decimal): return float(valor)
        if isinstance(valor, datetime): return valor.strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(valor, bytes): return f"<binário: {len(valor)} bytes>"
        return valor

    @classmethod
    def _linha_para_dict(cls, linha):
        if not linha: return None
        return {k: cls._serializar(v) for k, v in linha.items()}

    # -------------------- CRUD genérico --------------------
    @classmethod
    def buscar_por_id(cls, id_valor):
        conn = cls._conectar(); cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(f"SELECT * FROM `{cls.TABELA}` WHERE `{cls.CHAVE_PRIMARIA}` = %s", (id_valor,))
            return cls._linha_para_dict(cursor.fetchone())
        finally:
            cursor.close(); conn.close()

    @classmethod
    def listar_todos(cls, ordem=None):
        conn = cls._conectar(); cursor = conn.cursor(dictionary=True)
        try:
            sql = f"SELECT * FROM `{cls.TABELA}`"
            if ordem: sql += f" ORDER BY `{ordem}` ASC"
            cursor.execute(sql)
            return [cls._linha_para_dict(l) for l in cursor.fetchall()]
        finally:
            cursor.close(); conn.close()

    @classmethod
    def excluir(cls, id_valor):
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            cursor.execute(f"DELETE FROM `{cls.TABELA}` WHERE `{cls.CHAVE_PRIMARIA}` = %s", (id_valor,))
            conn.commit()
            return cursor.rowcount > 0
        except mysql.connector.Error as e:
            conn.rollback(); print(f"Erro ao excluir em {cls.TABELA}: {e}"); return False
        finally:
            cursor.close(); conn.close()

    @classmethod
    def contar(cls):
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            cursor.execute(f"SELECT COUNT(*) FROM `{cls.TABELA}`")
            return cursor.fetchone()[0]
        finally:
            cursor.close(); conn.close()