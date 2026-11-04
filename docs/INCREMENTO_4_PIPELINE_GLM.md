# Incremento 4 — pipeline local preparado para NOAA GLM

**Estado:** adaptador e worker implementados; scheduler opt-in; produto ainda pendente; sem coleta real validada.  
**Escopo:** observações de flashes do NOAA GOES-19 GLM-L2-LCFA.  
**Data de revisão:** 04/10/2026.

## Decisão técnica

O projeto prioriza GOES-19 ABI/GLM como primeira fonte candidata. O bucket público NOAA GOES pode ser acessado sem conta AWS; páginas oficiais descrevem arquivos NetCDF e estrutura por produto/ano/dia/hora. A disponibilidade pública não valida nosso parser nem conclui permissões de uso e redistribuição.

Referências oficiais: registry NOAA GOES em registry.opendata.aws/noaa-goes; guia GOES-R em goes-r.gov; catálogo NODD NOAA; metadados GLM-L2-LCFA no NOAA NCEI.

O leitor trata GLM como observação de raios. Não classifica tempestades, não estima severidade e não emite risco ou alerta.

## O que está no código

- Adaptador NOAA com listagem de janela curta, timeout, limite de tamanho e parser NetCDF.
- Serviço de ingestão com gates por ciclo, proveniência, cursor, deduplicação e registro de execução.
- Scheduler opt-in, desligado por padrão.
- Rotas autenticadas para observações, GeoJSON, ciclos, métodos e alertas não emitidos.
- Frontend plota apenas observações retornadas pela API numa grade local, sem pontos sintéticos nem base cartográfica de terceiros.
- Registros de execução, cursores, saúde da fonte e qualidade desconhecida quando não medida.

## Candidatos que aguardam liberação

A inicialização idempotente inclui estes produtos em PENDING e desabilitados:

| Produto | Preparação atual |
|---|---|
| NOAA GOES-19 GLM-L2-LCFA | Adaptador disponível, coleta opt-in, gates pendentes |
| NOAA GOES-19 ABI-L2-MCMIPF | Candidato catalogado; adaptador pendente |
| SIMEPAR RADAR-PR | Revisão/liberação pendente; sem conector |
| SMN/SINARAME-RADAR | Revisão/liberação pendente; sem conector |
| INUMET RADAR-UY | Revisão/liberação pendente; sem conector |
| Defesa Civil RS ALERTAS-RS | Revisão/liberação pendente; sem conector |
| CPTEC/INPE PRODUTO-SATELITE-RADAR | Revisão/liberação pendente; sem conector |

Esse catálogo prepara a avaliação, sem evidência presumida e sem chamadas às fontes. Cada integração futura requer adaptador e validação próprios.

## Barreiras de execução

1. STORMTRACK_COLLECTION_ENABLED é false por padrão.
2. O produto deve estar enabled e ter gates VERIFIED para acesso, coleta e armazenamento, além de referência documental.
3. Os gates são checados em cada ciclo. A frequência configurável é limitada a 20–300 segundos; a janela consultada inclui margem e repete uma janela recente com deduplicação para aceitar objetos que cheguem fora de ordem.
4. Listagem, número de objetos, tamanho e tempo de resposta são limitados.
5. Coleta local não libera redistribuição.
6. Falhas não são mostradas como “sem raios” ou “sem risco”.

## Validação necessária antes da primeira coleta real

- Revisar termos, atribuição, armazenamento, retenção e redistribuição.
- Inspecionar NetCDF real autorizado e comparar variáveis, máscaras, coordenadas e timestamp.
- Confirmar escala temporal/espacial e projeção antes de interpretação cartográfica.
- Exercitar indisponibilidade, arquivo corrompido, atraso, repetição, limites e recuperação.
- Habilitar somente um produto em ensaio controlado e conferir proveniência e mapa.

Os testes atuais usam rede simulada; não demonstram compatibilidade do parser com arquivo real nem disponibilidade de serviço. Listagem do S3 sinalizada como truncada e janela acima do cap de 30 objetos falham explicitamente, sem declarar sucesso parcial silencioso. Não existe backfill para indisponibilidade além da janela recente.

## Métodos meteorológicos ainda bloqueados

Detecção/tracking de células, risco de vento/granizo/rotação, nowcast e alertas permanecem pendentes de método e validação. A API de alertas não emite itens. Cada método precisa de referência, versão, escopo, métricas, casos independentes e revisão meteorológica.

## Riscos e limites conhecidos

- Não há backfill/replay; uma janela pode ser perdida durante falha.
- Um processo local não tem alta disponibilidade nem política automatizada de retenção/restauração.
- Dados consomem disco local; custo de nuvem alvo é R$ 0/mês.
- O mapa é grade de coordenadas, sem contornos políticos, tiles ou escala.
- Uma observação GLM não é uma célula nem determina risco.
- Cinco testes HTTP dependem da instalação de dependências; a rede deste ambiente bloqueou a instalação.
