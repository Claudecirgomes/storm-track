# Integração regional local — checkpoint e operação

Implementação em 04/11/2026 (America/Sao_Paulo). Sem alterações do banco operacional,
gates, alertas, autenticação, Vercel ou Supabase. Worker separado não depende do navegador.

## Executar (PowerShell, dentro de StormTrack)

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:STORMTRACK_DATA_DIR = '.\data'
.\.venv\Scripts\python.exe -m uvicorn backend.app.api.main:app --host 127.0.0.1 --port 8000
```

Em outro terminal, mesmo diretório e `STORMTRACK_DATA_DIR`:

```powershell
$env:STORMTRACK_DATA_DIR = '.\data'
.\.venv\Scripts\python.exe -m backend.app.adapters.regional_satellite
# Uma rodada para diagnóstico:
.\.venv\Scripts\python.exe -m backend.app.adapters.regional_satellite --once
```

Use as contas existentes. Não é necessário habilitar o agendador meteorológico anterior
nem mudar gates no banco. A autorização desta integração é separada: o worker é iniciado
explicitamente pelo comando acima. Não há início automático em workers ASGI ou reload.
Um lock exclusivo SQLite mantido pelo SO impede dois coletores no mesmo cache,
inclusive após crash/reinício. Cada execução sequencial usa uma conexão por arquivo NetCDF.

Para desativar somente esta integração, encerre o worker e configure
`$env:STORMTRACK_SATELLITE_ENABLED = 'false'` no servidor e no terminal do coletor.
O mapa base e as observações anteriores continuam acessíveis. Para reativar, use `true`.

## Fontes e processamento

- Bucket anônimo `https://noaa-goes19.s3.amazonaws.com/`, sem credenciais.
- [Catálogo oficial NOAA/AWS](https://registry.opendata.aws/noaa-goes/).
- [Convenções e produtos NOAA](https://github.com/NOAA-Big-Data-Program/nodd-data-docs/blob/main/GOES/README.md).
- `ABI-L2-CMIPF`: C13, C01, C02 e C03; listagem S3 paginada por hora UTC,
  filtrada por satélite/canal/horário. Sem nomes/datas fixos.
- CMI usa escala, offset e máscara do netCDF4; somente DQF=0. C13 Kelvin − 273,15.
- CRS geoestacionário é lido de `goes_imager_projection`. Centros de pixels de uma
  grade EPSG:3857 são transformados inversamente para amostragem vizinho mais próximo.
  Apenas a janela regional da matriz é lida; download ainda exige o arquivo de disco completo.
  Imagens com 900 pixels de largura são compatíveis com `L.imageOverlay` no Leaflet Mercator.
- Paleta linear definida em `STOPS/COLORS` no módulo; realce somente ≤ −30 °C,
  transparente nos demais pixels. C13 numérico em `.npz`, chave `c13_celsius`.
- RGB alternativo: C02 vermelho, C01 azul, verde sintético
  0,45 vermelho + 0,10 C03 + 0,45 azul; gama 2,2. Combinação com IR cinza
  noturno por cosseno do ângulo solar aproximado, faixa de transição 0–0,15.
  **Não é GeoColor CIRA**: não implementa correção Rayleigh, luzes noturnas,
  identificação de nuvens baixas nem todos os auxiliares do produto CIRA.
  A interface identifica a composição alternativa. O GeoColor completo continua pendente.
- Canais só são combinados quando os inícios das varreduras diferem em até um segundo.
  RGB indisponível não impede C13 nem GLM; detalhes do erro ficam nos metadados.
- GLM usa somente flashes, `flash_quality_flag=0`, posição e horário do primeiro evento
  de cada flash. Chave composta por objeto S3 + `flash_id`. Não significa impacto no solo.
  Replay consulta exclusivamente [fim da cena − 10 min, fim da cena].
  Completude resulta da união dos intervalos dos arquivos processados, sem dupla contagem;
  cobertura ≥98% recebe estado completo. Zero flashes difere de nenhum arquivo disponível.

## Recursos e configuração

- `STORMTRACK_SATELLITE_BOUNDS`: oeste,sul,leste,norte; padrão `-68,-39,-44,-18`.
  Coleta regional independe de zoom/enquadramento do usuário.
- `STORMTRACK_SATELLITE_STALE_SECONDS`: padrão 1800 para ABI. Consulta ABI a cada
  120 segundos e GLM a cada 60 segundos, depois de cada rodada terminar.
  Isso não muda a cadência observacional ABI de aproximadamente dez minutos.
- `STORMTRACK_GLM_STALE_SECONDS`: padrão 180. Idade e disponibilidade de cada produto
  são independentes no catálogo; a completude histórica GLM é calculada por janela.
- Intervalos ajustáveis: `STORMTRACK_SATELLITE_INTERVAL_SECONDS` (120) e
  `STORMTRACK_GLM_INTERVAL_SECONDS` (60), limitados a 30–3600 segundos.
  `STORMTRACK_SATELLITE_HISTORY_MINUTES` (120), limitado a 10–120 minutos;
  retenção inclui margem de dez minutos para as janelas GLM.
- Retenção de 2h10min; catálogo e identificação persistem em
  `data/regional-satellite/catalog.sqlite3`; imagens e numéricos no mesmo cache.
  A limpeza só toca arquivos referenciados por este catálogo e temporários próprios.
- Download máximo 180 MB/objeto, cache máximo 512 MiB, três tentativas, backoff 1s/2s,
  timeout de download 45s. Concorrência de download/processamento = 1.
  Catálogo limitado a 30 páginas por hora; exceder o limite produz erro explícito.
- Rodadas novas processam até dois ABI e 60 GLM ainda não vistos, mais recentes primeiro;
  histórico é preenchido gradualmente, com estado GLM parcial durante o preenchimento.
  A primeira coleta pode demorar vários minutos e transferir centenas de MB.
- Em falha preserva quadros válidos, com idade/estado no catálogo e erro por produto.
  Não há radar, risco, tracking, CELL-ID ou previsão derivados desses dados.

## Arquivos e API

`backend/app/adapters/regional_satellite.py`: coleta, cache, projeção, RGB, C13, GLM e CLI.
`backend/app/api/main.py`: três rotas autenticadas de leitura em `/api/satellite/regional/`:
`catalog`, `image/{filename}`, `flashes?end=<ISO UTC>`.
`frontend/regional-satellite.js` e `.css`: controles e camadas locais ao painel central.
`frontend/map.js`: pane de satélite, contornos acima das imagens e enquadramentos.
`frontend/app.js`, `index.html`: ciclo de sessão e carregamento dos novos arquivos.
`requirements.txt`: Pillow e pyproj; NumPy já integra a dependência netCDF4.
`tests/test_regional_satellite.py`: testes focados; suíte anterior preservada.

## Verificação e limites

Suíte anterior: 92 passaram, 7 ignorados (PostgreSQL sem DSN), 55 subtestes.
Cinco testes novos passaram: paleta/transparência, escala Kelvin e projeção,
paginação/virada de ano, deduplicação/janela sem futuro e quadro atrasado preservado.
Execução sandbox inicial falhou em diretórios temporários; repetição autorizada passou.

A verificação visual no navegador foi interrompida pelo mecanismo de automação:
ele não conseguiu determinar a URL atual com segurança. Desktop/mobile, console JS,
alinhamento visual de litoral e replay interativo ainda precisam de validação manual.
Não há imagem de referência anexada ao pedido. Parallax de nuvens altas não é corrigida.
Teste de projeção numérico não equivale a validação visual geográfica completa.

Pendências: GeoColor CIRA completo e validação visual; não declarar entrega integral.
Os resultados reais da coleta e os horários estão no catálogo local e no relatório final.

### Resultado real e verificação final

98 testes Python passaram, 7 ignorados, 55 subtestes. Sintaxe de `app.js`, `map.js`
e `regional-satellite.js` verificada no runtime Node. Teste isolado adicional em
`tests/regional_frontend_check.cjs` passou: atualização preserva replay pausado e
consulta GLM termina no horário escolhido. Execute com Node:
`node tests/regional_frontend_check.cjs`. Fixtures desse teste não entram na aplicação.

Leitura anônima real: mais de 350 objetos GLM persistidos na primeira rodada.
Cena C13 validada: 2026-11-05 02:20:21,2–02:29:53,2 UTC
(04/11/2026 23:20:21,2–23:29:53,2 em America/Sao_Paulo), DQF=0 em 100% da grade regional.
RGB alternativo disponível com C01/C02/C03 da mesma varredura. Foram gerados também
quadros de 02:00 e 02:10 UTC, e o worker segue preenchendo o histórico.
Na janela GLM 02:19:53,2–02:29:53,2 UTC foram lidos 9.675 flashes na região configurada,
com 87,8% de cobertura temporal declarada pelos arquivos, portanto **parcial**.
Esses números registram uma verificação, não constituem valores fixos da aplicação.
A imagem C13 processada foi inspecionada diretamente; isso não valida o layout do navegador.

Reinício preservou os quadros e identificadores já processados; tentativa de iniciar
segundo coletor foi recusada com `Satellite collector already running`.
`git diff --check` sem erros de whitespace. Sem commit, push ou publicação.
