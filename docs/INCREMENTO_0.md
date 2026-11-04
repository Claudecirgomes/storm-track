# Incremento 0 - contrato de implementação

**Base:** `StormTrack_Auditoria_Final_Gate_Arquitetura_v2` (matriz ST-001–ST-053) e `StormTrack_Diagramas_Auditados_v1.1`.

## Decisão técnica

Construir a fundação local gratuita antes dos algoritmos meteorológicos: FastAPI, SQLite e módulos pequenos. A arquitetura não inicia fonte automaticamente. As aprovações metodológicas e os termos de cada fonte continuam sendo gates independentes.

## Entregue neste incremento

| Requisito/regra | Implementação | Estado |
|---|---|---|
| ST-001, ST-002 | Contas locais, perfis `USER` e `ADMIN`, login por token | Implementado no núcleo |
| ST-045 | Catálogo `DataSource`/`SourceProduct`; estados independentes de acesso, coleta, armazenamento e redistribuição | Implementado; tudo começa pendente |
| ST-048 | Endpoint protegido para consultar logs operacionais | Implementado, logs mínimos |
| Limite do piloto | No máximo 5 contas; 1 Admin + até 4 User; sem signup público | Contagem serializada no serviço; unicidade de username e de Admin também protegidas no banco |
| Autorização backend | `HTTPBearer`, sessão ativa e dependência Admin | Implementado nas rotas protegidas |
| Persistência | SQLite, transações imediatas em provisionamento, FK e checks | Implementado |

## Ajuste de rastreabilidade identificado

O incremento adiciona `sessions` para expiração e revogação de tokens. Essa estrutura técnica não aparece como entidade explícita no DER v1.1. Ela dá suporte a ST-001/ST-002 e ao UC-01, sem ampliar o limite de contas nem criar cadastro público. Antes de declarar nova auditoria cruzada final, atualizar Classes/DER para `AuthSession` e Sequência para emissão, validação, expiração e revogação da sessão.

## Não implementado neste incremento

Frontend/Leaflet, scheduler, coletores, fusão, observações meteorológicas, detecção, CELL-ID, riscos, IA/ensemble, nowcast, impacto geográfico, alertas, replay e simulação. A ausência é intencional: esses módulos precisam de contratos de dados, gates específicos e testes históricos.

## Critérios de aceite

1. Inicialização cria o esquema sem substituir dados existentes.
2. Uma segunda conta Admin, uma sexta conta e um quinto usuário são recusados.
3. Senha nunca é armazenada em texto claro; token de sessão também não.
4. Conta desativada, sessão inválida e perfil inadequado não autorizam operações.
5. Produto novo inicia desabilitado e com as quatro situações `PENDING`.
6. Coleta local só pode ser autorizada quando acesso técnico, coleta, armazenamento e habilitação estiverem confirmados. Redistribuição exige verificação adicional própria.
7. Testes não dependem de internet nem de dados meteorológicos reais.

Uma mudança para `VERIFIED` exige uma referência de termos/evidência. A ativação da coleta local exige referência e os estados de acesso, coleta e armazenamento verificados. O gate de redistribuição permanece separado e não é ativado automaticamente.

## Próximo marco após este incremento

Validar execução local no computador do projeto e completar teste de API com `TestClient`. Depois, implementar uma tela simples de login/saúde e gestão visual do catálogo. Só então integrar o primeiro produto de observação com termos de uso confirmados, guardando payload bruto e metadados em UTC e testando duplicação/retentativas. Nenhum limiar meteorológico deve ser inventado nesta fase.
