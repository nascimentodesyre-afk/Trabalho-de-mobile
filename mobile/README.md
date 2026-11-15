# IPE Mobile — Ionic + Angular

Aplicativo mobile do IPE. O backend original em Python/Flask e o banco MySQL permanecem responsáveis pelas regras de negócio e persistência.

## Requisitos
- Node.js 20+
- npm
- Backend Flask configurado e executando na porta 5000

## Executar
```bash
cd mobile
npm install
npm start
```

O proxy de desenvolvimento encaminha /api, /login e /logout para http://127.0.0.1:5000.

## Telas disponíveis
- Login com suporte à chave de acesso do perfil Patrimônio
- Página inicial com resumo de chamados
- Consulta e busca do inventário
- Listagem de chamados
- Histórico de movimentações, resumo e filtro local

## Próximas etapas
Ainda precisam ser migrados: cadastro e edição de patrimônio, criação de movimentações, baixa, reparos/manutenção, bens alugados, financeiro, relatórios, administração/backup, notificações e perfil.

## Integração e permissões
A tela de movimentações usa os endpoints já existentes GET /api/movimentacoes e GET /api/movimentacoes/resumo. A criação existe no backend em POST /api/movimentacoes, exige perfil de Patrimônio e recebe formulário com id_sala_origem, id_sala_destino, observacao e itens (JSON com IDs de patrimônio); ainda não foi ligada à interface mobile.

As operações administrativas devem respeitar os decoradores de autorização do Flask. Não considere a proteção de rotas do Angular como substituta da autorização no servidor.

## Segurança
Não inclua senhas, chaves administrativas ou credenciais do banco no aplicativo. Configure segredos no ambiente do servidor. Em produção, use HTTPS e configure a origem da API.
