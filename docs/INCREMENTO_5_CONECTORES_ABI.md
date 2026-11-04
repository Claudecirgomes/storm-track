# Incremento 5 — conectores preparados e imagens GOES-19 ABI no app

**Data:** 05/10/2026  
**Estado:** imagens NOAA ABI carregadas pelo backend e exibidas no app; conectores regionais isolados e pendentes; coleta meteorológica desligada.

## Entrega

- Painel de satélite consulta um catálogo oficial NOAA de JPEGs GeoColor e carrega os quadros pelo backend autenticado, sem iframe ou link externo.
- `GET /api/satellite/goes19/abi/frames` lista até 24 nomes validados; `GET /api/satellite/goes19/abi/image/{filename}` serve apenas nomes permitidos do host oficial, com limites de tamanho e timeout.
- O painel atualiza o catálogo em intervalo de cinco minutos, mostra a idade do quadro mais recente e permite percorrer os 12 quadros recentes. As imagens não são arquivadas localmente.
- API autenticada `GET /api/connectors` lista preparação e bloqueios dos conectores conhecidos.
- Foram criados pontos de extensão próprios para SIMEPAR RADAR-PR, SMN/SINARAME-RADAR, INUMET RADAR-UY, Defesa Civil RS ALERTAS-RS e CPTEC/INPE PRODUTO-SATELITE-RADAR.
- Cada conector regional falha fechado com `SourceProfileRequired`; não faz chamadas externas enquanto faltarem contrato técnico e evidência de uso.
- NOAA GOES-19 GLM continua como adaptador de objetos implementado, sem coleta ativa nem validação de arquivo real.

## Fonte de imagem NOAA dentro do StormTrack

Produto exibido: GOES-19 ABI GeoColor Full Disk, JPEG 1808×1808. O backend consulta os nomes recentes no catálogo oficial e faz proxy do quadro selecionado. A interface permite percorrer até 12 imagens recentes, com atualização periódica. Esta conexão é somente visual; não é ingestão ABI estruturada, não produz overlay georreferenciado e não persiste imagens.

A NOAA indica atualização nominal em 10 minutos e atribuição CIRA/NOAA. A própria página NOAA classifica as imagens web como informativas, não para uso operacional ou resposta a emergências. O painel repete essa limitação. Quadros de nuvens não identificam células, risco, rotação ou trajetória validada.

O proxy restringe o host a `cdn.star.nesdis.noaa.gov`, aceita apenas o padrão de nome NOAA para resolução média, limita o catálogo a 8 MiB e a imagem a 5 MiB, usa timeout de 12 s, valida HTTPS, host final e MIME. O índice fica em cache por 60 s; imagens timestamped têm cache privado no cliente. Erros de fonte viram estado de indisponibilidade no painel.

## Outras imagens públicas identificadas

| Fonte | Evidência pública encontrada | Decisão no StormTrack |
|---|---|---|
| SIMEPAR / Radar-PR | A página oficial publica radar e mosaico para PR e áreas vizinhas; imagem recente foi localizada. A página apresenta direitos reservados; termos de automação, retenção e redistribuição ainda não foram estabelecidos. | Conector segue pendente; não copiar automaticamente até fechar perfil e autorização. |
| Defesa Civil RS / radar POA | Página oficial informa quadro a cada 5 minutos e cobertura aproximada de 150 km centrada na região de Porto Alegre. O conteúdo disponível é um painel incorporado; API de imagem direta e permissão de proxy não foram confirmadas. | Preparado, desabilitado; cobertura não substitui o corredor inteiro. |
| CPTEC/INPE | Página oficial publica produtos de satélite/radar, mas sua política limita uso comercial e cópia/reprodução em mídia sem autorização expressa; a disponibilidade também oscilou na consulta. | Preparado, desabilitado até resolver uso do produto específico e endpoint. |
| SMN / SINARAME | Portal oficial de mapas de vigilância foi identificado, mas não respondeu na consulta desta revisão; direitos dos documentos abertos não foram presumidos para imagens operacionais. | Perfil e disponibilidade de produto pendentes. |
| INUMET | Encontrados catálogo de dados abertos, observações e mapas mensais de precipitação; não foi localizado um feed público de imagem de radar em tempo real. | Conector de radar pendente; não apresentar mapa mensal como radar ao vivo. |
| IPMet/UNESP | Visualizador público de radar e animação para área de Bauru/SP; cobertura, endpoint de imagem e regras de uso não foram confirmados. | Candidato futuro, ainda fora dos conectores ativos. |

“Público para visualizar” não demonstra, por si só, autorização para proxy, coleta, arquivo ou redistribuição no StormTrack. Onde a permissão e o contrato de imagem não estão claros, o app não busca nem replica essas imagens. O catálogo documenta a pendência e permite completar a integração sem habilitá-la por engano.

## Contrato mínimo para ativar conectores pendentes

Para cada fonte registrar: endpoint/protocolo; acesso público ou autenticação; formato e esquema; frequência/cobertura; licença/atribuição; política de retenção; autorização separada para acesso, coleta e armazenamento; redistribuição em gate separado; amostra oficial e critérios de validação. Depois, implementar parser isolado e teste de falha, atrasos e duplicatas. Nenhum destes conectores inicia coleta agora.

## Verificação

- Testes unitários: todos os conectores regionais recusam `fetch()` sem perfil; catálogo separa ABI como imagem interna ativa sem arquivo; GLM e fontes regionais continuam desabilitados. Os testes do parser usam índice NOAA simulado, sem rede externa.
- `node --check frontend/app.js` passou.
- `python -m compileall -q backend tests` passou.
- Suíte `unittest`: 43 passaram; cinco testes HTTP são ignorados porque `fastapi`/`httpx` não estão instalados neste ambiente.
- A fonte real NOAA e o fluxo completo em navegador ainda precisam de verificação no ambiente local com acesso à internet.

## Estado honesto ao final

A imagem NOAA ABI aparece dentro do StormTrack via proxy de backend. Não há arquivo ABI local, transformação nem overlay georreferenciado. Nenhum satélite está conectado como cadeia de ingestão e processamento do StormTrack. GLM permanece desconectado. As fontes regionais estão com esqueletos de integração, não conectores funcionais até que seus contratos sejam conhecidos.

Fontes oficiais consultadas:

- [NOAA NESDIS — GOES-19 ABI GeoColor Full Disk](https://www.star.nesdis.noaa.gov/GOES/fulldisk_band.php?band=GEOCOLOR&length=36&sat=G19)
- [NOAA NESDIS — Advanced Baseline Imager](https://www.nesdis.noaa.gov/our-satellites/currently-flying/goes-east-west/advanced-baseline-imager-abi)
