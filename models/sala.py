# ============================================================================
# SALA
# ============================================================================
from .base import BaseModel


class Sala(BaseModel):
    TABELA = "Sala"
    CHAVE_PRIMARIA = "id_sala"

    @classmethod
    def cadastrar(cls, numero_sala, bloco, id_tipo_sala=1):
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO Sala (numero_sala, bloco, id_tipo_sala) VALUES (%s, %s, %s)",
                           (numero_sala, bloco, id_tipo_sala))
            conn.commit(); return cursor.lastrowid
        finally:
            cursor.close(); conn.close()

    @classmethod
    def listar_patrimonios_alocados(cls, id_sala):
        conn = cls._conectar(); cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT * FROM Patrimonio WHERE id_sala=%s ORDER BY nome", (id_sala,))
            return [cls._linha_para_dict(l) for l in cursor.fetchall()]
        finally:
            cursor.close(); conn.close()

    @classmethod
    def listar_itens_alocados(cls, id_sala):
        """Alias do diagrama."""
        return cls.listar_patrimonios_alocados(id_sala)

    @classmethod
    def verificar_responsavel(cls, id_sala, id_usuario):
        conn = cls._conectar(); cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT id_perfil FROM Usuario WHERE id_usuario=%s", (id_usuario,))
            u = cursor.fetchone()
            return bool(u and u["id_perfil"] == 1)
        finally:
            cursor.close(); conn.close()