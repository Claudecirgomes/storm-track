# Matriz GOES — evidência de 05/11/2026

Status de engenharia e de interface são separados. Nenhum item implica validação meteorológica.
Fontes, resoluções e condições adicionais: [relatório](GOES_MULTICAMADAS_IA.md).

| Camada | Fonte / dependências | Unidade | Resolução / condição | Status comprovado |
|---|---|---|---|---|
| C01 Azul visível | ABI-L2-CMIPF C01 | 1 | 1 km nominal no nadir; solar | Implementada; leitura/exportação real reproduzida; acessível sob demanda |
| C02 Vermelho visível | ABI-L2-CMIPF C02 | 1 | 0.5 km nominal no nadir; solar | Implementada; leitura/exportação real reproduzida; acessível sob demanda |
| C03 Vegetação | ABI-L2-CMIPF C03 | 1 | 1 km nominal no nadir; solar | Implementada; leitura/exportação real reproduzida; acessível sob demanda |
| C04 Cirrus | ABI-L2-CMIPF C04 | 1 | 2 km nominal no nadir; solar | Implementada; leitura/exportação real reproduzida; acessível sob demanda |
| C05 Neve/gelo | ABI-L2-CMIPF C05 | 1 | 1 km nominal no nadir; solar | Implementada; leitura/exportação real reproduzida; acessível sob demanda |
| C06 Microfísica | ABI-L2-CMIPF C06 | 1 | 2 km nominal no nadir; solar | Implementada; leitura/exportação real reproduzida; acessível sob demanda |
| C07 IR curto | ABI-L2-CMIPF C07 | K | 2 km nominal no nadir; C07 inclui componente solar | Implementada; leitura/exportação real reproduzida; acessível sob demanda |
| C08 Vapor alto | ABI-L2-CMIPF C08 | K | 2 km nominal no nadir; dia/noite | Implementada; leitura/exportação real reproduzida; acessível sob demanda |
| C09 Vapor médio | ABI-L2-CMIPF C09 | K | 2 km nominal no nadir; dia/noite | Implementada; leitura/exportação real reproduzida; acessível sob demanda |
| C10 Vapor baixo | ABI-L2-CMIPF C10 | K | 2 km nominal no nadir; dia/noite | Implementada; leitura/exportação real reproduzida; acessível sob demanda |
| C11 Fase de nuvem | ABI-L2-CMIPF C11 | K | 2 km nominal no nadir; dia/noite | Implementada; leitura/exportação real reproduzida; acessível sob demanda |
| C12 Ozônio | ABI-L2-CMIPF C12 | K | 2 km nominal no nadir; dia/noite | Implementada; leitura/exportação real reproduzida; acessível sob demanda |
| C13 Janela IR limpa | ABI-L2-CMIPF C13 | K | 2 km nominal no nadir; dia/noite | Implementada; leitura/exportação real reproduzida; acessível sob demanda |
| C14 Janela IR | ABI-L2-CMIPF C14 | K | 2 km nominal no nadir; dia/noite | Implementada; leitura/exportação real reproduzida; acessível sob demanda |
| C15 Janela úmida | ABI-L2-CMIPF C15 | K | 2 km nominal no nadir; dia/noite | Implementada; leitura/exportação real reproduzida; acessível sob demanda |
| C16 CO₂ | ABI-L2-CMIPF C16 | K | 2 km nominal no nadir; dia/noite | Implementada; leitura/exportação real reproduzida; acessível sob demanda |
| Topos frios isolado | C13; mesma observação | °C | Grade EPSG:3857 regional; paralaxe não corrigida | Implementada; PNG real; integração visual completa pendente |
| Topos frios sobre composição | C13; mesma observação | °C | Grade EPSG:3857 regional; paralaxe não corrigida | Implementada; PNG real; integração visual completa pendente |
| C13 cinza | C13; mesma observação | °C | Grade EPSG:3857 regional; paralaxe não corrigida | Implementada; PNG real; integração visual completa pendente |
| C13 térmico anterior | C13; mesma observação | °C | Grade EPSG:3857 regional; paralaxe não corrigida | Implementada; PNG real; integração visual completa pendente |
| split-window | C13 − C15 | K | Mesmo scan, máscara comum | Implementada; entradas reais reproduzidas; exibição final no navegador pendente |
| fog | C13 − C07 | K | Mesmo scan, máscara comum | Implementada; entradas reais reproduzidas; exibição final no navegador pendente |
| phase | C11 − C14 | K | Mesmo scan, máscara comum | Implementada; entradas reais reproduzidas; exibição final no navegador pendente |
| split-vapor | C08 − C10 | K | Mesmo scan, máscara comum | Implementada; entradas reais reproduzidas; exibição final no navegador pendente |
| split-ozone | C12 − C13 | K | Mesmo scan, máscara comum | Implementada; entradas reais reproduzidas; exibição final no navegador pendente |
| vapor-window | C08 − C13 | K | Mesmo scan, máscara comum | Implementada; entradas reais reproduzidas; exibição final no navegador pendente |
| airmass | C08, C10, C12, C13 | RGB, sem unidade física única | any; reflectância bruta quando aplicável | Implementada; preview real gerado; revisão científica pendente |
| night-microphysics | C07, C13, C15 | RGB, sem unidade física única | night; reflectância bruta quando aplicável | Implementada; preview real gerado; revisão científica pendente |
| dust | C11, C13, C14, C15 | RGB, sem unidade física única | any; reflectância bruta quando aplicável | Implementada; preview real gerado; revisão científica pendente |
| ash | C11, C13, C14, C15 | RGB, sem unidade física única | any; reflectância bruta quando aplicável | Implementada; preview real gerado; revisão científica pendente |
| so2 | C09, C10, C11, C13 | RGB, sem unidade física única | any; reflectância bruta quando aplicável | Implementada; preview real gerado; revisão científica pendente |
| day-convection | C02, C05, C07, C08, C10, C13 | RGB, sem unidade física única | day; reflectância bruta quando aplicável | Implementada; preview real gerado; revisão científica pendente |
| day-cloud-type | C02, C04, C05 | RGB, sem unidade física única | day; reflectância bruta quando aplicável | Implementada; preview real gerado; revisão científica pendente |
| fire-temperature | C05, C06, C07 | RGB, sem unidade física única | day; reflectância bruta quando aplicável | Implementada; preview real gerado; revisão científica pendente |
| day-cloud-phase | C02, C05, C13 | RGB, sem unidade física única | day; reflectância bruta quando aplicável | Implementada; preview real gerado; revisão científica pendente |
| simple-vapor | C08, C10, C13 | RGB, sem unidade física única | any; reflectância bruta quando aplicável | Implementada; preview real gerado; revisão científica pendente |
| differential-vapor | C08, C10 | RGB, sem unidade física única | any; reflectância bruta quando aplicável | Implementada; preview real gerado; revisão científica pendente |
| day-cloud-convection | C02, C13 | RGB, sem unidade física única | day; reflectância bruta quando aplicável | Implementada; preview real gerado; revisão científica pendente |
| day-land-cloud | C02, C03, C05 | RGB, sem unidade física única | day; reflectância bruta quando aplicável | Implementada; preview real gerado; revisão científica pendente |
| day-land-cloud-fire | C02, C03, C06 | RGB, sem unidade física única | day; reflectância bruta quando aplicável | Implementada; preview real gerado; revisão científica pendente |
| day-snow-fog | C03, C05, C07, C13 | RGB, sem unidade física única | day; reflectância bruta quando aplicável | Implementada; preview real gerado; revisão científica pendente |
| true-color | C01, C02, C03 | RGB, sem unidade física única | day; reflectância bruta quando aplicável | Implementada; preview real gerado; revisão científica pendente |
| ACMF | ABI-L2-ACMF | None | [5424, 5424] nativa; nearest para exibição | Adaptador implementado e lido com dado real; controles de mapa adicionados, QA visual pendente |
| ACHAF | ABI-L2-ACHAF | m | [1086, 1086] nativa; nearest para exibição | Adaptador implementado e lido com dado real; controles de mapa adicionados, QA visual pendente |
| ACHTF | ABI-L2-ACHTF | K | [5424, 5424] nativa; nearest para exibição | Adaptador implementado e lido com dado real; controles de mapa adicionados, QA visual pendente |
| CTPF | ABI-L2-CTPF | hPa | [1086, 1086] nativa; nearest para exibição | Adaptador implementado e lido com dado real; controles de mapa adicionados, QA visual pendente |
| ACTPF | ABI-L2-ACTPF | 1 | [5424, 5424] nativa; nearest para exibição | Adaptador implementado e lido com dado real; controles de mapa adicionados, QA visual pendente |
| CODF | ABI-L2-CODF | 1 | [2712, 2712] nativa; nearest para exibição | Adaptador implementado e lido com dado real; controles de mapa adicionados, QA visual pendente |
| CPSF | ABI-L2-CPSF | um | [5424, 5424] nativa; nearest para exibição | Adaptador implementado e lido com dado real; controles de mapa adicionados, QA visual pendente |
| TPWF | ABI-L2-TPWF | mm | [1086, 1086] nativa; nearest para exibição | Adaptador implementado e lido com dado real; controles de mapa adicionados, QA visual pendente |
| DSIF | ABI-L2-DSIF | J kg-1 | [1086, 1086] nativa; nearest para exibição | Adaptador implementado e lido com dado real; controles de mapa adicionados, QA visual pendente |
| LVTPF | ABI-L2-LVTPF | K | grade/pressões nativas, consulta por ponto | Leitor de perfil implementado, 101 níveis reais; mapa/seletor pendentes |
| LVMPF | ABI-L2-LVMPF | percent | grade/pressões nativas, consulta por ponto | Leitor de perfil implementado, 101 níveis reais; mapa/seletor pendentes |
| DMWF | ABI-L2-DMWF | m s-1; hPa; degree | vetores nativos; não vento de superfície | Leitor e GeoJSON reais, qualidade/pressão/tempo filtrados; mapa pendente |
| DMWVF | ABI-L2-DMWVF | m s-1; hPa; degree | vetores nativos; não vento de superfície | Leitor e GeoJSON reais, qualidade/pressão/tempo filtrados; mapa pendente |
| RRQPEF | ABI-L2-RRQPEF | não verificada | não verificada | Sem objetos na janela real consultada; disponibilidade histórica não concluída |
| ADPF | ABI-L2-ADPF | 1 | [5424, 5424] nativa; nearest para exibição | Adaptador implementado e lido com dado real; controles de mapa adicionados, QA visual pendente |
| AODF | ABI-L2-AODF | 1 | [5424, 5424] nativa; nearest para exibição | Adaptador implementado e lido com dado real; controles de mapa adicionados, QA visual pendente |
| FDCF | ABI-L2-FDCF | 1 | [5424, 5424] nativa; nearest para exibição | Adaptador implementado e lido com dado real; controles de mapa adicionados, QA visual pendente |
| LSTF | ABI-L2-LSTF | K | [1086, 1086] nativa; nearest para exibição | Adaptador implementado e lido com dado real; controles de mapa adicionados, QA visual pendente |
| GFLSF | ABI-L2-GFLSF | não verificada | não verificada | Sem objetos na janela real consultada; disponibilidade histórica não concluída |
| VAAF | ABI-L2-VAAF | não verificada | não verificada | Sem objetos na janela real consultada; disponibilidade histórica não concluída |
| DSRF | ABI-L2-DSRF | W m-2 | [5424, 5424] nativa; nearest para exibição | Adaptador implementado e lido com dado real; controles de mapa adicionados, QA visual pendente |
| RSRF | ABI-L2-RSRF | W m-2 | [5424, 5424] nativa; nearest para exibição | Adaptador implementado e lido com dado real; controles de mapa adicionados, QA visual pendente |
| SSTF | ABI-L2-SSTF | não verificada | não verificada | Sem objetos na janela real consultada; disponibilidade histórica não concluída |
| GLM flashes / taxa | GLM-L2-LCFA | flashes; flashes/min | Janelas 1/5/10/15 min | Coletor existente reutilizado; deduplicação entre arquivos ainda pendente |
| GLM FED / MFA / AFA / TOE de extensão | Eventos/footprints requeridos | não definida sem método | Sem footprint arbitrário | Não implementada; validar método de extensão antes de habilitar |

ABI Full Disk tem cadência nominal de 10 min; o inventário real registra objetos em uma hora.
As cadências e latências específicas de todos os L2 ainda não foram medidas; não são copiadas do C13.
A grade de saída regional não altera a resolução física. Valores nominais de canal são no nadir.
