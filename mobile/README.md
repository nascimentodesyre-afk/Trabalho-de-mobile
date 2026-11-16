# IPE Mobile — Ionic + Angular

Aplicativo mobile do IPE. O backend original em Python/Flask e o banco MySQL continuam responsáveis pelas regras de negócio, autorização e persistência.

## Requisitos
- Node.js 22 LTS (compatível com Angular 19)
- npm
- Backend Flask configurado e executando na porta 5000
- Banco MySQL disponível para o backend

## Executar
```bash
cd mobile
npm install
npm start
```

O proxy de desenvolvimento encaminha `/api`, `/login` e `/logout` para `http://127.0.0.1:5000`.

Para gerar o build de produção:
```bash
npm run build
```

## Telas disponíveis
- Login com suporte à chave de acesso do perfil Patrimônio
- Página inicial com resumo de chamados
- Consulta e busca do inventário
- Cadastro de patrimônio para administradores
- Listagem de chamados
- Histórico de movimentações, resumo e filtro local

Consulte [MIGRATION_STATUS.md](./MIGRATION_STATUS.md) para a matriz das rotas Flask existentes e das telas que ainda faltam.

## Integração de patrimônio
O cadastro mobile utiliza os contratos existentes do Flask:
- `GET /api/inventario/filtros`: carrega categorias, salas e status.
- `POST /api/inventario/cadastrar`: recebe `multipart/form-data` com `nome`, `numero_patrimonio`, `valor_compra`, `data_aquisicao`, `taxa_depreciacao`, `id_sala` (opcional) e `id_categoria`.

O endpoint de cadastro é protegido por `admin_required`; no backend atual, somente sessões com `id_perfil = 1` podem cadastrar. A visibilidade do atalho no app é apenas conveniência de interface: a autorização real continua no Flask.

## Lacuna conhecida: edição
O backend consultado oferece detalhes de patrimônio por `GET /api/patrimonio/<id_patrimonio>/detalhes` e atualização de dados extras por `POST /api/patrimonio/<id_patrimonio>/extra`, mas não expõe um endpoint geral para editar os campos principais do patrimônio. Por segurança, a interface não simula uma edição. Para migrar essa operação, é necessário definir e implementar no Flask um contrato autenticado de atualização (campos editáveis, validações e regras de auditoria).

## Próximas etapas
Ainda precisam ser migrados: criação de movimentações, baixa, reparos/manutenção, bens alugados, financeiro, relatórios, administração/backup, notificações e perfil.

A criação de movimentações já existe em `POST /api/movimentacoes`, exige perfil administrador e recebe formulário com `id_sala_origem`, `id_sala_destino`, `observacao` e `itens` (JSON com IDs de patrimônio); ainda não está ligada à interface mobile.

As operações administrativas devem respeitar os decoradores de autorização do Flask. O guard do Angular não substitui a autorização no servidor.

## Segurança e testes
- Não armazene senhas, chaves administrativas ou credenciais do banco no aplicativo.
- Em produção, use HTTPS e configure a origem da API.
- O projeto ainda não possui uma suíte de testes mobile configurada; valide a compilação com `npm run build` após instalar as dependências.
