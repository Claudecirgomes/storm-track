# Raios exclusivos no cartão GLM — 05/11/2026

Os pontos GLM foram removidos do mapa central, incluindo o caminho alternativo
de observações armazenadas. O checkbox, a janela e o texto GLM deixaram os
controles centrais. A coleta e os endpoints não foram modificados.

O cartão Raios (GLM) agora contém mapa Leaflet próprio com base local, contagem,
cobertura temporal, horário observado, janela 1/5/10/15 minutos e Atualizar.
Consulta automática a cada 10 segundos, independente do carregamento do satélite.
Ao vivo usa o último GLM; em replay respeita o fim do quadro central. Ao mudar
o horário ou a janela, remove pontos antigos antes de buscar o novo intervalo.
Falha de consulta preserva a informação de erro e não vira contagem zero.

Verificação: seis testes da API passaram; o teste JavaScript passou com mapa
dedicado, zero real com cobertura completa, GLM ausente do mapa central, replay
e cache de imagens. A página e o novo script retornaram HTTP 200 localmente.
Não houve inspeção visual completa no navegador nem alteração do coletor.

Abra http://127.0.0.1:8000 e pressione Ctrl+F5 para carregar os scripts atualizados.
