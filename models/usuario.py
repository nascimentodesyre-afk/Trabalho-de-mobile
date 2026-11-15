# ============================================================================
# USUARIO
# ============================================================================
from .base import BaseModel
import mysql.connector


class Usuario(BaseModel):
    TABELA = "Usuario"
    CHAVE_PRIMARIA = "id_usuario"

    @classmethod
    def autenticar(cls, email, senha):
        conn = cls._conectar(); cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT * FROM Usuario WHERE e_mail = %s AND senha = %s", (email, senha))
            return cls._linha_para_dict(cursor.fetchone())
        finally:
            cursor.close(); conn.close()

    @classmethod
    def criar(cls, nome, email, senha, id_perfil=2):
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO Usuario (nome, e_mail, senha, id_perfil) VALUES (%s, %s, %s, %s)",
                           (nome, email, senha, id_perfil))
            conn.commit(); return cursor.lastrowid
        except mysql.connector.Error as e:
            conn.rollback()
            if e.errno == 1062: raise ValueError("E-mail já cadastrado.")
            raise
        finally:
            cursor.close(); conn.close()

    @classmethod
    def atualizar_perfil(cls, id_usuario, nome, email, senha=None):
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            if senha:
                cursor.execute("UPDATE Usuario SET nome=%s, e_mail=%s, senha=%s WHERE id_usuario=%s",
                               (nome, email, senha, id_usuario))
            else:
                cursor.execute("UPDATE Usuario SET nome=%s, e_mail=%s WHERE id_usuario=%s",
                               (nome, email, id_usuario))
            conn.commit(); return True
        finally:
            cursor.close(); conn.close()

    @classmethod
    def verificar_permissao(cls, id_usuario, id_perfil_necessario=1):
        u = cls.buscar_por_id(id_usuario)
        return bool(u and u["id_perfil"] == id_perfil_necessario)

    @classmethod
    def alterar_novo_perfil(cls, id_usuario, id_perfil):
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            cursor.execute("UPDATE Usuario SET id_perfil=%s WHERE id_usuario=%s", (id_perfil, id_usuario))
            conn.commit(); return True
        finally:
            cursor.close(); conn.close()

    @classmethod
    def listar_com_perfil(cls):
        conn = cls._conectar(); cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("""
                SELECT u.id_usuario, u.nome, u.e_mail, u.id_perfil,
                       IFNULL(p.nome, 'Usuário') AS nome_perfil,
                       (SELECT COUNT(*) FROM Chamado c WHERE c.id_usuario = u.id_usuario) AS total_chamados
                FROM Usuario u
                LEFT JOIN Perfil p ON u.id_perfil = p.id_perfil
                ORDER BY u.id_usuario ASC
            """)
            return [cls._linha_para_dict(l) for l in cursor.fetchall()]
        finally:
            cursor.close(); conn.close()

    # Adicione dentro da classe Usuario no seu models.py (ou no app.py se for tudo junto)
class Usuario(BaseModel):
    # ... seus atributos existentes ...

    def meus_chamados(self):
        """Retorna todos os chamados abertos por este usuário (Relação 1:N)"""
        conn = self._get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT * FROM Chamado 
            WHERE id_usuario = %s 
            ORDER BY data_abertura DESC
        """, (self.id_usuario,))
        resultado = cursor.fetchall()
        cursor.close()
        conn.close()
        return resultado