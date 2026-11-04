# StormTrack — auditoria integral do repositório

**Data:** 04/10/2026  
**Escopo auditado:** código disponível em `backend/`, `frontend/`, `tests/`, configuração, README e documentação técnica do MVP.  
**Base de decisão:** MVP acadêmico gratuito/local-first; FastAPI + SQLite; até cinco contas locais (1 ADMIN + até 4 USER); produtos começam pendentes/desabilitados; fontes aguardam análise de termos e dados; diagramas continuam rascunhos, sem aprovação final.  
**Limite:** revisão de código e testes automatizados disponíveis; não é certificação de segurança nem prova matemática de ausência de defeitos.

## Parecer executivo

A fundação é coerente para um MVP local de autenticação, catálogo de fontes e persistência interna de observações. O repositório **não implementa ainda o monitoramento meteorológico descrito pelos requisitos ST**: não há coleta, scheduler, adaptadores, mapa conectado, detecção/tracking de células, risco, nowcast, alertas ou replay. Portanto, deve ser tratado como protótipo técnico de fundação, não como sistema operacional de alerta meteorológico.

Foram encontrados e corrigidos defeitos de integridade e rastreabilidade: evidência composta só por espaços podia satisfazer a regra de autorização; registros de proveniência não estavam protegidos no SQLite contra `UPDATE`/`DELETE`; o timestamp de verificação de acesso era regravado em alterações não relacionadas; e o log de provisionamento atribuía a autoria à conta recém-criada. Também foram corrigidos trechos de documentação que diziam que não havia código executável e que a modelagem estava fechada, em conflito com o estado real do repositório e com a decisão de manter os diagramas como rascunhos.

## Achados corrigidos

| ID | Severidade | Achado | Correção | Verificação |
|---|---|---|---|---|
| SEC-01 | Alta | `terms_reference="   "` era aceito no cadastro e podia ser usado depois para satisfazer os gates sem uma evidência real. | Normaliza espaços para `NULL` no serviço; o banco e o serviço interno de ingestão também falham fechado. | Teste regressivo cobre cadastro e tentativa de aprovação sem evidência. |
| DATA-01 | Média | Registros de artefato, observação, revisão, qualidade e saúde eram append-only pela lógica de serviço, mas aceitavam alteração/exclusão SQL. | Triggers SQLite rejeitam `UPDATE` e `DELETE` nas tabelas de proveniência meteorológica. | Testes tentam alterar e excluir linhas de cada tabela e esperam erro de integridade. |
| DATA-02 | Média | Uma escrita direta/legada com evidência em branco podia passar pelo limite interno de ingestão. | Ingestão falha fechado e triggers também impedem habilitar produto sem evidência não vazia e os três gates locais. | Testes exercitam o limite interno e uma tentativa SQL de habilitação inválida. |
| AUD-01 | Baixa | O log de provisionamento atribuía a criação da conta à própria conta recém-criada. | Provisionamento local passa a registrar ator nulo (origem técnica) em vez de atribuir autoria falsa. | Teste confirma `actor_id` nulo no evento. |
| AUD-02 | Baixa | Atualizar gates sem mudar acesso renovava `access_verified_at`, distorcendo quando o acesso tinha sido verificado. | Timestamp só muda quando `access_status` é explicitamente enviado como verificado. | Teste preserva timestamp sentinela ao alterar redistribuição. |
| DOC-01 | Média | Documento UML dizia que nenhum código executável existia e tratava a estrutura como fechada/aprovada. | Texto agora identifica a modelagem como rascunho, separa consistência entre diagramas de implementação e reconhece o código existente sem alegar prova formal. | Busca textual e leitura das seções revisadas. |
| DOC-02 | Baixa | Incremento 0 atribuía ao banco o limite total de cinco contas; o banco só garante username único e no máximo um ADMIN. | Precisão corrigida: limite total e de USER é serializado no serviço de provisionamento. | Comparação entre documentação, serviço e índices SQLite. |

## Estado por camada

