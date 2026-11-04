# Revisão técnica total — satélite, métodos e estado do MVP StormTrack

**Revisão:** 04/10/2026 (fuso de São Paulo)  
**Escopo:** código atual, catálogo de fontes, adaptador, agendador, API, métodos meteorológicos, testes e estado público NOAA consultado.  
**Parecer:** protótipo de ingestão observacional; nenhum satélite está conectado ao processo local nesta versão.

## 1. Resposta direta: qual satélite está conectado?

**Nenhum está efetivamente conectado ao StormTrack no estado verificado.** O código está preparado para ler arquivos do produto **GLM-L2-LCFA do NOAA GOES-19** pelo bucket público NOAA em AWS S3. Isso é um adaptador para arquivos disponibilizados pelo provedor, não uma conexão de telemetria/controle com o satélite.

A coleta está desligada por padrão, o produto GLM inicializa desabilitado e com os gates PENDING, e os testes de ingestão simulam as respostas. Não houve execução de uma coleta de rede validada nem leitura de arquivo NetCDF NOAA real. Portanto, não há observação atual chegando ao mapa.

O produto **ABI-L2-MCMIPF do GOES-19** está apenas catalogado, sem adaptador. SIMEPAR, SMN/SINARAME, INUMET, Defesa Civil RS e CPTEC/INPE também são candidatos no catálogo, sem conectores.

| Item | Estado constatado |
|---|---|
| GOES-19, instrumento GLM, produto GLM-L2-LCFA | Adaptador de leitura no código; coleta local não conectada/validada; gates PENDING e disabled |
| GOES-19, instrumento ABI, produto ABI-L2-MCMIPF | Candidato no catálogo; sem adaptador |
| Fontes regionais | Candidatas no catálogo; sem endpoints ou conectores |
| Satélite em operação no país | GOES-19 é o GOES-East operacional NOAA; isso não significa que o aplicativo StormTrack esteja conectado |

A documentação pública NOAA identifica o GOES-19 como GOES-East em 75,2°W. O registry NOAA descreve os dados NODD como públicos e pede atribuição para dados NOAA inalterados; isso não demonstra conexão do aplicativo, qualidade do nosso parser ou autorização para redistribuir qualquer produto alterado. O GLM-L2-LCFA contém flashes, grupos e eventos em arquivos de 20 segundos. Esses dados são observações de raios, não objetos de tempestade ou um alerta por si sós.

### Situação externa que precisa ser checada no ensaio

Na consulta oficial feita para esta revisão, o painel OSPO lista GOES-19 como operacional e GLM como verde, com status geral atualizado em 03/09/2026. A página NOAA STAR de visualização de GLM ainda exibe um aviso de restauração pendente após o evento de julho, enquanto a própria página mostra quadros com timestamp de setembro. Essas páginas não são evidência suficiente de disponibilidade ponta a ponta atual do arquivo no bucket. Tratar a saúde do produto como **não verificada até uma sondagem controlada**.

## 2. Métodos pendentes: o que dá para resolver agora

| Método/entrega | Decisão desta revisão | O que podemos fazer agora | O que impede uso operacional |
|---|---|---|---|
| Proveniência, validação de payload, deduplicação e estado de coleta | Resolver como engenharia de software | Corrigir filtros de cursor, truncamento, limites, erros e testes de regressão; parte foi corrigida nesta revisão | Falta execução com arquivo NetCDF real e ensaio de disponibilidade/recuperação |
| Resumo descritivo de raios | Pode ser um próximo recurso observacional, sem chamar de risco | Exibir total de flashes por arquivo/janela e, se aprovado o contrato, contagem por grade e intervalo com carimbo de tempo, fonte e qualidade | Primeiro validar variáveis, flags de qualidade, projeção, borda da cobertura e atraso com produto real |
| Detecção de células | Não resolver como método operacional agora | Especificar alternativas e preparar interfaces; ensaio offline somente com amostras identificadas como simulação | O GLM fornece pontos de raios, não contornos de células. Faltam radar/ABI conectado, definição de célula, casos de referência e métricas |
| Tracking/linhagem | Não resolver agora | Desenhar contrato de identidade, associação, divisão/fusão e histórico | Requer objetos detectados em sequência e validação independente; não há detector aprovado ou dados conectados |
| Risco de vento | Não resolver agora | Definir requisitos e proveniência do perigo | GLM não mede vento. Requer observações apropriadas, modelo/medição e calibração validada |
| Risco de granizo | Não resolver agora | Preparar ficha de método e critérios de validação | GLM não confirma granizo. Exige fontes adequadas, medidas de referência e validação de falsos positivos/negativos |
| Rotação/supercélula/tornado | Não resolver agora | Preparar método/saída como UNKNOWN até haver evidência suficiente | Pontos GLM não medem velocidade radial. Requer radar Doppler apropriado e revisão meteorológica especializada; satélite sozinho não confirma tornado |
| Nowcast A30/A60/A90 | Não resolver como previsão operacional | Criar comparação experimental/replay só depois de armazenar sequências observadas com proveniência | Sem fonte validada, célula rastreada, alvos históricos independentes, baseline, horizonte e métricas; persistência ingênua não é previsão validada |
| Alertas StormTrack | Resolver apenas o estado seguro de não emissão | Manter API em NOT_ISSUED, separar alerta oficial de experimental e criar esquema/auditoria quando requisitos forem aprovados | Sem método aprovado não se deve emitir alertas de risco. O endpoint atual corretamente retorna vazio |
| Saúde/recuperação | Resolver mais da estrutura; manter limites claros | Registrar ciclos, falhas e atraso/idade quando medível; testar retomada, backoff, paginação e perda de janelas | Não há backfill, replay, operação contínua ou validação com indisponibilidade real |

