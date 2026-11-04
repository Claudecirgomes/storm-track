# StormTrack — Incremento 1: painel local

## Decisão

O Gate de Arquitetura v2 define frontend web leve como etapa 2 do roadmap. Este incremento acrescenta a primeira interface local para observar a saúde do serviço, autenticar contas já provisionadas e administrar o catálogo de produtos de fonte.

## Entregue

- `frontend/index.html`, `frontend/styles.css` e `frontend/app.js`, sem bibliotecas, CDN ou chamadas externas.
- FastAPI serve o painel na raiz e os ativos estáticos no mesmo host.
- Login, consulta da sessão e logout revogável integrados à API existente. O navegador mantém o token apenas em `sessionStorage` da aba, nunca em `localStorage`.
- Usuário consulta produtos e gates. Administrador pode cadastrar produtos e alterar evidência, estados de acesso/coleta/armazenamento/redistribuição e autorização futura.
- Logs operacionais disponíveis somente ao Administrador.
- Mensagem explícita quando o feed meteorológico está ausente; o painel não interpreta ausência de dados como ausência de ameaça.

## Alinhamento e correção de rastreabilidade

O código do Incremento 0 introduziu `sessions`, mas os diagramas v1.1 não representavam essa entidade. O documento UML foi atualizado para v1.2:

- `AuthSession` entrou no diagrama de classes e no DER, com digest do token, expiração e revogação.
- A sequência de autenticação agora descreve emissão, validação em cada rota protegida e logout.
- `DataSource` e `SourceProduct` foram ajustados para que os quatro gates e `enabled` residam no produto, conforme o esquema SQLite efetivamente implementado.
- A cobertura permanece em ST-001/ST-002, UC-01, UC-07 e UC-08; nenhum caso de uso meteorológico foi declarado concluído.

## Fora deste incremento

O mapa é apenas um painel de estado, sem Leaflet, dados, radar, satélite ou células. Não há scheduler, coletor, detecção, tracking, risco, nowcast, IA, alerta ou simulação. Marcar um produto como autorizado não dispara integração, e redistribuição não é necessária para coleta/armazenamento local.

## Verificação

- Na execução daquele incremento, 10 testes de núcleo passaram; 3 testes HTTP ficaram ignorados por falta de FastAPI/HTTPX.
- `compileall` e `node --check frontend/app.js` devem passar.
- Três testes HTTP, incluindo servir a página, dependem de FastAPI e HTTPX; sem essas dependências ficam ignorados e não contam como integração validada.
- A interface usa `textContent` ao apresentar dados recebidos e não inclui ativos de terceiros.

## Próximo marco

1. Instalar dependências e executar os testes HTTP.
2. Ligar um mapa Leaflet sem camada meteorológica fictícia.
3. Escolher e validar documentalmente um primeiro produto autorizado antes de criar adaptador de coleta.
4. Manter coleta desabilitada até acesso, coleta automatizada e armazenamento do produto estarem verificados com evidência.