| Camada | Implementado | Parcial/limite |
|---|---|---|
| Interface | Login, estado de saúde, navegação Monitoramento/Fontes/Auditoria; catálogo e logs administrativos; estado vazio explícito. | Camadas são indicadores visuais, não visualizações meteorológicas; sem mapa, células, dados ou alertas. |
| API | Saúde, login/me/logout, catálogo protegido, CRUD administrativo de produto/gates e consulta de logs. | Sem endpoints de observações, eventos, mapas, previsões, alertas ou administração de regiões/métodos. |
| Contas/sessões | scrypt, token aleatório, hash do token em sessão, expiração, revogação e autorização de ADMIN no backend. | Sem limitação de tentativas de login; a operação deve permanecer local. Se exposta em rede, precisa de controles adicionais. |
| Fontes/gates | Produto começa com gates `PENDING` e desabilitado; ativação exige evidência e acesso/coleta/armazenamento verificados; redistribuição é independente. | Um campo de referência serve para evidências; nenhum provedor foi conectado ou legalmente analisado. Não há cadência/tipo de produto nem adaptador. |
| SQLite | FK, índices e checks; observações com horário UTC/original, deduplicação por produto, revisões preservadas, qualidade e saúde com estados desconhecidos. | Banco local em arquivo único; sem migrações versionadas, backup/restore automatizado ou endpoint de leitura meteorológica. Triggers protegem registros de proveniência contra alterações acidentais pela aplicação, não contra o proprietário do arquivo removendo o banco ou os triggers. |
| Persistência de observação | Serviço interno rejeita produto inexistente, desabilitado ou sem gates/evidência; reentrega idêntica é ignorada; conteúdo diferente gera revisão. | Não existe coletor chamando o serviço. Validação de payload, limites de tamanho, unidade e esquema de geometria deve ser definida antes de conectá-lo. |
| Testes | Regras de conta, senha/sessão, gates, ingestão, timestamps, duplicatas, revisões, qualidade e saúde. | Três testes HTTP foram ignorados no ambiente por falta de FastAPI/HTTPX; autorização e integração HTTP não ficaram validadas nesta execução. |

## Rastreabilidade resumida dos requisitos ST

- **ST-001–002:** base parcialmente implementada — contas locais, autenticação, perfis e autorização; sem gestão de contas pelo painel.
- **ST-003–004:** não implementados — mapa e detalhes de célula são espaços vazios.
- **ST-005:** não implementado — sem scheduler nem coleta automática.
- **ST-006–009:** parciais — persistência interna cobre deduplicação e tempos observados/recebidos; sem ingestão, normalização ampla de unidades/coordenadas ou ciclo de qualidade de fonte.
- **ST-010–044:** não implementados — detecção, CELL-ID, linhagem, riscos, nowcast, classificação, IA/ensemble, impacto, alertas, validação e simulação ainda são requisitos de arquitetura.
- **ST-045:** parcial — catálogo e quatro gates existem; classificação completa de produtos, cadência e análise real de licença ainda não.
- **ST-046–047:** parciais/não implementados — interface não controla processamento, mas as camadas ainda são somente indisponíveis; regiões e parâmetros não são configuráveis.
- **ST-048:** parcial — saúde do banco e logs administrativos básicos existem; monitoramento de saúde por fonte não está exposto/automatizado.
- **ST-049–050:** não implementados — não há execução de simulação nem marcador Ponto I.
- **ST-051–053:** evolução, fora do MVP atual conforme escopo documentado.

## Riscos remanescentes antes de qualquer integração meteorológica

1. **Testes HTTP sem execução:** instalar as dependências em ambiente autorizado e rodar `python -m unittest discover -s tests -v`; incluir testes para limites e autorização por rota.
2. **Contrato por fonte:** analisar termos, atribuição, formato, resolução, atrasos, correções, unidades, timestamps, tamanho máximo e limites de consulta antes de escolher um adaptador.
3. **Validação de ingestão:** definir GeoJSON/CRS suportado, limites de payload, esquema versionado, normalização e tratamento de dados atrasados/corrompidos.
4. **Operação local:** restringir o servidor ao loopback conforme o README, proteger o arquivo SQLite e planejar cópia de segurança/restauração.
5. **Reprodutibilidade:** fixar versões de dependências e adicionar migrações versionadas antes de distribuir ou evoluir o banco.
6. **Métodos meteorológicos:** manter limiares e algoritmos bloqueados até aprovação documental e validação com eventos históricos; IA não deve ser autoridade única para risco crítico.
7. **Prova formal:** F-01–F-12 são obrigações de desenho, não provas concluídas. Nenhuma ferramenta de model checking ou CI de invariantes foi executada.

## Verificações executadas nesta auditoria

- `python -m compileall -q backend tests`: passou.
- `node --check frontend/app.js`: passou.
- `python -m unittest discover -s tests -v`: 26 testes encontrados; 23 passaram e 3 HTTP foram ignorados por dependências ausentes.
- Regressões adicionadas para evidência em branco, gates no banco, timestamp de verificação, autoria de provisionamento e imutabilidade dos registros de proveniência.
- Revisão manual de rotas, dependências de autorização, transações, regras de gate, esquema SQLite, manipulação do DOM e documentação.

## Próximo marco recomendado

Antes de ampliar a interface, concluir a validação HTTP da fundação e escolher **um único produto** para análise técnica e de uso. Só depois implementar um adaptador isolado com limites, validação, saúde, falha parcial e testes com amostras autorizadas. A primeira tela com dados reais deve vir após existir contrato de leitura e verificação da proveniência.
