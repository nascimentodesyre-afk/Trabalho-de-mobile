# ============================================================================
# ANEXO
# ============================================================================
from .base import BaseModel
import os


EXTENSOES_PERMITIDAS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf"}


class Anexo(BaseModel):
    TABELA = "Anexo"
    CHAVE_PRIMARIA = "id_anexo"

    @classmethod
    def registrar(cls, caminho, id_chamado, id_tipo_anexo=1, comprovante=None):
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            cursor.execute("""INSERT INTO Anexo (caminho, data_upload, comprovante, id_tipo_anexo, id_chamado)
                              VALUES (%s, NOW(), %s, %s, %s)""",
                           (caminho, comprovante, id_tipo_anexo, id_chamado))
            conn.commit(); return cursor.lastrowid
        finally:
            cursor.close(); conn.close()

    @classmethod
    def validar_extensao(cls, nome_arquivo):
        ext = os.path.splitext(nome_arquivo or "")[1].lower()
        return ext in EXTENSOES_PERMITIDAS

    @classmethod
    def baixar_upload(cls, id_anexo):
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            cursor.execute("SELECT comprovante FROM Anexo WHERE id_anexo=%s", (id_anexo,))
            row = cursor.fetchone()
            return row[0] if row else None
        finally:
            cursor.close(); conn.close()

    @classmethod
    def excluir_arquivo(cls, id_anexo):
        a = cls.buscar_por_id(id_anexo)
        if not a: return False
        try:
            if a.get("caminho") and os.path.exists(a["caminho"]):
                os.remove(a["caminho"])
        except Exception: pass
        return cls.excluir(id_anexo)