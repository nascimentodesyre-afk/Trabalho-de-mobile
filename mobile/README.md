# IPE Mobile — Ionic + Angular

Aplicativo mobile do IPE. O backend original em Python/Flask e o banco MySQL permanecem responsáveis pelas regras de negócio e persistência.

## Requisitos
- Node.js 20+
- npm
- Ionic CLI: npm install -g @ionic/cli
- Backend Flask configurado e executando na porta 5000

## Executar
```bash
cd mobile
npm install
npm start
```

O proxy de desenvolvimento encaminha /api, /login e /logout para http://127.0.0.1:5000.

## Telas nesta primeira etapa
- Login com suporte à chave exigida pelo perfil Patrimônio
- Página inicial e resumo de chamados
- Consulta e busca do inventário
- Listagem dos chamados

## Próximas etapas
Migrar cadastro/edição de patrimônio, movimentações, baixa, reparos, alugados, financeiro, relatórios, administração, backup, notificações e perfil.

## Segurança
Não inclua senhas, chaves administrativas ou credenciais do banco no aplicativo. Configure segredos no ambiente do servidor. Em produção, use HTTPS e configure a origem da API.
