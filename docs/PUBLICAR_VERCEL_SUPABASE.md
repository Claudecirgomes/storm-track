# StormTrack na Vercel e no Supabase

Preparação local concluída; não significa que o sistema já está publicado.
Os arquivos de `frontend/` são os mesmos do sistema local. O FastAPI serve
o painel e a API na mesma origem, preservando login e permissões existentes.

## 1. Criar as contas gratuitas

- Vercel: https://vercel.com/signup — selecionar Hobby (uso pessoal e não comercial).
- Supabase: https://supabase.com/dashboard — criar uma organização no plano Free.
- No Supabase, criar um projeto `stormtrack`, preferencialmente em São Paulo.
  Guardar a senha do banco em um gerenciador de senhas.

O plano gratuito tem cotas; o Supabase pode pausar projetos com pouca atividade
por sete dias. Não há coleta contínua neste deploy da Vercel.

## 2. Preparar o banco antes do primeiro deploy

A aplicação usa PostgreSQL por conexão privada do backend; não usa Supabase Auth.
Não são necessárias chaves `anon` ou `service_role` no frontend.

No botão **Connect** do projeto Supabase, selecionar **Session pooler**, porta
**5432**. Não usar o Transaction pooler (6543): o adaptador depende do schema
da sessão. A senha deve estar codificada para URL. Manter `sslmode=require`.

Na pasta `StormTrack`, executar no PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-postgres.txt
$stormtrackConnection = Read-Host "URL do Session pooler Supabase" -AsSecureString
$env:STORMTRACK_DATABASE_URL = [System.Net.NetworkCredential]::new("", $stormtrackConnection).Password
Remove-Variable stormtrackConnection
.\.venv\Scripts\python.exe -m backend.app.scripts.migrate_to_postgres --source .\data\stormtrack.sqlite3
```

Esse comando apenas inspeciona, sem conectar ou escrever no destino.
Parar a API/coleta local e fazer uma cópia de segurança do SQLite antes da cópia.
Depois de conferir as contagens, executar:

```powershell
.\.venv\Scripts\python.exe -m backend.app.scripts.migrate_to_postgres --source .\data\stormtrack.sqlite3 --apply
```

A ferramenta verifica o conteúdo e recusa destino ocupado. Não iniciar o
backend no Supabase antes da migração. Contas, hashes de senhas, catálogo e
auditoria são preservados. Sessões não são copiadas: fazer login novamente.
Consultar também [o procedimento completo](MIGRACAO_SUPABASE.md).

## 3. Publicar a pasta certa na Vercel

Usar **a pasta `StormTrack`**, onde estão `app.py`, `vercel.json` e
`requirements.txt`. Não usar somente `frontend/` nem a pasta acima de StormTrack.

Pode-se importar um repositório privado pelo painel da Vercel ou publicar pela
CLI sem GitHub, depois de instalar Node.js LTS e entrar na conta:

```powershell
npx vercel login
npx vercel link
npx vercel env add STORMTRACK_DATABASE_URL production
npx vercel env add STORMTRACK_COLLECTION_ENABLED production
```

No primeiro prompt de variável, informar a URL privada do Session pooler; no
segundo, informar `false`. A URL do banco deve ser marcada como sensível nas
configurações da Vercel. Não incluir senhas em arquivos do repositório ou no chat.

Para uma implantação Preview funcional, configurar as mesmas variáveis no
ambiente Preview (de preferência com outro banco, pois escritas no mesmo banco
também afetariam produção). Não conectar previews públicos a dados reais.

Selecionar o preset **FastAPI**; sem comando npm de build e sem Output Directory.
A versão Python está definida em `.python-version`. O frontend já está pronto,
sem compilação. O projeto está configurado para região `gru1` (São Paulo).

Quando as variáveis e o banco estiverem preparados:

```powershell
npx vercel --prod
```

O comando cria a publicação de produção e devolve o endereço HTTPS `*.vercel.app`.
As regras de exclusão impedem o upload da pasta de dados, screenshots, ambientes
virtuais e arquivos `.env`. Não publicar a pasta local manualmente por ZIP.

## 4. Verificar depois da publicação

1. Abrir `/api/health`: `database_backend` deve ser `postgresql`, `database` deve
   ser `ok`, e `collection` deve ser `disabled_by_default`.
2. Abrir `/`, entrar com a conta existente e conferir fontes e usuários.
3. Conferir que as rotas de leitura exigem login e as administrativas exigem ADMIN.
4. Conferir imagens NOAA e mapa; esses serviços externos podem estar indisponíveis
   independentemente da hospedagem do painel.

Na Vercel (`VERCEL=1`), a aplicação recusa iniciar sem PostgreSQL ou com coleta
contínua ligada. As instâncias não criam schema e não semeiam dados durante o
startup: esse preparo acontece na migração, antes do deploy. O SQLite local
continua independente; não há sincronização automática com a cópia online.

Para voltar ao banco local neste terminal:

```powershell
Remove-Item Env:STORMTRACK_DATABASE_URL -ErrorAction SilentlyContinue
```

## Referências oficiais

- https://vercel.com/docs/frameworks/backend/fastapi
- https://vercel.com/docs/functions/runtimes/python/python-version
- https://vercel.com/docs/plans/hobby
- https://supabase.com/docs/guides/database/connecting-to-postgres
- https://supabase.com/docs/guides/platform/free-project-pausing
