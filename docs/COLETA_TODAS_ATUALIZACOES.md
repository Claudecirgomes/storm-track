# Coleta de todas as atualizações das fontes ativas

Atualização de 05/11/2026. Esta operação substitui o comportamento anterior de
capturar somente o último C13 e a pequena janela GLM.

## Iniciar e visualizar

```powershell
.venv\Scripts\python.exe -m backend.app.scripts.start_local
```

Abra http://127.0.0.1:8000 e use Ctrl+F5. O mapa mantém o estilo da referência e
mostra arquivos pendentes e novas tentativas abaixo dos controles. Confira também
o horário efetivo de cada produto; ausência de pendências descobertas não prova
que um coletor parado esteja funcionando. Verificações antigas são indicadas.

## Funcionamento

São iniciados três processos locais independentes, todos com lease SQLite:

| Processo | Fontes continuamente verificadas | Intervalo padrão |
|---|---|---:|
| ABI | ABI-L2-CMIPF C13, Full Disk | 10 s |
| GLM | GLM-L2-LCFA | 10 s |
| Contexto | ABI-L2-DMWF e ABI-L2-RRQPEF | 30 s por produto |

Os outros diagnósticos e RGB mantidos no seletor continuam sob demanda. Isso
preserva o orçamento; não se reativou o catálogo inteiro ou os 16 canais contínuos.
O navegador consulta o catálogo a cada 10 s e reaproveita imagens imutáveis já
carregadas. Raios e vento atualizam independentemente do intervalo do ABI.

Toda chave encontrada na listagem paginada é gravada em `satellite_queue`, no
catálogo SQLite regional, **antes** de avançar o checkpoint. Arquivos concluídos
não são baixados de novo. Cada arquivo novo, inclusive revisão com nova chave de
criação, recebe seu próprio registro. Para novas aquisições, o recibo guarda
SHA-256 dos bytes originais e horário de conclusão. Registros antigos importados
podem não possuir hash e permanecem explicitamente sem esse dado.

Cada lote processa o mais recente e depois os mais antigos pendentes. O mapa
recebe logo o quadro novo e os intermediários são recuperados sem abandoná-los
quando chegam observações mais novas. Não há descarte de um trabalho pendente
por atingir o tamanho do lote: ele permanece na fila persistente.

Falhas individuais têm backoff de 10 s até 5 min; não bloqueiam os demais arquivos.
Se o processo cair, itens ainda pendentes continuam no banco após reiniciar. Um
arquivo já persistido antes da queda é reconhecido na retomada sem novo download.
Somente após escrita e registro o recibo passa para concluído.

A descoberta mantém sobreposição para arquivos atrasados: 30 min para ABI,
15 min para GLM, 120 min para DMW e 60 min para chuva. Há uma varredura mais ampla
na virada de hora desde o início da sessão, limitada à janela de recuperação.
Após interrupção, parte do último checkpoint com sobreposição, até **24 horas**
por padrão. `STORMTRACK_RECOVERY_HOURS` permite de 1 a 168 horas. Uma interrupção
além desse limite é registrada como lacuna que exige importação histórica, sem
anunciar coleta completa daquele intervalo.

As atualizações de contexto também são persistidas: vetores em GeoJSON com tempo,
pressão e qualidade; chuva em NPZ físico com máscara, unidade e PNG. O mapa usa
os dados continuamente coletados quando disponíveis, respeitando o horário de
replay. Fonte sem arquivos permanece indisponível e não produz chuva zero.

## Limites práticos

- É necessária internet e computador ligado, com os processos em execução.
- Verificar a cada 10 s não cria observações ABI entre varreduras, nem elimina
  a latência de publicação, transferência e processamento do produtor.
- A fila registra aquisição; não é um arquivo meteorológico ilimitado. O cache
  de imagens e campos conserva aproximadamente duas horas. Recibos concluídos
  permanecem no catálogo; sessões científicas fixadas ficam fora desse cache.
- O limite existente de 512 MiB do cache e a reserva livre continuam válidos.
  Uma cota atingida deixa trabalhos para nova tentativa e indica erro, em vez de
  apagar estudos ou declarar arquivos concluídos sem processamento.
- Chaves NOAA timestampadas são a identidade de revisão. Alteração de bytes
  silenciosa sob a mesma chave e tamanho não é detectada por re-download periódico.
- Nenhum serviço de inicialização automática do Windows foi instalado e nenhum
  deploy remoto foi realizado.

Logs: `output/stormtrack-collector-abi-error.log`,
`output/stormtrack-collector-glm-error.log` e
`output/stormtrack-collector-context-error.log`.

## Verificação

Testes cobrem persistência após reabrir o banco, prioridades recente/antigo,
repetição idempotente, falha de listagem sem avanço do checkpoint, retry por
arquivo sem bloquear outros, revisões distintas e janela de produto mais lento.
O teste JavaScript verifica reutilização da imagem, avanço de GLM ao vivo e
replay sem observações futuras. A regressão completa passou com 117 testes antes
do último teste adicional da janela DMW; esse teste é executado na verificação
focada posterior.

Evidência real de 20:51:55 UTC (17:51:55 de São Paulo): C13 até 20:49:53 UTC,
GLM até 20:51:20 UTC. A fila continha recibos de três C13, 57 GLM e quatro arquivos
DMW concluídos, com oito arquivos DMW mais antigos ainda pendentes e sem falhas.
Isso confirma entrada de uma nova cena e continuidade de GLM após a ativação,
sem confundir a recuperação de vento com atraso da imagem principal. Não havia
arquivo RRQPEF encontrado na janela consultada; o coletor segue verificando.