**Fechamento científico:** nenhum método de detecção, perigo, nowcast ou alerta pode ser marcado como validado apenas por revisão de código. A entrega segura agora é aprimorar qualidade de ingestão e observações descritivas; o produto deve indicar claramente que não representa risco.

## 3. Achados de auditoria

### Corrigidos nesta revisão

1. **Cursor podia perder arquivos atrasados.** O código usava a última chave como filtro; um objeto entregue fora de ordem e com chave menor podia ficar invisível dentro da janela recente. O coletor agora reconsulta a janela delimitada e depende da deduplicação por chave para não duplicar observações.
2. **Limite podia descartar dados em silêncio.** A listagem retornava somente os objetos mais recentes quando excedia o limite. Agora a janela tem cap de 30 objetos e excedente/listagem S3 truncada gera erro explícito de ciclo, em vez de falso sucesso.
3. **Intervalo e janela eram incompatíveis.** Configuração aceitava intervalo de até uma hora, mas a busca olhava só cinco minutos. O intervalo foi limitado a 20–300 segundos; a janela de busca recebe margem sobre o intervalo; as horas S3 necessárias são consultadas. Ainda não há replay se o processo ficar parado além da janela.
4. **Rótulo de integração era ambíguo.** O estado GLM no catálogo agora diz adaptador implementado, sem conexão confirmada. Isso descreve a implementação e não o estado do satélite nem a saúde do bucket.
5. **Estado analítico expunha objeto mutável compartilhado.** A resposta agora copia o catálogo de métodos pendentes.

### Limitações ainda abertas

- Parser não foi comparado com NetCDF real. A existência de variáveis com nomes esperados não basta: é preciso checar dimensões, máscaras, unidades, flags de qualidade e timestamps internos do arquivo.
- A geometria atualmente exporta coordenadas globais. O mapa recorta visualmente por seus limites; ainda falta aplicar domínio espacial no backend e estimar volume de armazenamento.
- A janela recente evita perdas por entrega fora de ordem dentro dela, mas não recupera intervalos após parada longa. Não há backfill.
- “AVAILABLE” indica que a chamada listagem/download processada respondeu; não comprova frescor, completude, precisão científica ou cobertura do corredor.
- Produto novo pode receber estado VERIFIED por decisão administrativa com texto de evidência não vazio. O sistema registra a decisão, mas não verifica juridicamente a referência nem a qualidade da fonte.
- Endpoint de alertas está deliberadamente sem emissão; os métodos retornam NOT_OPERATIONAL/PENDING_METHOD_AND_VALIDATION.
- Banco SQLite local, sem plano automatizado de retenção, backup/restore verificado, alta disponibilidade ou segurança para exposição em rede.

## 4. Evidência de teste

Depois das correções, a suíte executou **37 testes: 32 passaram e 5 testes HTTP foram ignorados** pela falta de FastAPI/HTTPX no ambiente. A tentativa anterior de instalar dependências foi barrada pela restrição de rede. compileall do Python e node --check do frontend passaram.

Os testes novos exercitam a retomada com arquivo tardio atrás do cursor. Eles usam rede simulada. Não testam conexão real, parser NetCDF com arquivo NOAA, operação meteorológica, carga, recuperação de processo ou qualidade das observações. Não foi executada prova formal/model checking; não se afirma ausência de defeitos.

## 5. Gates recomendados

### Gate 1 — confirmar a fonte alvo
- Manter GOES-19 GLM como candidato para observação de raios, sem chamar o satélite de conectado.
- Fazer uma única sondagem do catálogo S3 e obter um objeto recente, registrando horário da consulta, chave, tamanho e código de resposta.
- Ler um arquivo NetCDF real permitido e comparar esquema, timestamps, máscaras, contagens e coordenadas com o guia/produto NOAA.
- Só então registrar resultado de acesso técnico; revisão de termos, retenção e redistribuição é decisão separada.

### Gate 2 — piloto observacional
- Implementar e validar um resumo de raios (contagens e idade do dado) sem limiar de risco.
- Checar cobertura brasileira, limite do disco visível, qualidade e atraso; preservar desconhecidos como desconhecidos.
- Testar atraso, duplicação, interrupção menor/maior que a janela e recuperação. Antes do uso contínuo, implementar retenção/backfill ou declarar a perda de janelas na interface.

### Gate 3 — métodos meteorológicos
- Escolher um método por fenômeno com especificação versionada: entradas, escopo, unidades, janela, threshold, saída, incerteza e motivo de não emissão.
- Reservar conjunto histórico independente; definir métricas e critérios de aceite antes de treinar/ajustar.
- Fazer validação com especialista meteorológico; manter simulação separada de LIVE.
- Liberar alertas apenas após validação de método, fonte, taxa de falsos alarmes e fluxo de revisão.

## 6. Referências oficiais consultadas

- NOAA — GOES-19 entrou em serviço como GOES-East em 07/04/2025: https://www.noaa.gov/news-release/noaas-goes-19-satellite-now-operational-providing-critical-new-data-to-forecasters
- NOAA OSPO — estado de instrumentos e anomalias GOES: https://www.ospo.noaa.gov/operations/goes/status.html
- NOAA STAR — visualização GLM GOES-19 e aviso de restauração: https://goes.noaa.gov/sector_band.php?band=EXTENT3&length=12&sat=G19&sector=ga&src=nav
- NOAA Open Data on AWS — dados GOES e termos de atribuição: https://registry.opendata.aws/noaa-goes/
- NOAA NCEI — GLM-L2-LCFA, flashes/grupos/eventos e arquivos de 20 s: https://www.ncei.noaa.gov/access/metadata/landing-page/bin/iso?id=gov.noaa.ncdc%3AC01527
