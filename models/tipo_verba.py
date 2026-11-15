# ============================================================================
# TIPO DE VERBA
# ============================================================================
from .base import BaseModel


class TipoVerba(BaseModel):
    TABELA = "Tipo_verba"
    CHAVE_PRIMARIA = "id_tipo_verba"

    @classmethod
    def cadastrar_novo_tipo(cls, nome, regra_calculo=None):
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO Tipo_verba (nome, regra_calculo) VALUES (%s, %s)",
                           (nome, regra_calculo))
            conn.commit(); return cursor.lastrowid
        finally:
            cursor.close(); conn.close()

    @classmethod
    def listar_categorias(cls):
        return cls.listar_todos(ordem="nome")

    @classmethod
    def calcular_valor_anual(cls, id_tipo_verba, numero_alunos=0):
        conn = cls._conectar(); cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("""SELECT IFNULL(SUM(saldo_inicial), 0) AS total, COUNT(*) AS qtd
                              FROM Verba WHERE id_tipo_verba = %s""", (id_tipo_verba,))
            r = cursor.fetchone()
            total = float(r["total"] or 0)
            cota = (total / numero_alunos) if numero_alunos > 0 else 0
            return {"id_tipo_verba": id_tipo_verba, "qtd_verbas": int(r["qtd"] or 0),
                    "total_anual": round(total, 2), "numero_alunos": numero_alunos,
                    "cota_por_aluno": round(cota, 2)}
        finally:
            cursor.close(); conn.close()

    @classmethod
    def calcular_cota_aluno(cls, id_tipo_verba):
        conn = cls._conectar(); cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("""SELECT IFNULL(AVG(CASE WHEN num_alunos > 0 THEN saldo_inicial/num_alunos END), 0) AS media
                              FROM Verba WHERE id_tipo_verba=%s""", (id_tipo_verba,))
            r = cursor.fetchone()
            return float(r["media"] or 0)
        finally:
            cursor.close(); conn.close()