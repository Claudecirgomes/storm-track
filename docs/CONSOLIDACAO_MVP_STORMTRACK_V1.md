# StormTrack — consolidação do MVP e parecer de auditoria

**Versão:** 1.5  
**Data:** 05/10/2026  
**Natureza:** baseline consolidado do MVP acadêmico local-first  
**Situação:** imagens NOAA GOES-19 ABI exibidas no app via proxy; coleta GLM e fontes regionais seguem pendentes; operação meteorológica não validada. Este documento não certifica operação nem prova formal de ausência de defeitos.

## 1. Parecer executivo

O StormTrack evoluiu da fundação local para uma primeira fatia de ingestão de observações. Há catálogo de fontes, gates de governança, adaptador NOAA GOES-19 GLM, agendador opt-in, persistência de observações, API autenticada de leitura, GeoJSON e representação local no mapa. Isso forma uma estrutura executável de MVP, mas ainda não demonstra coleta meteorológica ao vivo.

A coleta meteorológica permanece desligada por padrão e os gates GLM continuam pendentes. O adaptador foi exercitado com rede simulada; não houve coleta validada do bucket nem teste do parser com NetCDF NOAA real. O painel pode exibir imagens ABI públicas, mas só mostrará observações GLM após coleta aprovada e verificada.

**Decisão:** manter o proxy de imagens ABI ativo apenas para exibição no app; avançar a preparação das outras fontes sem coleta, arquivo ou redistribuição automáticos até validar endpoint, termos e amostra por produto. Não anunciar previsão, detecção operacional, avaliação de risco ou alertas.

### Por que ainda não opera como monitor meteorológico

Autorizações são um bloqueio, mas não o único. Autorização de uso não implementa adaptadores, não valida resultados meteorológicos e não torna o processo resiliente.

| Área | Implementado | Ainda necessário |
|---|---|---|
| Fonte e governança | Catálogo idempotente; gates e evidências; fontes novas começam PENDING/desabilitadas | Revisar termos, limites, atribuição, armazenamento e redistribuição por produto |
| Coleta | Adaptador GLM limitado e agendador opt-in; gates verificados em cada ciclo | Aprovação documentada, teste em arquivo real, execução controlada e validação operacional |
| Dados e API | Persistência de observações, proveniência, histórico de revisão e rotas autenticadas | Contrato meteorológico completo, migrações, retenção e backup/restore validado |
| Mapa | Grade local com GeoJSON recebido pela API; sem eventos fictícios ou tiles externos | Base geográfica e validação visual/geoespacial de dados reais |
| Meteorologia | Estados dos métodos explicitamente pendentes | Métodos publicados, versionados e avaliados com casos históricos independentes |
| Operação | Registro de ciclos e saúde por fonte; falhas tratadas | Recuperação testada, retenção, alertas técnicos, rotina operacional e instalação reproduzível |

Autorização remove apenas uma parte do bloqueio de uso. O marco do MVP observacional exige fonte autorizada, coleta demonstrada, proveniência revisada e mapa de observações reais. Detecção, risco, nowcast e alertas exigem gates próprios.

## 2. Objetivo e limites do produto

O projeto acadêmico local-first estuda monitoramento de tempestades severas no corredor Argentina/Paraguai/Uruguai → Rio Grande do Sul → Santa Catarina → Paraná, com Maringá como foco adicional.

O desenho separa observações de análises derivadas e previsões; alertas oficiais de experimentais; qualidade do dado de confiança do método; e processamento no backend de inspeção visual. IA não será autoridade única para declarar supercélula ou tornado.

## 3. Situação real: código versus plano

| Área | Estado implementado | Estado ainda ausente |
|---|---|---|
| Acesso | Login local, perfis ADMIN/USER, sessões expiradas/revogáveis; limite de uma conta ADMIN e quatro USER no provisionamento | Administração de contas pelo painel e segurança para exposição em rede |
| Fontes | Catálogo e gates; imagens NOAA ABI no app; NOAA GLM tem adaptador opt-in; fontes regionais pendentes | Conectores de ingestão para NOAA ABI, SIMEPAR, SMN/SINARAME, INUMET, Defesa Civil RS e CPTEC/INPE |
| Coleta | Ciclo GLM com limites, timeout, status, cursor e registro; desligado por padrão | Acesso real ao bucket, validação de NetCDF real, recuperação e backfill |
| Persistência/API | SQLite, deduplicação, revisões e proveniência; GET autenticados de observações, GeoJSON, ciclos, status analítico e alertas | Migrações versionadas, retenção, backup/restauração e modelo multi-produto completo |
| Interface | Frontend local; grade geográfica desenha apenas observações retornadas pela API | Mapa-base cartográfico e camadas meteorológicas derivadas |
| Métodos | Estados dos métodos pendentes; alertas não são emitidos | Detecção/tracking, CELL-ID, risco, rotação, nowcast, previsão e alertas validados |
| Operação | Saúde e falhas de ciclo registradas; scheduler opt-in | Recuperação robusta, procedimentos, implantação e continuidade |

