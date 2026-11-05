# Ajuste visual local — 05/11/2026

Escopo: aparência meteorológica do painel central existente. Sem mudança de
enquadramento, seleção de produto, layout, alertas, APIs, dados físicos, coleta,
retenção, autenticação, infraestrutura ou serviços externos.

## Alterações

- `backend/app/adapters/regional_satellite.py`: apenas paleta e transparência do
  renderizador `thermal`. Mantidos os mesmos nós físicos em °C:
  −90, −80, −70, −60, −50, −40, −30, 0, 40.
  Extremos frios escuros, passando por magenta, vermelho, laranja (interpolação),
  amarelo, verde e ciano. Aproximação visual da referência SIMEPAR, não sua paleta oficial.
  No modo combinado, opacidade cresce linearmente de zero em −30 °C até 100%
  em −38 °C, preservando o RGB/IR existente nas bordas. C13 isolado mantém
  opacidade integral em todos os pixels válidos. Máscaras DQF, reprojeção e
  temperaturas não mudaram; esta transparência não é uma máscara de nuvens.
- `frontend/regional-satellite.js`: legenda recebe a tabela do catálogo usada pelo
  renderizador, evitando divergência entre imagem e escala. Não troca produto,
  horário selecionado, opacidade, zoom nem reprodução.
- `frontend/regional-satellite.css`: removido o gradiente duplicado fixo;
  tamanho e posição dos controles preservados.
- `frontend/map.js`: contornos claros com espessura 0,8 px e opacidade 0,85.
  Prefixo do crédito Leaflet substituído por seu nome/link sem o SVG da bandeira.
  Créditos Natural Earth e OpenStreetMap mantidos. Biblioteca vendorizada intacta.
- `tests/test_regional_satellite.py`, `tests/regional_frontend_check.cjs`:
  ajustadas verificações da transparência e da legenda compartilhada.

Os PNGs C13 e realce dos 13 quadros em cache foram regenerados dos `.npz`
numéricos existentes. Nenhum arquivo-fonte foi baixado para essa regeneração,
e RGB/IR, máscaras, coordenadas e horários permanecem intactos.
Servidor e coletor locais foram reiniciados para aplicar a paleta também aos
quadros futuros. Não houve commit, push ou publicação.

## Comparação e testes

Comparação no mesmo quadro e recorte regional EPSG:3857:
05/11/2026 03:00:21,2–03:09:53,1 UTC, isto é,
05/11/2026 00:00:21,2–00:09:53,1 America/Sao_Paulo.
Artefatos locais em `output/satellite-visual/`: `before-combined.png`,
`after-combined.png`, versões C13/realce e `frame.json` com os metadados.
A imagem de comparação não é apresentada como observação atual no aplicativo.

- 11 testes Python de satélite/API passaram.
- Teste isolado Node: preservação de replay pausado, consulta GLM relativa ao
  quadro e legenda proveniente da API. Sintaxe JavaScript verificada.
- Antes/depois das imagens processadas inspecionados diretamente.
- Revisão do diff e `git diff --check`.

## Limitações verificadas

A base existente tem polígonos locais e mapa de ruas OpenStreetMap, sem uma
textura estática de relevo/vegetação/oceano. Por isso, a textura e as cores de
terreno da referência não podem ser reproduzidas com as camadas atuais à noite.
Não foram adicionadas fontes nem simulada observação visível diurna noturna.
O RGB diurno / IR noturno existente foi preservado e não é GeoColor CIRA completo.

O provedor de navegador estava indisponível; a alternativa Windows foi encerrada
pelo mecanismo de automação por não conseguir determinar a URL com segurança.
Logo, não foram validados visualmente o painel em desktop/celular, console JS,
nem a remoção da bandeira em uma captura do navegador. O ajuste usa a API pública
`attributionControl.setPrefix` do Leaflet e foi revisado no código local.

## Revisão após solicitação de visão maior e nova correção das cores

O pedido posterior do usuário autoriza ampliar a visão inicial: o mapa agora
enquadra a região já coletada (−68/−39 a −44/−18), mantendo os atalhos existentes.
O novo botão “Ampliar mapa” ocupa a janela com o painel e seus controles;
“Restaurar mapa” ou Escape retorna ao layout anterior, preservando quadro e zoom.
Não foram ampliadas artificialmente as imagens para fora da cobertura coletada.

Produto inicial passa a “RGB + topos frios”; mudanças de produto são salvas
localmente e respeitadas nas próximas aberturas. As URLs dos três arquivos visuais
em `index.html` receberam versão para evitar cache de código anterior.

A paleta foi revista para concentrar as faixas nos topos frios, mantendo
as temperaturas e o intervalo total −90 a 40 °C. Nós intermediários atuais:
−90, −80, −75, −70, −65, −60, −55, −50, −40, −30, 0 e 40 °C.
A legenda usa a mesma tabela. Os pixels menos frios passam a tons cinza claros
na transição do realce; não há filtro global sobre o RGB e o tratamento noturno
continua intacto. A tabela continua sendo aproximação, não paleta oficial SIMEPAR.

13 quadros disponíveis foram renderizados novamente a partir de seus numéricos
em cache. Comparação do mesmo quadro registrada em
`output/satellite-visual/revised-combined.png`, sem mudar fonte, horário ou recorte.
11 testes Python passaram; teste Node passou para replay, GLM, legenda,
ampliar/restaurar preservando seleção e persistência da preferência de produto.
Sintaxe JS e diff verificados. A tela final em navegador/mobile segue sem validação
visual por causa do bloqueio de automação registrado acima.
