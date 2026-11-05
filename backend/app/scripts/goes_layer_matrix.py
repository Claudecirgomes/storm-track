"""Generate an evidence-aware layer matrix; catalog entries are not completion."""
import json
from pathlib import Path

from backend.app.adapters import goes_layers as layers
from backend.app.adapters.goes_products import VARIABLES


def main():
    inventory=json.loads(Path('output/goes-inventory.json').read_text())
    inspected=json.loads(Path('output/goes-products-real.json').read_text())
    byproduct={r['product']:r for r in inspected}
    full=json.loads(Path('output/goes-research-all16/manifest.json').read_text())
    channels={s['channel'] for sample in full['samples'] for s in sample['sources']}
    lines=['# Matriz GOES — evidência de 05/11/2026','',
           'Status de engenharia e de interface são separados. Nenhum item implica validação meteorológica.',
           'Fontes, resoluções e condições adicionais: [relatório](GOES_MULTICAMADAS_IA.md).','',
           '| Camada | Fonte / dependências | Unidade | Resolução / condição | Status comprovado |',
           '|---|---|---|---|---|']
    for c in range(1,17):
        nominal=.5 if c==2 else 1 if c in (1,3,5) else 2
        lines.append(f'| C{c:02d} {layers.NAMES[c-1]} | ABI-L2-CMIPF C{c:02d} | {"1" if c<=6 else "K"} | {nominal} km nominal no nadir; '+
                     ('solar' if c<=6 else 'C07 inclui componente solar' if c==7 else 'dia/noite')+
                     f' | {"Implementada; leitura/exportação real reproduzida" if c in channels else "Teste real pendente"}; acessível sob demanda |')
    for name in ('Topos frios isolado','Topos frios sobre composição','C13 cinza','C13 térmico anterior'):
        lines.append(f'| {name} | C13; mesma observação | °C | Grade EPSG:3857 regional; paralaxe não corrigida | Implementada; PNG real; integração visual completa pendente |')
    for name,(a,b) in layers.DIFFERENCES.items():
        lines.append(f'| {name} | C{a:02d} − C{b:02d} | K | Mesmo scan, máscara comum | Implementada; entradas reais reproduzidas; exibição final no navegador pendente |')
    for name,recipe in layers.RGB.items():
        deps=', '.join(f'C{c:02d}' for c in layers.dependencies(name))
        lines.append(f'| {name} | {deps} | RGB, sem unidade física única | {recipe[-1]}; reflectância bruta quando aplicável | Implementada; preview real gerado; revisão científica pendente |')
    for entry in inventory['products']:
        code=entry['product'].removeprefix('ABI-L2-')
        if code in ('CMIPF','GLM-L2-LCFA'):
            continue
        actual=byproduct.get(code)
        if not entry.get('sample'):
            status='Sem objetos na janela real consultada; disponibilidade histórica não concluída'
            units='não verificada';resolution='não verificada'
        elif code in ('LVTPF','LVMPF'):
            status='Leitor de perfil implementado, 101 níveis reais; mapa/seletor pendentes'
            units='K' if code=='LVTPF' else 'percent';resolution='grade/pressões nativas, consulta por ponto'
        elif code in ('DMWF','DMWVF'):
            status='Leitor e GeoJSON reais, qualidade/pressão/tempo filtrados; mapa pendente'
            units='m s-1; hPa; degree';resolution='vetores nativos; não vento de superfície'
        elif actual and actual['adapter']=='real_read_passed':
            decoded=actual['decoded'];units=str(decoded['units'])
            status='Adaptador implementado e lido com dado real; controles de mapa adicionados, QA visual pendente'
            resolution=str(actual['metadata']['variables'][decoded['variable']]['shape'])+' nativa; nearest para exibição'
        else:
            status='Dependência bloqueada: '+str(actual.get('error') if actual else 'inspeção ausente')
            units='não verificada';resolution='não verificada'
        lines.append(f'| {code} | {entry["product"]} | {units} | {resolution} | {status} |')
    lines.extend(['| GLM flashes / taxa | GLM-L2-LCFA | flashes; flashes/min | Janelas 1/5/10/15 min | Coletor existente reutilizado; deduplicação entre arquivos ainda pendente |',
                  '| GLM FED / MFA / AFA / TOE de extensão | Eventos/footprints requeridos | não definida sem método | Sem footprint arbitrário | Não implementada; validar método de extensão antes de habilitar |',
                  '', 'ABI Full Disk tem cadência nominal de 10 min; o inventário real registra objetos em uma hora.',
                  'As cadências e latências específicas de todos os L2 ainda não foram medidas; não são copiadas do C13.',
                  'A grade de saída regional não altera a resolução física. Valores nominais de canal são no nadir.'])
    Path('docs/GOES_MATRIZ_CAMADAS.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


if __name__=='__main__':
    main()