A lista de fontes pendentes prepara o catálogo para avaliação. Ela não contém endpoints de origem, credenciais, decisões legais ou conectores que possam ser ligados por configuração.

Os diagramas de caso de uso, classes, sequência e DER em docs/StormTrack_Diagramas_Auditados_v1.3.md são modelos arquiteturais em revisão; não provam que todos os módulos foram implementados.

## 4. Usuários e casos de uso disponíveis

O piloto prevê no máximo cinco contas locais: um ADMIN e até quatro USER. Não há cadastro público.

| Caso de uso | Ator | Resultado disponível |
|---|---|---|
| Entrar e encerrar sessão | USER/ADMIN | Sessão validada no backend, com expiração e revogação |
| Consultar observações | USER/ADMIN | Consulta autenticada; só dados persistidos são retornados |
| Consultar mapa | USER/ADMIN | Exibe pontos do GeoJSON; estado vazio significa dados indisponíveis |
| Consultar catálogo | USER/ADMIN | Visualiza produtos, gates e status de integração |
| Alterar evidência/gates | ADMIN | Registra decisão; não substitui revisão nem teste técnico |
| Consultar ciclos/saúde/auditoria | Conforme rota | Consulta registros locais disponíveis |

Detecção de células, previsão A30/A60/A90, risco e alertas não são casos de uso operacionais disponíveis.

## 5. Arquitetura consolidada

### 5.1 Fluxo implementado

Navegador local ⇄ FastAPI/autorização ⇄ serviços de conta, fonte, ingestão e observação ⇄ SQLite.  
Na coleta opt-in: NOAA GLM → adaptador limitado → validação/normalização → persistência com proveniência → API autenticada → grade local. Separadamente, o proxy ABI busca JPEG NOAA pelo backend autenticado e entrega os quadros recentes à tela; não persiste nem interpreta as imagens.

A API protege leituras meteorológicas por sessão. A interface não é fronteira de segurança. O scheduler só inicia quando STORMTRACK_COLLECTION_ENABLED=true, e cada ciclo checa produto e gates novamente.

### 5.2 Estrutura do projeto

| Caminho | Responsabilidade |
|---|---|
| backend/app/api | Rotas, autenticação e autorização |
| backend/app/accounts | Contas e sessões |
| backend/app/sources | Catálogo, gates e evidências |
| backend/app/adapters | Adaptador NOAA GLM; proxy NOAA ABI; conectores regionais fail-closed |
| backend/app/ingestion | Ciclos, scheduler, cursores e registros de execução |
| backend/app/observations | Validação, persistência e leitura/GeoJSON |
| backend/app/analysis | Estado dos métodos; não executa análise meteorológica |
| backend/app/core | Configuração, segurança e SQLite |
| frontend | Interface local e mapa de observações |
| tests | Regressões de regras, persistência, ingestão mockada e HTTP opcional |
| docs | Auditorias, arquitetura, diagramas e consolidação |

Cada novo produto seguirá: revisão e evidência → adaptador isolado → validação e normalização → persistência/proveniência → API de leitura → interface. Métodos derivados entram depois em módulos versionados e validados.

## 6. Fontes e gates de liberação

O catálogo semeia produtos PENDING e desabilitados:

| Provedor | Produto candidato | Preparação atual |
|---|---|---|
| NOAA GOES-19 | GLM-L2-LCFA | Adaptador implementado; opt-in; gates pendentes; sem coleta real demonstrada |
| NOAA GOES-19 | ABI-L2-MCMIPF / GeoColor Full Disk | Proxy de JPEG oficial ativo no app; sem arquivo local, análise ou overlay; uso informativo |
| SIMEPAR | RADAR-PR | Estrutura de conector isolada; aguarda perfil técnico e liberação; sem chamadas de rede |
| SMN Argentina | SINARAME-RADAR | Estrutura de conector isolada; aguarda perfil técnico e liberação; sem chamadas de rede |
| INUMET | RADAR-UY | Estrutura de conector isolada; aguarda perfil técnico e liberação; sem chamadas de rede |
| Defesa Civil RS | ALERTAS-RS | Estrutura de conector isolada; aguarda perfil técnico e liberação; sem chamadas de rede |
| CPTEC/INPE | PRODUTO-SATELITE-RADAR | Estrutura de conector isolada; aguarda perfil técnico e liberação; sem chamadas de rede |

A NOAA documenta acesso público aos dados GOES-19 em bucket aberto e especifica atribuição para dados sem alteração. Isso não valida nosso parser, não conclui a revisão de cada uso e não representa autorização para redistribuir produtos processados. Referências oficiais consultadas: registry NOAA GOES (registry.opendata.aws/noaa-goes), guia GOES-R (goes-r.gov), catálogo NODD NOAA e metadados GLM-L2-LCFA do NOAA NCEI.

