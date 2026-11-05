# Coletor online

O site Vercel lê imagens regionais processadas, raios GLM e ventos/chuva no
schema privado `stormtrack_weather` do PostgreSQL. A função Vercel não executa
um coletor contínuo e não depende do computador local.

O workflow `.github/workflows/weather-collector.yml` executa um lote a cada
cinco minutos, com acionamento manual disponível. O agendador GitHub pode
atrasar ou omitir execuções sob carga. Não há garantia de atualização em dez
segundos, como no coletor local. Em repositórios públicos sem atividade, o
GitHub pode desativar agendamentos após 60 dias.

## Preparação

1. Aplicar `backend/app/core/weather_cloud_schema.sql` com a conta administrativa
   já utilizada pelo projeto. A migração é aditiva e não altera contas/sessões.
2. Criar uma identidade de máquina com acesso somente ao schema meteorológico
   e permissão de tabelas temporárias. Não usar a senha administrativa no Actions.
3. Configurar a conexão dessa identidade no secret GitHub
   `STORMTRACK_CLOUD_DATABASE_URL`. Nunca colocar conexões no código ou logs.
4. Manter `STORMTRACK_COLLECTION_ENABLED=false` na Vercel e a conexão existente
   `STORMTRACK_DATABASE_URL` para a aplicação.
5. Executar manualmente o workflow, confirmar dados no catálogo e publicar o
   site. Sem a migração e o secret, o coletor ainda não está ativado.

O lote restaura checkpoints e pendências, consulta novas publicações NOAA,
processa C13, GLM, DMW e RRQPE e publica o resultado em transação. Recibos de
arquivos concluídos impedem downloads repetidos após a limpeza do cache.
Falhas individuais permanecem na fila para novas tentativas.

O cache online guarda até duas horas e 96 MiB de artefatos processados. Não é
um arquivo histórico completo. A fila conserva recibos concluídos por sete
dias e pendências até processamento. A publicação pausa se o banco ultrapassar
400 MiB; isso preserva margem, mas não substitui o acompanhamento da cota do
provedor. Arquivos NOAA brutos são temporários; dados científicos locais e
contas não são removidos.

O cartão de superfície consulta Open-Meteo sob demanda, com cache PostgreSQL
de quinze minutos, orçamento compartilhado e bloqueio entre instâncias.
Temperatura e vento são estimativas de modelo, não observações de estações.

Acompanhe o horário da observação e a cobertura GLM no painel: ausência de
dados nunca significa ausência de tempestade ou de raios.
