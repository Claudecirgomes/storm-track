# Preparar a transferência para Supabase

O SQLite continua sendo o padrão. O backend também aceita PostgreSQL 14+,
incluindo Supabase, quando `STORMTRACK_DATABASE_URL` está definida.
A configuração usa conexão SQL direta ou o Session pooler (porta 5432),
com SSL por padrão. O Transaction pooler do Supabase (6543) não é suportado:
a aplicação mantém o schema da sessão. Copie a URL do botão Connect do
Supabase; codifique os caracteres reservados da senha na URL.

Referência: https://supabase.com/docs/guides/database/connecting-to-postgres

## O que está preparado

- Adaptador opcional em `backend/app/core/postgres.py`.
- Schema em `backend/app/core/postgres_schema.sql`: todas as 12 tabelas atuais,
  chaves, índices, gates, proteção de registros imutáveis e exclusão de usuários.
- Dados em schema privado `stormtrack`. O frontend acessa a API FastAPI; as
  tabelas e as credenciais do banco não são entregues ao navegador.
- A autenticação continua sendo a do StormTrack. Os hashes de senhas existentes
  são preservados; a preparação não migra contas para Supabase Auth.
- Ferramenta de inspeção/cópia transacional, com verificação de contagens e
  hashes do conteúdo. IDs, JSON, gates e auditoria são mantidos.
- Sessões não são copiadas: todos devem entrar novamente após a troca.

## Simular agora, sem Supabase

Na raiz do projeto, com o ambiente Python ativo:

```powershell
python -m backend.app.scripts.migrate_to_postgres --source ".\data\stormtrack.sqlite3"
```

O comando padrão apenas abre uma fotografia consistente do SQLite em modo
somente leitura e apresenta as contagens previstas. Não conecta ao destino,
não transfere dados e não altera o SQLite. Uma origem antiga sem `deleted_at`
recebe o campo nulo somente na fotografia em memória.

## Transferir quando necessário

1. Pare o backend e a coleta durante a troca e guarde uma cópia do SQLite.
2. Crie o projeto Supabase e obtenha uma URL de conexão direta ou Session pooler.
3. Instale as dependências opcionais no ambiente usado pelo backend:

```powershell
python -m pip install -r requirements-postgres.txt
```

4. Defina a URL apenas no ambiente do backend. No PowerShell, a entrada abaixo
   fica oculta e evita colocar a URL em texto no comando salvo no histórico:

```powershell
$stormtrackConnection = Read-Host "URL PostgreSQL do Supabase" -AsSecureString
$env:STORMTRACK_DATABASE_URL = [System.Net.NetworkCredential]::new("", $stormtrackConnection).Password
Remove-Variable stormtrackConnection
```

`STORMTRACK_DATA_DIR` continua indicando onde encontrar a origem local.
`.env.example` documenta as variáveis; o backend não carrega arquivos .env
automaticamente. Em hospedagem, configure a variável no gerenciador de segredos.
Para verificar também a identidade TLS do servidor, use `sslmode=verify-full`
com o certificado raiz adequado; sem opção explícita, o driver usa `require`.

5. Rode a inspeção e, depois de conferir as contagens, aplique explicitamente:

```powershell
python -m backend.app.scripts.migrate_to_postgres --source ".\data\stormtrack.sqlite3"
python -m backend.app.scripts.migrate_to_postgres --source ".\data\stormtrack.sqlite3" --apply
```

O schema é criado antes da cópia. Todas as tabelas do StormTrack no destino
precisam estar vazias, inclusive sessões. Não inicie o backend no destino antes
da cópia: ele cadastra fontes candidatas na inicialização.
A ferramenta não sobrescreve nem apaga dados de um destino ocupado. Se a cópia
ou sua verificação falhar, a transação é desfeita; as tabelas vazias criadas
na etapa de inicialização podem permanecer. A origem continua preservada.

6. Inicie o backend no mesmo ambiente, com a variável ainda definida:

```powershell
uvicorn backend.app.api.main:app --reload
```

Confira `/api/health`: `database_backend` deve ser `postgresql` e `database`
deve ser `ok`. Entre com seu nome e senha habituais, e confira usuários,
fontes, observações e auditoria antes de liberar novas escritas.
Mover o banco não hospeda o frontend/backend: o aplicativo continua precisando
de um servidor que execute o FastAPI.

## Voltar ao SQLite antes de liberar o sistema

```powershell
Remove-Item Env:STORMTRACK_DATABASE_URL -ErrorAction SilentlyContinue
uvicorn backend.app.api.main:app --reload
```

O backend usa novamente o SQLite de `STORMTRACK_DATA_DIR`. A ferramenta realiza
uma cópia única, não replicação; dados escritos no PostgreSQL após a troca
não voltam automaticamente ao SQLite. Nesse caso, o retorno exige conciliação.

## Limites verificados

A compatibilidade é testada com PostgreSQL local isolado. A conexão real ao
Supabase depende de URL, permissões, certificado e rede do projeto escolhido.
O schema privado não deve ser adicionado aos schemas expostos na Data API.
Referência: https://supabase.com/docs/guides/api/securing-your-api
