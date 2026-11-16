# Migração mobile — estado dos módulos

Esta matriz foi conferida com as rotas declaradas em `app.py` e os modelos em `models/` na branch `ionic-conversion`. A existência de uma rota não significa que a interface mobile já a utiliza.

## Já disponível no mobile

| Módulo | Situação |
|---|---|
| Login | Integrado a `POST /login` usando sessão Flask |
| Início | Integrado a `GET /api/dados_usuario` |
| Inventário | Consulta e busca local usando `GET /api/inventario/listar` |
| Cadastro de patrimônio | Formulário integrado a `GET /api/inventario/filtros` e `POST /api/inventario/cadastrar` |
| Chamados | Listagem integrada a `GET /api/chamados` |
| Movimentações | Consulta e resumo integrados a `GET /api/movimentacoes` e `GET /api/movimentacoes/resumo` |

## Funcionalidades ainda não migradas

| Módulo | Rotas Flask encontradas | Observações para a migração |
|---|---|---|
| Edição de patrimônio | `GET /api/patrimonio/<id>/detalhes`; `POST /api/patrimonio/<id>/extra` | Não foi encontrada rota geral de atualização dos campos principais do bem. A rota `/extra` trata somente dados extras; não implementar edição completa até definir contrato e validações no backend. |
| Movimentações — criação/exclusão | `POST /api/movimentacoes`; `DELETE /api/movimentacoes/<id>` | Criação exige autorização administrativa e recebe formulário com sala de origem, sala de destino, observação e lista JSON de IDs de patrimônio. Detalhes usam `GET /api/movimentacoes/<id>`. |
| Baixa | `GET /api/baixa/verificar/<id>`; `POST /api/baixa/registrar`; `GET /api/baixa/listar`; `GET /api/baixa/resumo` | Rotas protegidas por `admin_required`. O registro exige patrimônio, motivo permitido, laudo com pelo menos 10 caracteres e bloqueia bens com chamados ativos. |
| Reparos/manutenção | `GET /api/reparos/ranking`; `GET /api/reparos/resumo`; `GET /api/reparos/patrimonio/<id>`; `GET /api/manutencao/<id_chamado>`; `POST /api/manutencao/estimar`; `POST /api/manutencao/iniciar`; `POST /api/manutencao/finalizar` | As operações de escrita são administrativas. Conferir os campos exigidos em cada função antes de criar formulários. |
| Bens alugados | `GET /api/alugados/listar`; `GET /api/alugados/resumo`; `POST /api/alugados/cadastrar`; `PUT/POST /api/alugados/<id>`; `DELETE /api/alugados/<id>` | Rotas protegidas por `admin_required`. A listagem aceita filtros de busca, fornecedor, vencimento e inclusão de contratos vencidos. |
| Financeiro | `GET /api/financeiro/resumo`; `GET/POST /api/financeiro/movimentacoes`; `PUT/POST/DELETE /api/financeiro/movimentacoes/<id>`; `GET /api/financeiro/categorias`; `GET /api/financeiro/verbas`; `GET /api/financeiro/grafico`; `GET /api/financeiro/origens`; `GET /api/financeiro/resumo-por-origem` | Todas as rotas identificadas estão protegidas por `admin_required`. Mapear os campos e enums dos modelos `Lancamento_caixa`, `Despesa`, `Receita` e `verba` antes de ligar os formulários. |
| Relatórios | `GET /api/relatorios/resumo`; `GET /api/relatorios/exportar-csv`; `GET /api/relatorios/exportar-excel` | Rotas protegidas por `patrimonio_required`; o resumo aceita ano e período. |
| Administração | `GET /api/admin/estatisticas`; `GET /api/usuarios`; `POST /api/usuarios/<id>/perfil`; `DELETE /api/usuarios/<id>`; `GET/POST /api/log-auditoria`; rotas `/api/backup/*` | Respeitar a distinção entre `admin_required` e `patrimonio_required`. Exportações e exclusões devem ter confirmação explícita na interface. |
| Notificações | `GET /api/notificacoes`; `GET/POST /api/notificacoes/config-smtp`; `POST /api/notificacoes/testar-smtp`; `GET /api/notificacoes/destinatarios`; `POST /api/notificacoes/enviar`; `GET /api/notificacoes/historico` | Configuração e envio são administrativos. A listagem `GET /api/notificacoes` não declara decorator de autorização no ponto de entrada; revisar a sessão/permissão no backend antes de expor dados no app. |
| Perfil | `GET /api/dados_usuario`; `POST /atualizar_perfil` | A consulta valida a sessão e retorna JSON. A atualização atual é um formulário HTML com redirect/flash, não um contrato JSON adequado ao mobile; definir resposta de API antes de integrar. |

## Contratos já usados no cadastro mobile

- `GET /api/inventario/filtros` retorna `categorias`, `salas` e `status`.
- `POST /api/inventario/cadastrar` recebe `multipart/form-data`: `nome`, `numero_patrimonio`, `valor_compra`, `data_aquisicao`, `taxa_depreciacao`, `id_sala` (opcional) e `id_categoria`.
- O app envia `Accept: application/json` e `X-Requested-With: XMLHttpRequest`, que fazem o Flask responder com JSON em sucesso e erro.
- O endpoint de cadastro usa `admin_required`; a verificação definitiva permanece no servidor.

## Segurança e validação pendente

- Não colocar credenciais de banco, tokens, chaves administrativas ou configuração SMTP no pacote mobile.
- A configuração do backend contém uma credencial de banco fixa no código-fonte. Ela não foi copiada para o app; antes de publicar/compartilhar o repositório, migrar esse segredo para variável de ambiente e rotacionar a credencial atual.
- O projeto mobile não declara uma suíte de testes automatizados. O comando de build disponível é `npm run build`.
- Nesta execução não foi possível instalar dependências nem executar o build no ambiente remoto porque o acesso de rede ao GitHub/DNS está indisponível. O código foi revisado contra os contratos estáticos do Flask; ainda precisa de `npm install` e `npm run build` em um ambiente com acesso ao npm.
