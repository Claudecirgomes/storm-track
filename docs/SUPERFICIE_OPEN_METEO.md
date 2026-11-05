# Cartão Temperatura / Vento — Open-Meteo

Implementado no cartão anteriormente chamado Estações. São **saídas de modelos
meteorológicos**, não medições de estações nem estimativas de vento GLM/DMW.

## Interface

- Minimapa do Sul, Paraguai, Uruguai e norte/nordeste da Argentina, com Maringá.
- Modos Temperatura, Vento e Combinado.
- Círculos coloridos para temperatura a 2 m; setas para o vento a 10 m, com tamanho
  variando com a velocidade e limitado para legibilidade. Direção da seta indica
  para onde sopra; o popup informa a direção meteorológica de origem.
- Consulta de marcador usa a amostra exibida. Toque em outro ponto consulta aquela
  localização no backend, dentro do recorte, sem interpolar valores dos 43 pontos.
- Popup informa temperatura (°C), vento (km/h), direção, fonte e horário de validade
  em America/Sao_Paulo. Coordenadas retornadas da célula do modelo ficam no JSON.
- Ampliar no mapa principal adiciona a camada somente mediante clique, com legenda
  explícita MODELO e botão para retirar. O satélite continua como base.
- Durante replay, a camada atual é retirada do mapa principal e sua ampliação é
  desabilitada. O cartão permanece atual, com aviso próprio. Não se apresenta uma
  consulta feita agora como rodada histórica conhecida naquela data.

O mapa central não recebe nenhuma camada automaticamente ao abrir o cartão.

## Fonte e tempo

Fonte: [Open-Meteo Forecast API](https://open-meteo.com/en/docs), com `models=best_match`,
`current=temperature_2m,wind_speed_10m,wind_direction_10m`, unidades explícitas,
UTC/Unix e seleção da célula mais próxima. A seleção de modelo é automática do
provedor; não se inventa identidade ou horário de inicialização da rodada.
Horário de validade e horário de consulta são campos separados.

A grade regional tem 42 locais regulares mais Maringá: 43 solicitações de ponto.
É uma amostragem ampla para contexto, não a resolução nativa do modelo nem um
campo contínuo interpolado. O recorte é 68°W–44°W, 39°S–18°S. A consulta ao toque
tem cache de coordenadas arredondadas a 0,01°, antes de selecionar a célula do
modelo. Não há geolocalização do usuário.

Valores ausentes não viram zero. Vento calmo zero tem símbolo próprio; direção
ausente com vento não nulo não gera seta. Dados futuros não são aceitos como
condição atual. Paleta térmica: −5,5,15,25,35,45°C, com saturação nos extremos;
valores numéricos não são alterados pela paleta.

## Uso gratuito e orçamento

O usuário escolheu uso acadêmico não comercial. O acesso gratuito é condicionado
aos [termos Open-Meteo](https://open-meteo.com/en/terms), com atribuição e limites.
Não há chave, contratação ou conta nova. Atribuição Open-Meteo/CC BY 4.0 aparece
no minimapa e quando a camada é ampliada.

- Cache compartilhado persistente: 15 minutos por grade/ponto.
- Navegador consulta o backend a cada 5 minutos; Atualizar respeita o cache.
- Lease SQLite impede chamadas duplicadas entre abas/threads/processos locais.
- Cada coordenada é contabilizada conservadoramente como uma unidade: a grade
  soma 43 por atualização, mesmo enviada em uma requisição multi-localização.
- Limites locais: 300/minuto, 2.000/hora, 8.000/dia e 240.000/mês (UTC).
- A grade a cada 15 min corresponde a aproximadamente 4.128 unidades/dia, antes
  dos cliques. Cotas de todos os pontos e da grade compartilham o mesmo contador.
- Falha de rede preserva o último conjunto com estado atrasado e backoff de
  cinco minutos; nenhuma falha é apresentada como dado válido zero.

Cache e contadores ficam em `data/surface-model/`, separados do banco operacional
e do arquivo GOES. Não há dependências novas. Um deploy com múltiplas instâncias
exige cache/cotas duráveis compartilhados; a presente validação é local.

## Operação e verificação

Iniciar como antes:

```powershell
.venv\Scripts\python.exe -m backend.app.scripts.start_local
```

Rotas autenticadas: `/api/weather/surface` e
`/api/weather/surface/point?lat=-23.42&lon=-51.94`.
Não são proxies para URLs arbitrárias; a região e a fonte são fixas.

Amostra real recebida em 05/11/2026 às 21:35 UTC: 43/43 pontos completos.
Maringá: validade 21:30 UTC (18:30 de Brasília), 24,6°C e 9,7 km/h de 282°.
São dados de modelo do horário indicado, não observações de estação.

Testes verificam unidades, nulls, vento zero, cache entre chamadas, backoff,
orçamento e limite regional. O teste JavaScript verifica modos, direção de fluxo,
ampliação apenas por ação do usuário e retirada no replay. A API exige sessão.
Não houve inspeção visual completa do navegador nesta implementação.