Para uma fonte entrar em coleta, o ADMIN registra evidência e confirma separadamente acesso, coleta e armazenamento. Redistribuição tem gate próprio. VERIFIED é decisão administrativa registrada, não certificação automática da fonte.

## 7. Segurança, dados e limites operacionais

- Senhas usam scrypt; somente hash do token de sessão é persistido.
- Observações e revisões são append-only pelas regras SQLite; conteúdo corrigido abre revisão.
- Qualidade desconhecida permanece desconhecida, não vira zero nem ausência de risco.
- O adaptador GLM limita janela recente, quantidade de objetos, tamanho de arquivo e tempo de resposta.
- Não há backfill/replay nem alta disponibilidade; uma janela pode ser perdida durante falha.
- Dados consomem disco local; retenção e recuperação do banco ainda exigem política e ensaio.
- O mapa é uma grade sem base cartográfica; os pontos são observações GLM, não células.
- A posse do arquivo SQLite permite alterações fora dos controles da aplicação.
- A meta de custo é R$ 0/mês; banda, armazenamento local e energia continuam sendo consumidos.

## 8. Rastreabilidade dos requisitos ST

| Grupo | Estado consolidado |
|---|---|
| ST-001–002 | Parcial: contas, sessão e perfil |
| ST-003–004 | Parcial: mapa de pontos observados; célula não implementada |
| ST-005 | Parcial: scheduler/adaptador GLM; coleta desligada e sem validação real |
| ST-006–009 | Parcial: persistência, deduplicação, revisões e proveniência |
| ST-010–044 | Pendente: detecção, tracking, risco, nowcast, IA, impacto, alertas, replay e validação |
| ST-045 | Parcial: catálogo/gates; revisão por produto pendente |
| ST-046–047 | Parcial: API de observações e mapa básico |
| ST-048 | Parcial: registros de saúde/ciclos; recuperação incompleta |
| ST-049–050 | Pendente: simulação operacional e marcador Ponto I |
| ST-051–053 | Fora do MVP atual |

## 9. Parecer de auditoria e verificações

Foram verificados gates/evidências, persistência append-only, deduplicação, revisões e ingestão sob gates. A suíte encontrou 37 testes: 32 passaram e cinco testes HTTP foram ignorados porque FastAPI/HTTPX não estão instalados neste ambiente. A tentativa de instalar dependências foi bloqueada pela restrição de rede. Também passaram compileall do Python e node --check do frontend.

Os testes do adaptador usam mocks; não provam disponibilidade da NOAA, compatibilidade com NetCDF real nem correção meteorológica. Não foram executados testes de carga, model checking, prova formal de invariantes, auditoria externa ou simulação de recuperação. A evidência limita-se às verificações executadas e não equivale a ausência de defeitos.

## 10. Critérios para avançar

### Gate A — fundação local
- Instalar dependências e executar todos os testes HTTP.
- Validar instalação limpa, login/perfis, banco, backup e restauração.
- Manter o serviço em loopback até definir controles para exposição em rede.

### Gate B — produto observacional piloto
- Revisar termos, atribuição, acesso automatizado, armazenamento, retenção e redistribuição.
- Registrar evidência sem habilitar outros produtos.
- Testar parser com amostras oficiais reais; comparar esquema, horário e coordenadas.
- Validar timeout, tamanho, repetição, atraso, falha, saúde e recuperação.
- Habilitar um produto em ensaio controlado e conferir proveniência e mapa.

### Gate C — métodos meteorológicos
- Definir referência, versão, domínio de validade, parâmetros e métricas.
- Validar com casos históricos independentes, separando desconhecido de negativo.
- Liberar detecção, risco, previsão e alertas apenas no escopo validado.
- Auditar falsos positivos/negativos e apresentação de incerteza.

## 11. Decisão consolidada

Pode avançar a infraestrutura observacional e a preparação documental dos candidatos. As fontes que aguardam liberação já aparecem no catálogo e estão organizadas para revisão, mas continuam desconectadas e desabilitadas até decisão por produto.

Ainda não se pode declarar monitoramento operacional, coleta real validada, risco meteorológico atual, previsão ou alerta confiável, licença aprovada para todos os usos ou garantia matemática de ausência de defeitos. A próxima etapa técnica é executar Gate A e validar em ambiente controlado a fatia NOAA GLM; em paralelo, avaliar as fontes regionais sem ativá-las.


## 12. Revisão total de métodos e satélite

