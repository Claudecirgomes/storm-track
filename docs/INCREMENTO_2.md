# StormTrack — Incremento 2: persistência meteorológica segura

## Decisão

Antes de integrar uma fonte real, a base precisa de um caminho persistente que preserve a proveniência e recuse dados de produtos ainda não aprovados. Este incremento cria esse caminho como serviço interno, sem API de ingestão, scheduler ou conector ativo.

## Incluído

- Tabelas SQLite para `DATA_ARTIFACT`, `OBSERVATION`, `OBSERVATION_REVISION`, `DATA_QUALITY_ASSESSMENT` e `SOURCE_HEALTH`.
- Observações mantêm `observed_at_utc`, `received_at_utc`, timestamp original e offset original.
- A chave de deduplicação é única no escopo de um produto, não global.
- Payload e geometria são serializados canonicamente para hash SHA-256 e mantidos em snapshots de revisão.
- Reentrega com mesma chave e mesmo conteúdo é ignorada; conteúdo diferente para a mesma chave cria revisão append-only, sem substituir a anterior.
- O serviço bloqueia produto ausente, desabilitado ou sem evidência e gates verificados para acesso, coleta e armazenamento.
- Qualidade desconhecida permanece `NULL` e disponibilidade desconhecida permanece `UNKNOWN`; limites de integridade rejeitam métricas fora do intervalo.

## Alinhamento dos diagramas

O DER v1.3 aloca conteúdo e geometria em `ObservationRevision`, o que preserva cada snapshot recebido. O horário e o identificador estável ficam em `Observation`; cada revisão também preserva seu próprio timestamp e offset original. A saúde da fonte e a qualidade da observação são registros próprios. A mudança é de implementação das entidades já previstas e não cria um caso de uso novo.

## Não incluído

Nenhum endpoint aceita ingestão meteorológica; nenhum arquivo é baixado. Não há polling, retries, circuit breaker, conversor de produto, detecção, tracking ou previsão. Aprovar os gates de um produto também não liga um coletor.

## Verificação

- 16 testes da fundação e persistência passaram com `unittest` (19 encontrados no total).
- 3 testes HTTP seguem no pacote, mas estão ignorados porque a rede bloqueou a instalação de FastAPI/HTTPX neste ambiente.
- Compilação Python e verificação sintática do JavaScript passaram.

## Próximo marco

Instalar as dependências em uma máquina com acesso ao índice Python e executar os testes HTTP. Depois, revisar as evidências de um produto meteorológico específico e desenhar o adaptador com timeout, limites de tamanho, validação de formato, retry controlado e registro de saúde antes de habilitar qualquer coleta.
