# Monitor de tempestades — atualização e referência visual

Alteração de 05/11/2026, conforme referência fotográfica enviada pelo usuário.

**Operação atual:** consulte [coleta de todas as atualizações](COLETA_TODAS_ATUALIZACOES.md),
que substitui a seleção apenas do último C13, os intervalos e o backfill descritos
abaixo por fila persistente e processos independentes.

## Uso diário

```powershell
.venv\Scripts\python.exe -m backend.app.scripts.start_local
```

Esse comando inicia servidor e coletor NOAA ocultos, sem mudar a política de
scripts do Windows. O coletor possui lease único; uma chamada posterior não
inicia outra coleta quando o lease já está ocupado. Os logs estão em
`output/stormtrack-server-error.log` e `output/stormtrack-collector-error.log`.
Endereço: http://127.0.0.1:8000. Atualize o navegador com Ctrl+F5.

## Causa e correções da defasagem

O servidor estava aberto, mas o coletor estava parado desde 03:41 UTC. Na inspeção
das 20:24 UTC, o catálogo regional ainda terminava em 03:29 UTC para ABI e 03:40
UTC para GLM. Portanto, atualizar a página não conseguiria produzir quadros novos.

- Servidor e coletor foram reiniciados/iniciados e a publicação real confirmada.
- Descoberta ABI padrão: 30 s; GLM: 20 s; consulta do catálogo no navegador: 15 s.
- A imagem GeoColor do painel separado passa a consultar a cada 30 s, com cache
  do índice de 20 s, em vez de esperar 5 minutos no navegador.
- C13 é persistido e anunciado antes do RGB opcional. Falha ou demora do visível
  não prende a chegada da imagem infravermelha.
- O modo normal busca a cena ABI mais recente; não baixa automaticamente a fila
  histórica antes de atualizar o quadro atual. Backfill é opt-in por
  `STORMTRACK_SATELLITE_BACKFILL=true`.
- GLM recupera uma janela limitada de 15 minutos, em lotes de até 12 arquivos,
  mais recentes primeiro. A cobertura parcial continua indicada enquanto completa.
- Ao vivo, GLM usa o último horário efetivo do próprio GLM, independentemente do
  horário do ABI. Em replay, a janela termina no quadro escolhido, sem futuro.
- O cache dos vetores também recusa um resultado posterior à referência de replay,
  mesmo se dois pedidos pertencem ao mesmo minuto.

Não há promessa de latência zero: o produtor precisa publicar o arquivo, o download
e o processamento precisam terminar. Full Disk ABI normalmente observa a cada
10 minutos; consultar a cada 30 s não cria observações intermediárias.
[Agenda oficial NOAA](https://www.nesdis.noaa.gov/our-satellites/currently-flying/goes-east-west/goes-schedules-and-scan-sectors).

Verificação real após reinício: ABI até 20:29:53,3 UTC, idade ~99 s; GLM até
20:31:00 UTC, idade ~33 s na amostragem. A coleta permaneceu em execução.

## Seleção de camadas

O seletor principal agora contém apenas contexto de acompanhamento de tempestades:

- Referência: terreno + nuvens realçadas; C13, cinza e estilo combinado anterior.
- Altura e fase de topos, textura True Color, fase/convecção diurna e microfísica noturna.
- Massas de ar e vapor de água alto/médio/baixo.
- Taxa de chuva estimada por satélite, com indisponibilidade explícita quando a
  fonte não tiver produto. Radar e estações continuam dependendo de conexão real.
- Descargas GLM com janelas de 1/5/10/15 minutos.
- Ventos em altitude DMW, por checkbox, com velocidade, pressão, horário e DQF no
  tooltip. Até 400 setas são desenhadas por amostragem visual; o endpoint conserva
  todos os vetores válidos do arquivo selecionado. O teste real retornou 1.869
  vetores para o recorte ampliado, observados entre 20:00 e 20:09 UTC.

Foram retirados do seletor fogo, fumaça, poeira, cinzas, radiação, temperatura da
superfície e o catálogo amplo de canais/diagnósticos de pesquisa. Os leitores e
arquivos científicos anteriores foram preservados fora do seletor operacional.
Preferências de produtos removidos deixam de ser restauradas; opções mantidas
continuam preservando preferência, zoom e replay.

Satélite sozinho não confirma rotação ou supercélula. DMW estima movimento
atmosférico em níveis de pressão, não vento observado em superfície nem rota
de célula. Chuva estimada não é refletividade Doppler. Não foram criados dados
substitutos para fontes desconectadas.

## Aparência e enquadramento da foto

A nova opção padrão, **Referência — terreno + nuvens realçadas**, usa:

- Enquadramento inicial aproximado: 73°W–42°W, 36°S–18°S, incluindo Sul do Brasil,
  Paraguai, Uruguai, norte da Argentina e os Andes no lado oeste.
- Área de coleta mais ampla: 73°W–42°W, 40°S–14°S. Zoom não redefine a coleta.
- Contornos claros existentes, mapa com proporção aproximada de 1,56 e terreno
  NASA Blue Marble com relevo e batimetria.
- A mesma paleta térmica anterior (com extremos frios magenta/escuros), usando C13
  real NOAA, sobre o terreno. A foto foi referência visual, não fonte de valores.
- Transparência térmica de exibição: zero a +15°C, opaca a −15°C e abaixo; valores
  intermediários interpolados. Isso não é uma máscara física de nuvens: superfícies
  frias podem aparecer, e nuvens quentes podem ficar transparentes. Valores
  científicos e DQF não mudam.

A base NASA é **estática, agosto de 2004**, não imagem atual do solo, e tem
atribuição visível. Nuvens vêm do horário NOAA informado separadamente. Se os tiles
falham, a base local continua disponível. Os estilos anteriores permanecem no
seletor; uma preferência já salva pode exigir selecionar Referência manualmente.
[Metadados NASA](https://gibs.earthdata.nasa.gov/layer-metadata/v1.0/BlueMarble_ShadedRelief_Bathymetry.json).

A foto enviada representa outro horário. A posição das tempestades na prévia
atual não foi modificada para coincidir com aquela imagem histórica.

## Evidências e limites

`output/monitor-reference-real.png` é uma prévia renderizada com os mesmos dados
C13, tiles NASA, contornos e enquadramento do mapa. Não é screenshot do navegador.
O script `python -m backend.app.scripts.preview_monitor` permite regenerá-la.
O teste JavaScript verifica GLM ao vivo independente e replay limitado ao ABI,
além de legenda, expansão e preferência. Há teste de publicação do C13 antes da
falha RGB e da recusa de cache de vento futuro.

Não houve deploy. Alterações são locais. O aplicativo completo em navegador não
foi inspecionado nesta alteração; a prévia raster e os testes de comportamento
não substituem a validação visual desktop/celular.