A conclusão da revisão foi atualizada: imagens públicas GOES-19 ABI agora são obtidas pelo backend e exibidas dentro do StormTrack. Isso conecta um fluxo de imagens para inspeção visual, mas não uma cadeia ABI de ingestão meteorológica, interpretação ou arquivo. O adaptador GLM continua separado, com gates pendentes, coleta desligada e sem validação de arquivo real.

A revisão corrigiu a perda potencial de produtos GLM atrasados dentro da janela recente, falha silenciosa por truncamento, incompatibilidade entre intervalo máximo e janela de consulta, rótulo ambíguo do adaptador e retorno de estado analítico mutável. A configuração de coleta agora aceita 20–300 segundos, faz polling recente idempotente e falha explicitamente quando limites de listagem são excedidos. Continua sem backfill para interrupções longas.

Agora é possível avançar com validação de payload, ingestão, proveniência, frescor mensurável e resumo descritivo de flashes. Detecção/tracking de célula, vento, granizo, rotação, nowcast e alertas operacionais permanecem pendentes: o produto GLM é observação de raios, não mede esses perigos nem identifica sozinho células. O próximo passo é uma sondagem controlada e análise de arquivo NetCDF real, seguida de validação independente antes de qualquer método. O relatório detalhado está em docs/REVISAO_TECNICA_TOTAL_METODOS_SATELITE_2026-10-04.md.

## 13. Incremento 5 — conectores e imagem de satélite

O painel recebe JPEGs timestamped do catálogo oficial NOAA GOES-19 ABI GeoColor Full Disk pelo backend. O operador pode inspecionar até 12 quadros recentes e acompanhar visualmente a evolução das nuvens. O backend limita host, nome, tamanho, tipo de conteúdo e tempo de resposta; não guarda nem processa os quadros. A NOAA qualifica este produto web como informativo, não para uso operacional ou emergencial; a tela apresenta a ressalva.

Foram preparados conectores fail-closed separados para SIMEPAR, SMN/SINARAME, INUMET, Defesa Civil RS e CPTEC/INPE. Seus endpoints, protocolos, formatos, condições de uso e amostras precisam ser confirmados antes de completar parsers ou habilitar chamadas. A API `GET /api/connectors` expõe o estado; `GET /api/satellite/goes19/abi` entrega os metadados do visualizador. Todas as fontes seguem com coleta automática desativada.

Validação: testes unitários confirmam que os conectores regionais recusam chamadas sem perfil, ABI é o único item de imagem marcado como exibição interna e nomes inválidos não chegam à rede. Testes do catálogo usam resposta simulada. A conexão real e o fluxo de tela ainda precisam de verificação no ambiente local com internet; não foram certificados neste ambiente.

Detalhamento: `docs/INCREMENTO_5_CONECTORES_ABI.md`.


## 14. Imagens públicas de outras fontes e estado da integração

A pesquisa confirmou imagens oficiais adicionais, mas visibilidade pública não equivale a autorização para proxy, retenção ou redistribuição. Por isso a NOAA é a única fonte de imagem ativada nesta versão.

| Fonte | Resultado da revisão | Próximo passo para habilitar no app |
|---|---|---|
| SIMEPAR Radar-PR | Página oficial mostra radar/mosaico de PR e vizinhança, inclusive imagem recente; termos de uso exibem direitos reservados e não fecham automação/redistribuição. | Confirmar autorização e endpoint estável; validar imagem e atribuição. |
| Defesa Civil RS radar POA | Visual oficial informa atualização de 5 min e raio aproximado de 150 km; acesso disponível por painel incorporado, sem endpoint direto confirmado. | Obter contrato/API de imagem e definir cobertura para fora da região de Porto Alegre. |
| SMN/SINARAME | Portal oficial de mapas foi identificado, mas indisponível na consulta desta revisão; escopo dos termos de dados operacionais não foi verificado. | Confirmar disponibilidade, produto, formato e condições específicas do radar. |
| INUMET | Há dados abertos, observações e mapas mensais de chuva; não foi encontrado radar público em imagem com atualização para acompanhar tempestades. | Validar possibilidade de API/produto radar; não usar mapas mensais como ao vivo. |
| CPTEC/INPE | Produtos de satélite/radar públicos; a página limita uso comercial e reprodução sem autorização expressa; disponibilidade oscilou. | Solicitar/confirmar permissão do produto exato antes de replicar. |
| IPMet/UNESP | Animação/imagem de radar pública para região de Bauru; endpoint, regras de uso e cobertura sul não foram confirmados. | Manter candidato futuro até fechar escopo e direitos. |

API de ABI: `GET /api/satellite/goes19/abi/frames` fornece até 24 nomes permitidos; `GET /api/satellite/goes19/abi/image/{filename}` faz proxy autenticado de uma imagem JPEG. O manifesto usa cache de 60 s e a tela atualiza a lista em 5 min. Não existe arquivo local nem animação contínua; o operador percorre os quadros recentes no controle deslizante.
