# ============================================================================
# LOG DE AUDITORIA
# ============================================================================
from .base import BaseModel


class LogAuditoria(BaseModel):
    TABELA = "Log_auditoria"
    CHAVE_PRIMARIA = "id_log"

    @classmethod
    def registrar_log(cls, acao, descricao, id_usuario):
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            cursor.execute("""INSERT INTO Log_auditoria (acao, descricao, id_usuario)
                              VALUES (%s, %s, %s)""", (acao[:100], descricao[:1000], id_usuario))
            conn.commit(); return cursor.lastrowid
        finally:
            cursor.close(); conn.close()

    @classmethod
    def registrar_log_usuario_novo(cls, id_usuario, nome):
        return cls.registrar_log("INSERT", f"Usuário cadastrado: {nome}", id_usuario)

    @classmethod
    def listar_linha_tempo_chamado(cls, id_chamado):
        conn = cls._conectar(); cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("""SELECT * FROM Log_auditoria WHERE descricao LIKE %s
                              ORDER BY id_log DESC""", (f"%chamado #{id_chamado}%",))
            return [cls._linha_para_dict(l) for l in cursor.fetchall()]
        finally:
            cursor.close(); conn.close()

    @classmethod
    def listar_historico_evento(cls, id_chamado):
        from .historico import Historico
        return Historico.listar_historico_evento(id_chamado)

    @classmethod
    def listar_historico(cls, limite=200):
        conn = cls._conectar(); cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("""SELECT l.id_log, l.acao,
                                     DATE_FORMAT(l.data, '%d/%m/%Y %H:%i') AS data_formatada,
                                     l.descricao, IFNULL(u.nome, 'Sistema') AS nome_usuario
                              FROM Log_auditoria l
                              LEFT JOIN Usuario u ON l.id_usuario = u.id_usuario
                              ORDER BY l.id_log DESC LIMIT %s""", (limite,))
            return [cls._linha_para_dict(l) for l in cursor.fetchall()]
        finally:
            cursor.close(); conn.close()