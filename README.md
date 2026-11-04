# StormTrack — MVP local-first

## Estado atual

O repositório contém fundação local, catálogo de fontes, governança por gates, pipeline opt-in para NOAA GOES-19 GLM-L2-LCFA, persistência de observações, API autenticada de leitura, grade geográfica local e registros de execução/saúde.

A coleta meteorológica está desligada por padrão. Os gates NOAA GLM permanecem pendentes e nenhuma coleta real GLM foi validada neste ambiente. O painel passou a obter quadros JPEG públicos do GOES-19 ABI GeoColor pelo backend e exibi-los internamente, com atualização periódica e seleção dos quadros recentes. Isso é um proxy de imagem ao vivo, sem persistência, parser meteorológico ou ingestão ABI. A imagem NOAA é informativa e não deve ser usada para decisão operacional ou emergencial.

O ABI está ativo somente para exibição de imagem dentro do app; armazenamento, processamento e redistribuição local não estão habilitados. SIMEPAR, SMN/SINARAME, INUMET, Defesa Civil RS e CPTEC/INPE têm estruturas de conector isoladas que falham fechado enquanto seus perfis técnicos, amostras e condições de uso não forem definidos. Permanecem desabilitados.

Não existem métodos operacionais validados de detecção/tracking de células, cálculo de risco, nowcast ou alertas. A grade do mapa exibe somente observações persistidas retornadas pela API. Ausência de dados significa indisponibilidade, não ausência de risco.

## Estrutura

- backend/app/api: API FastAPI e autorização
- backend/app/accounts: contas e sessões
- backend/app/sources: catálogo, candidatos e gates
- backend/app/adapters: NOAA GLM; proxy NOAA ABI para imagem dentro do app; estruturas pendentes para provedores regionais
- backend/app/ingestion: ciclo e agendador opt-in
- backend/app/observations: persistência e leitura GeoJSON
- backend/app/analysis: estado pendente de métodos
- backend/app/core: configuração, segurança e SQLite
- frontend: interface local
- tests: regras, persistência, ingestão mockada e HTTP
- docs: auditoria, arquitetura, diagramas e consolidação

## Executar localmente

Requer Python 3.11 ou superior.

Windows PowerShell:

    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install -r requirements.txt
    $env:STORMTRACK_DATA_DIR = ".\data"
    python -m backend.app.scripts.provision_account --username admin --role ADMIN
    uvicorn backend.app.api.main:app --reload

Linux/macOS:

    python -m venv .venv
    source .venv/bin/activate
    python -m pip install -r requirements.txt
    export STORMTRACK_DATA_DIR="./data"
    python -m backend.app.scripts.provision_account --username admin --role ADMIN
    uvicorn backend.app.api.main:app --reload

Painel local: http://127.0.0.1:8000/  
Documentação da API: http://127.0.0.1:8000/docs

## Gerenciar usuários

Entre com a conta ADMIN e abra a aba **Usuários** para criar contas comuns,
alterar o nome de acesso, redefinir a senha, bloquear/reativar o acesso e excluir
usuários. O piloto permite um administrador e até quatro usuários; contas
bloqueadas continuam ocupando uma vaga. Alterar nome ou senha e bloquear uma conta
encerra suas sessões. Alterar os dados do próprio administrador exige novo login.
A conta ADMIN não pode ser bloqueada ou excluída. A exclusão de usuários remove
as credenciais e libera o nome/vaga, preservando os registros de auditoria.

A detecção automática de células permanece indisponível. O painel consulta
`/api/analysis/status` e informa a necessidade de fonte quantitativa de radar ou
infravermelho, método definido e validação histórica; não exibe zero como uma
detecção executada.

## PostgreSQL / Supabase opcional

Para hospedar o painel e a API com banco persistente, consulte
[Publicar na Vercel e no Supabase](docs/PUBLICAR_VERCEL_SUPABASE.md).
O deploy usa o frontend existente e exige a migração do banco antes da publicação.

O SQLite continua padrão. A preparação para PostgreSQL/Supabase inclui
configuração `STORMTRACK_DATABASE_URL`, schema privado, dependências opcionais
e ferramenta de transferência com inspeção padrão (sem cópia).
Consulte [o procedimento de migração](docs/MIGRACAO_SUPABASE.md) antes de configurar
a conexão ou aplicar a transferência.

## Coleta

A coleta externa fica inativa se a configuração não for explicitamente ligada. A variável global sozinha não autoriza coleta: produto, evidência e gates de acesso, coleta e armazenamento também precisam estar verificados no banco. Não habilite antes de revisar a fonte e testar o parser com amostra real.

Para um ensaio local futuro, depois dos gates documentais e técnicos:

Linux/macOS:

    export STORMTRACK_COLLECTION_ENABLED=true
    export STORMTRACK_COLLECTION_INTERVAL_SECONDS=60

PowerShell:

    $env:STORMTRACK_COLLECTION_ENABLED = "true"
    $env:STORMTRACK_COLLECTION_INTERVAL_SECONDS = "60"

Para desligar, use false ou encerre o processo. O gate de redistribuição é separado.

## API de observações

- GET /api/observations
- GET /api/observations/geojson
- GET /api/ingestion/runs
- GET /api/analysis/status
- GET /api/alerts
- GET /api/connectors
- GET /api/satellite/goes19/abi
- GET /api/satellite/goes19/abi/frames
- GET /api/satellite/goes19/abi/image/{filename}

As rotas de observações requerem autenticação. O endpoint de alertas informa que nenhum alerta foi emitido.

## Verificações

    python -m unittest discover -s tests -v
    python -m compileall -q backend tests
    node --check frontend/app.js

Os testes HTTP são ignorados se FastAPI/HTTPX não estiverem disponíveis. A suíte não prova operação ao vivo nem correção meteorológica.

## Documentação

- docs/CONSOLIDACAO_MVP_STORMTRACK_V1.md — parecer e estado real consolidado
- docs/INCREMENTO_5_CONECTORES_ABI.md — imagens ABI no app e inventário de outras fontes públicas
- docs/REVISAO_TECNICA_TOTAL_METODOS_SATELITE_2026-10-04.md — revisão total dos métodos e da conexão GOES-19
- docs/INCREMENTO_4_PIPELINE_GLM.md — desenho e limites do pipeline GLM
- docs/AUDITORIA_INTEGRAL_2026-10-04.md — auditoria da base anterior
- docs/StormTrack_Diagramas_Auditados_v1.3.md — diagramas arquiteturais em revisão

Consulte também o PDF consolidado e pacote ZIP mais recentes em output. Nenhum documento afirma garantia matemática de ausência de defeitos.
