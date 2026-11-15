# ============================================================================
# PATRIMONIO
# ============================================================================
from .base import BaseModel
from datetime import datetime


class Patrimonio(BaseModel):
    TABELA = "Patrimonio"
    CHAVE_PRIMARIA = "id_patrimonio"

    @classmethod
    def cadastrar(cls, nome, numero_patrimonio, valor_atual, data_aquisicao,
                  taxa_depreciacao, id_sala, id_categoria, id_status=1,
                  descricao=None, nota_fiscal=None, origem=None, id_verba=None):
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO Patrimonio
                  (nome, numero_patrimonio, valor_atual, data_aquisicao,
                   taxa_depreciacao, id_sala, id_categoria, id_status,
                   descricao, nota_fiscal, origem, id_verba)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (nome, numero_patrimonio, float(valor_atual), data_aquisicao,
                  float(taxa_depreciacao), id_sala, id_categoria, id_status,
                  descricao, nota_fiscal, origem, id_verba))
            conn.commit(); return cursor.lastrowid
        finally:
            cursor.close(); conn.close()

    @classmethod
    def calcular_depreciacao(cls, id_patrimonio):
        p = cls.buscar_por_id(id_patrimonio)
        if not p: return 0.0
        return cls._depreciar(float(p.get("valor_atual") or 0), p.get("data_aquisicao"),
                              p.get("taxa_depreciacao"))

    @staticmethod
    def _depreciar(valor, data_aquisicao, taxa):
        try:
            anos = (datetime.now() - datetime.strptime(str(data_aquisicao), "%Y-%m-%d")).days / 365.25
            t = float(taxa or 0) / 100
            return max(round(valor * ((1 - t) ** anos), 2), 0.0)
        except Exception:
            return valor

    @classmethod
    def atualizar_depreciacao(cls, id_patrimonio):
        """Recalcula e atualiza o valor_atual do patrimônio no banco."""
        p = cls.buscar_por_id(id_patrimonio)
        if not p: return False
        novo_valor = cls._depreciar(float(p.get("valor_atual") or 0),
                                    p.get("data_aquisicao"), p.get("taxa_depreciacao"))
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            cursor.execute("UPDATE Patrimonio SET valor_atual=%s WHERE id_patrimonio=%s",
                           (novo_valor, id_patrimonio))
            conn.commit(); return novo_valor
        finally:
            cursor.close(); conn.close()

    @classmethod
    def listar_por_categoria(cls, id_categoria):
        conn = cls._conectar(); cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT * FROM Patrimonio WHERE id_categoria=%s", (id_categoria,))
            return [cls._linha_para_dict(l) for l in cursor.fetchall()]
        finally:
            cursor.close(); conn.close()

    @classmethod
    def registrar_baixa(cls, id_patrimonio, motivo, laudo, processo=None):
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            cursor.execute("""
                UPDATE Patrimonio
                SET processo_baixa = CURDATE(), id_status = 3,
                    descricao = CONCAT(IFNULL(descricao, ''),
                        '\n\n--- BAIXA EM ', DATE_FORMAT(CURDATE(), '%d/%m/%Y'), ' ---\n',
                        'Motivo: ', %s, '\n', 'Laudo: ', %s,
                        IF(%s <> '', CONCAT('\nProcesso: ', %s), ''))
                WHERE id_patrimonio = %s
            """, (motivo, laudo, processo, processo, id_patrimonio))
            conn.commit(); return True
        finally:
            cursor.close(); conn.close()

    @classmethod
    def transferir_local(cls, id_patrimonio, nova_sala, id_sala_origem=None):
        conn = cls._conectar(); cursor = conn.cursor(dictionary=True)
        try:
            if id_sala_origem is None:
                cursor.execute("SELECT id_sala FROM Patrimonio WHERE id_patrimonio=%s", (id_patrimonio,))
                row = cursor.fetchone()
                if not row: return False
                id_sala_origem = row["id_sala"]
            cursor.execute("""INSERT INTO Movimentacao (data_movimentacao, id_sala_origem, id_sala_destino)
                              VALUES (NOW(), %s, %s)""", (id_sala_origem, nova_sala))
            id_mov = cursor.lastrowid
            cursor.execute("INSERT INTO item_movimentacao (id_movimentacao, id_patrimonio) VALUES (%s, %s)",
                           (id_mov, id_patrimonio))
            cursor.execute("UPDATE Patrimonio SET id_sala=%s WHERE id_patrimonio=%s",
                           (nova_sala, id_patrimonio))
            conn.commit(); return id_mov
        except Exception:
            conn.rollback(); return False
        finally:
            cursor.close(); conn.close()

    @classmethod
    def verificar_disponibilidade(cls, id_patrimonio):
        p = cls.buscar_por_id(id_patrimonio)
        if not p: return False
        return p.get("processo_baixa") is None and p.get("id_status") in (1, 2)

    @classmethod
    def solicitar_troca_status(cls, id_patrimonio, novo_status, motivo="", id_usuario=1):
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            cursor.execute("UPDATE Patrimonio SET id_status=%s WHERE id_patrimonio=%s",
                           (novo_status, id_patrimonio))
            cursor.execute("""INSERT INTO Log_auditoria (acao, descricao, id_usuario)
                              VALUES ('UPDATE', %s, %s)""",
                           (f"Status do patrimônio #{id_patrimonio} alterado para {novo_status}. {motivo}", id_usuario))
            conn.commit(); return True
        except Exception:
            conn.rollback(); return False
        finally:
            cursor.close(); conn.close()

    @classmethod
    def gerar_historico_aquisicao(cls):
        conn = cls._conectar(); cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("""
                SELECT YEAR(data_aquisicao) AS ano, MONTH(data_aquisicao) AS mes,
                       COUNT(*) AS quantidade, SUM(valor_atual) AS valor_total,
                       AVG(valor_atual) AS valor_medio
                FROM Patrimonio WHERE data_aquisicao IS NOT NULL
                GROUP BY YEAR(data_aquisicao), MONTH(data_aquisicao)
                ORDER BY ano DESC, mes DESC
            """)
            linhas = cursor.fetchall()
            for l in linhas:
                l["valor_total"] = float(l["valor_total"] or 0)
                l["valor_medio"] = float(l["valor_medio"] or 0)
            return linhas
        finally:
            cursor.close(); conn.close()

    @classmethod
    def importar_lote(cls, lista_bens):
        """Importa uma lista de bens (lista de dicts) e retorna qtd inserida."""
        inseridos = 0
        conn = cls._conectar(); cursor = conn.cursor()
        try:
            for b in lista_bens:
                cursor.execute("""
                    INSERT INTO Patrimonio (nome, numero_patrimonio, valor_atual, data_aquisicao,
                                            taxa_depreciacao, id_sala, id_categoria, id_status,
                                            nota_fiscal, descricao)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 1, %s, %s)
                """, (b["nome"], b["numero_patrimonio"], b["valor_atual"], b["data_aquisicao"],
                      b.get("taxa_depreciacao", 10.0), b.get("id_sala"), b["id_categoria"],
                      b.get("nota_fiscal"), b.get("descricao")))
                inseridos += 1
            conn.commit(); return inseridos
        except Exception:
            conn.rollback(); return 0
        finally:
            cursor.close(); conn.close()