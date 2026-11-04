# StormTrack — Incremento 3

## Objetivo

Reorganizar o MVP para refletir o produto de monitoramento apresentado como referência e deixar explícitos os limites da implementação real, incluindo as partes do backend, dados e operação.

## Entregue

- Interface com navegação entre Monitoramento, Fontes e Auditoria.
- Monitoramento vazio e seguro: sem células, coordenadas, trajetórias, previsões, alertas ou avaliação de risco inventados.
- Camadas e cartões de radar, satélite, raios, estações e modelos claramente indicados como desconectados ou pendentes de análise.
- Telas de cadastro e governança de produtos de fonte separadas do monitoramento.
- Auditoria separada e restrita ao perfil Administrador, respeitando a autorização existente no backend.
- Atualização responsiva da interface para telas menores.
- Revisão documentada da estrutura atual, responsabilidades, limites e organização recomendada para os próximos incrementos em `ARQUITETURA_E_ESTRUTURA_INCREMENTO_3.md`.
- README alinhado à interface e aos limites técnicos presentes.

## Fora do incremento

Nenhum endpoint ou coletor meteorológico foi ativado. Não foram conectados provedores, mapa base, scheduler, detector de células, nowcast, risco ou alertas. Não foi feita análise de termos e dados de uma fonte específica. A estrutura persistente de observações continua sendo serviço interno, não uma integração operacional.

## Verificação

- `node --check frontend/app.js`: passou.
- IDs do HTML: únicos; seletores usados pelo JavaScript encontrados.
- `python -m compileall -q backend tests`: passou.
- `python -m unittest discover -s tests`: 19 encontrados; 16 passaram e 3 testes HTTP foram ignorados por ausência das dependências descritas em `requirements.txt`.

## Próximo incremento recomendado

Analisar e aprovar um único produto de fonte. Registrar documentação e termos; definir esquema e regras de qualidade; implementar adaptador isolado e testes com amostras autorizadas; validar proveniência, atrasos, falhas e correções em modo controlado. A conexão do mapa deve vir após haver endpoints de leitura baseados em dados validados.
