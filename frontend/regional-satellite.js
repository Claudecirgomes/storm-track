/* Authenticated, bounded regional loop; collection is owned by the CLI worker. */
(() => {
  let frames = [], selected = null, latest = true, playing = false, busy = false, legacyPalette=null;
  let image = null, tops = null, windLayer=null, generation = 0, urls = [], imageNames=[];
  const panel = document.querySelector('.map-panel');
  const controls = document.createElement('div');
  controls.className = 'regional-controls';
  controls.innerHTML = `<div class="regional-row">
    <label>Produto <select id="regional-product"><option value="reference" selected>Referência — terreno + nuvens realçadas</option><option value="c13">C13 infravermelho</option><option value="rgb">RGB diurno / IR noturno</option><option value="combined">Estilo anterior — RGB + topos frios</option></select></label>
    <label><input id="regional-winds" type="checkbox"> Ventos em altitude</label>
    <label>Opacidade <input id="regional-opacity" type="range" min="0" max="1" step=".05" value=".85"></label>
    <button type="button" id="regional-pr">Paraná</button><button type="button" id="regional-expand" aria-expanded="false">Ampliar mapa</button></div>
    <div class="regional-row"><button type="button" id="regional-prev" aria-label="Quadro anterior">◀</button><button type="button" id="regional-play">Reproduzir</button>
    <input id="regional-time" type="range" min="0" max="0" value="0" aria-label="Horário observado" disabled>
    <button type="button" id="regional-next" aria-label="Próximo quadro">▶</button><button type="button" id="regional-live">Último</button></div>
    <div id="regional-legend">Temperatura de brilho — C13 (°C)<div class="regional-gradient"></div><div class="regional-ticks"><span>−90</span><span>−70</span><span>−50</span><span>−30</span><span>40</span></div></div>
    <p id="regional-status" role="status">Carregando catálogo regional…</p><p id="regional-queue-status"></p><p id="regional-wind-status"></p>
    <small>Nuvens: NOAA GOES-19 · Terreno: NASA, base estática de 2004 · Topos frios não confirmam supercélulas. Horários: America/Sao_Paulo; UTC ao passar sobre o horário.</small>`;
  panel.querySelector('.observation-map-shell').after(controls);
  const get = id => controls.querySelector(`#regional-${id}`);
  const monitoredProducts=new Set(['reference','c13','rgb','combined','tops','gray','true-color','day-cloud-phase','day-convection','night-microphysics','airmass','simple-vapor','abi08','abi09','abi10','l2-achaf','l2-actpf','l2-rrqpef']);
  for (const [label,items] of [
    ['Convecção e topos',[['tops','Topos frios — C13 realçado'],['gray','C13 em tons de cinza'],['l2-achaf','Altura do topo'],['l2-actpf','Fase do topo']]],
    ['Estrutura das nuvens',[['true-color','Textura diurna — True Color'],['day-cloud-phase','Fase de nuvens (dia)'],['day-convection','Convecção (dia)'],['night-microphysics','Microfísica (noite)']]],
    ['Ambiente da tempestade',[['airmass','Massas de ar'],['simple-vapor','Vapor de água RGB'],['abi08','Vapor de água — níveis altos'],['abi09','Vapor de água — níveis médios'],['abi10','Vapor de água — níveis baixos']]],
    ['Chuva',[['l2-rrqpef','Taxa de chuva estimada por satélite']]]]) {
    const group=document.createElement('optgroup');group.label=label;
    for (const [value,label] of items) {const option=document.createElement('option');option.value=value;option.textContent=label;group.append(option);}
    get('product').append(group);
  }
  const tools=document.createElement('div');tools.className='regional-row';
  tools.innerHTML='<label>Buscar camada <input id="regional-search" type="search" placeholder="Canal, RGB ou produto"></label><button type="button" id="regional-favorite">☆ Favoritar</button><label><input type="checkbox" id="regional-only-favorites"> Favoritos</label><button type="button" id="regional-maringa">Maringá</button><button type="button" id="regional-sul">Sul</button><button type="button" id="regional-corredor">Corredor</button>';
  get('product').after(tools);
  function filterProducts() {
    let favorites=[];
    try {favorites=JSON.parse(localStorage.getItem('stormtrack-layer-favorites')||'[]');} catch (_) {}
    for (const option of get('product').querySelectorAll('option')) {
      option.hidden=!option.textContent.toLocaleLowerCase('pt-BR').includes(get('search').value.toLocaleLowerCase('pt-BR')) || (get('only-favorites').checked && !favorites.includes(option.value));
    }
  }
  get('search').oninput=filterProducts;get('only-favorites').onchange=filterProducts;
  get('favorite').onclick=()=>{
    try {const favorites=JSON.parse(localStorage.getItem('stormtrack-layer-favorites')||'[]'),value=get('product').value;
      localStorage.setItem('stormtrack-layer-favorites',JSON.stringify(favorites.includes(value)?favorites.filter(id=>id!==value):[...favorites,value]));filterProducts();
    } catch (_) {get('status').textContent='Preferências locais indisponíveis neste navegador.';}
  };
  for (const [id,bounds] of [['maringa',[[-23.65,-52.2],[-23.1,-51.6]]],['sul',[[-34,-58],[-22,-48]]],['corredor',[[-36,-73],[-18,-42]]]]) get(id).onclick=()=>window.StormTrackMap.instance()?.fitBounds(bounds);
  try {
    const saved = localStorage.getItem('stormtrack-satellite-product');
    if (monitoredProducts.has(saved)) get('product').value=saved;
  } catch (_) { /* Local storage can be disabled; selection still works. */ }
  function expand(active) {
    panel.classList.toggle('regional-expanded',active);
    get('expand').textContent = active ? 'Restaurar mapa' : 'Ampliar mapa';
    get('expand').setAttribute('aria-expanded',String(active));
    window.StormTrackMap.resize();
  }
  get('expand').onclick = () => expand(!panel.classList.contains('regional-expanded'));
  document.addEventListener('keydown',event => {if (event.key === 'Escape' && panel.classList.contains('regional-expanded')) expand(false);});
  function updatePalette(palette) {
    if (!palette?.values?.length || palette.values.length !== palette.colors?.length) return;
    const min = palette.values[0], max = palette.values.at(-1);
    const stops = palette.values.map((value,index) => {
      const color = palette.colors[index];
      return `rgb(${color.join(',')}) ${(value-min)/(max-min)*100}%`;
    });
    controls.querySelector('.regional-gradient').style.background = `linear-gradient(to right,${stops.join(',')})`;
    const ticks=controls.querySelectorAll?.('.regional-ticks span');
    if (ticks) Array.from(ticks).forEach((tick,index)=>{
      const value=palette.values[Math.round(index*(palette.values.length-1)/4)];
      tick.textContent=String(value);tick.style.left=`${(value-min)/(max-min)*100}%`;tick.style.right='auto';
    });
  }
  const format = value => new Intl.DateTimeFormat('pt-BR',{timeZone:'America/Sao_Paulo',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'}).format(new Date(value));
  function clear() {
    if (panel.classList.contains('regional-expanded')) expand(false);
    window.StormTrackLightning?.clear();
    generation++;
    const map = window.StormTrackMap.instance();
    for (const layer of [image,tops,windLayer]) if (layer && map) map.removeLayer(layer);
    image = tops = null;
    windLayer=null;
    urls.forEach(url => URL.revokeObjectURL(url)); urls = [];
    imageNames=[];
    frames = []; selected = null; playing = false;
    get('play').textContent = 'Reproduzir';
    panel.classList.remove('regional-active');
    window.StormTrackMap.regional(false);
  }
  async function loadImage(name) {
    const response = await fetch(`/api/satellite/regional/image/${name}`,{headers:authHeaders()});
    if (!response.ok) throw new Error(`Imagem indisponível (${response.status})`);
    const url = URL.createObjectURL(await response.blob());
    try {
      const preload = new Image(); preload.src = url; await preload.decode();
      return url;
    } catch (error) { URL.revokeObjectURL(url); throw error; }
  }
  async function draw() {
    const frame = frames.find(f => f.id === selected);
    const map = window.StormTrackMap.instance();
    if (!frame || !map) return;
    window.StormTrackLightning?.setReference({end:frame.end,live:latest,bounds:frame.bounds});
    window.StormTrackSurface?.setTimeline({live:latest,end:frame.end});
    const request = ++generation, product = get('product').value;
    let effective=null;
    if (['c13','rgb','combined'].includes(product)) {
      if (legacyPalette) updatePalette(legacyPalette);
      if (get('legend').firstChild) get('legend').firstChild.textContent='Temperatura de brilho — C13 (°C)';
      controls.querySelector('.regional-gradient').hidden=false;
      controls.querySelector('.regional-ticks').hidden=false;
    }
    let names = product === 'combined' ? [frame.images.rgb,frame.images.enhancement] : [frame.images[product]];
    if (!['c13','rgb','combined'].includes(product)) {
      get('status').textContent = 'Preparando camada física; a primeira consulta pode baixar dados NOAA…';
      try {
        const prepared = await api(`/api/satellite/regional/layer/${frame.id}/${product}`,{method:'POST'});
        effective=prepared;
        if (request !== generation) return;
        names = product === 'tops-overlay' ? [frame.images.rgb,prepared.image] : [prepared.image];
        if (prepared.palette) updatePalette(prepared.palette);
        get('legend').firstChild.textContent = prepared.palette || product==='gray' ? 'Temperatura de brilho — C13 (°C)' : product==='l2-acmf' ? '0 limpo · 1 provavelmente limpo · 2 provavelmente nublado · 3 nublado' : prepared.unit==='RGB' ? `${product} · composição RGB; consulte canais para valores físicos` : `${product} · ${prepared.unit} · escala ${prepared.range.join(' a ')}`;
        if (prepared.categories && Object.keys(prepared.categories).length) get('legend').firstChild.textContent=Object.entries(prepared.categories).slice(0,6).map(([code,label])=>`${code}: ${label}`).join(' · ')+(Object.keys(prepared.categories).length>6?' · consulte o código por clique':'');
        get('status').title = `Observação da camada: ${prepared.start} — ${prepared.end}`;
        if (!prepared.palette) controls.querySelector('.regional-gradient').style.background=product==='l2-acmf'?'linear-gradient(to right,rgb(20,30,60) 0% 25%,rgb(80,110,140) 25% 50%,rgb(180,190,200) 50% 75%,white 75% 100%)':'linear-gradient(to right,black,white)';
        if (prepared.category_colors && Object.keys(prepared.categories||{}).length) {
          const count=Math.min(6,Object.keys(prepared.categories).length);
          controls.querySelector('.regional-gradient').style.background=`linear-gradient(to right,${prepared.category_colors.slice(0,count).map((color,i)=>`rgb(${color.join(',')}) ${i/count*100}% ${(i+1)/count*100}%`).join(',')})`;
        }
        controls.querySelector('.regional-ticks').hidden=!prepared.palette;
        controls.querySelector('.regional-gradient').hidden=prepared.unit==='RGB';
      } catch (error) {
        if (request === generation) get('status').textContent=`Camada indisponível: ${error.message}`;
        return;
      }
    }
    get('legend').hidden = product === 'rgb';
    if (names.some(name => !name)) {
      get('status').textContent = 'Composição indisponível neste horário; selecione C13.';
      // Never leave a previous frame masquerading as the selected observation.
      for (const layer of [image,tops]) if (layer) map.removeLayer(layer);
      return;
    }
    const reuse=names.length===imageNames.length && names.every((name,index)=>name===imageNames[index]) && urls.length===names.length;
    const fresh = reuse?[...urls]:[];
    try {
      if (!reuse) for (const name of names) fresh.push(await loadImage(name));
      const windData=get('winds').checked ? await api(`/api/satellite/regional/winds?end=${encodeURIComponent(latest?new Date().toISOString():frame.end)}`).catch(()=>({features:[],state:'unavailable'})) : null;
      if (request !== generation || !state.account) { if(!reuse) fresh.forEach(URL.revokeObjectURL); return; }
      const [west,south,east,north] = frame.bounds;
      const options = {pane:'satellite',opacity:Number(get('opacity').value),interactive:false};
      const next = L.imageOverlay(fresh[0],[[south,west],[north,east]],options).addTo(map);
      const extra = fresh[1] ? L.imageOverlay(fresh[1],[[south,west],[north,east]],options).addTo(map) : null;
      for (const layer of [image,tops,windLayer]) if (layer) map.removeLayer(layer);
      if (!reuse) {urls.forEach(URL.revokeObjectURL);urls=fresh;imageNames=[...names];}
      image = next; tops = extra;
      windLayer=null;
      if (windData?.state==='available') {
        const features=windData.features.filter((_,index)=>index%Math.max(1,Math.ceil(windData.features.length/400))===0);
        windLayer=L.geoJSON({...windData,features},{pointToLayer:(feature,position)=>L.marker(position,{icon:L.divIcon({className:'wind-vector',html:`<span style="transform:rotate(${(feature.properties.direction+180)%360}deg)">↑</span>`,iconSize:[20,20],iconAnchor:[10,10]})}),onEachFeature:(feature,layer)=>{
          const info=document.createElement('span');info.textContent=`Vento em altitude: ${feature.properties.speed.toFixed(1)} m/s · ${feature.properties.pressure.toFixed(0)} hPa · ${format(feature.properties.observed)} · DQF 0`;layer.bindTooltip(info);
        }}).addTo(map);
      }
      get('wind-status').textContent=!windData?'Ventos em altitude: ative para consultar; não são vento de superfície.':windData.state==='available'?`Ventos em altitude · ${format(windData.start)} – ${format(windData.end)} · ${windData.features.length} vetores válidos; exibição amostrada · NOAA DMW`:'Ventos em altitude: fonte indisponível neste horário.';
      panel.classList.add('regional-active');
      window.StormTrackMap.regional(true);
      const age = Math.max(0,Math.floor((Date.now()-new Date(frame.end))/60000));
      const badge=document.querySelector('#map-state');
      if (badge) {badge.textContent=latest?(age*60>(frame.stale_seconds||1800)?'Satélite atrasado':'Satélite atualizado'):'Satélite · replay';badge.className=`status-pill ${latest && age*60<=(frame.stale_seconds||1800)?'status-ok':'status-muted'}`;}
      get('status').textContent = `${latest ? (frame.state==='delayed' || age*60>(frame.stale_seconds||1800)?'Atrasado':'Atualizado') : 'Histórico / replay'} · NOAA · ${format(frame.start)} – ${format(frame.end)} · idade ${age} min`;
      get('status').title = `${frame.start} — ${frame.end} UTC`;
      if (['rgb','combined'].includes(product) && frame.composite_status==='ir_only') get('status').textContent+=` · ${frame.composite_label}`;
      if (effective) get('status').textContent+=` · camada ${format(effective.start)} – ${format(effective.end)} · ${effective.status==='available'?'disponível':'não aplicável / sem pixels válidos'}`;
      get('time').value = frames.findIndex(f=>f.id===selected);
    } catch (error) {
      if (!reuse) fresh.forEach(URL.revokeObjectURL);
      if (request === generation) get('status').textContent = `Falha de atualização; último quadro preservado e atrasado. ${error.message}`;
    }
  }
  async function refresh() {
    if (!state.account || busy) return;
    busy = true;
    try {
      const data = await api('/api/satellite/regional/catalog');
      legacyPalette=data.palette;
      updatePalette(data.palette);
      if (data.enabled === false) {clear();get('status').textContent='Integração regional desativada neste servidor.';return;}
      frames = data.frames;
      if (data.supported_layers) {
        for (const option of Array.from(get('product').options||[])) option.hidden=option.disabled=!data.supported_layers.includes(option.value);
        if (!data.supported_layers.includes(get('product').value)) get('product').value='reference';
      }
      const queueSources=data.products||[];
      const pending=queueSources.reduce((sum,source)=>sum+(source.queue?.pending||0),0);
      const retrying=queueSources.reduce((sum,source)=>sum+(source.queue?.retrying||0),0);
      get('queue-status').textContent=pending?`Coleta contínua · ${pending} arquivos aguardando processamento${retrying?`; ${retrying} em nova tentativa`:''}`:'Coleta contínua · sem arquivos pendentes descobertos';
      const staleChecks=queueSources.filter(source=>source.discovered_at && Date.now()-new Date(source.discovered_at)>120000);
      if (staleChecks.length) get('queue-status').textContent+=' · verificação das fontes atrasada';
      if (!queueSources.some(source=>source.discovered_at)) get('queue-status').textContent='Aguardando confirmação da coleta contínua';
      if (queueSources.some(source=>source.recovery_gap)) get('queue-status').textContent+=' · existe um intervalo antigo que exige importação histórica';
      get('time').max = Math.max(0,frames.length-1); get('time').disabled = !frames.length;
      if (latest && frames.length) selected = frames.at(-1).id;
      if (!frames.length) get('status').textContent = 'Indisponível · sem quadros processados. Inicie o coletor local.';
      else if (frames.some(f=>f.id===selected)) await draw();
      else get('status').textContent = 'Replay fora da retenção; use Último para voltar.';
    } catch (error) { get('status').textContent = `Fonte indisponível; último quadro preservado e atrasado. ${error.message}`; }
    finally { busy = false; }
  }
  function step(delta) {
    if (!frames.length) return;
    latest = false;
    const index = frames.findIndex(f=>f.id===selected);
    selected = frames[Math.max(0,Math.min(frames.length-1,index+delta))].id; draw();
  }
  get('prev').onclick = () => step(-1); get('next').onclick = () => step(1);
  get('time').oninput = () => {latest=false;playing=false;get('play').textContent='Reproduzir';selected=frames[Number(get('time').value)]?.id;draw();};
  get('play').onclick = () => {playing=!playing;latest=false;get('play').textContent=playing?'Pausar':'Reproduzir';};
  get('live').onclick = () => {latest=true;playing=false;get('play').textContent='Reproduzir';refresh();};
  get('product').onchange = () => {
    try {localStorage.setItem('stormtrack-satellite-product',get('product').value);} catch (_) {}
    draw();
  };
  get('opacity').oninput = () => {for (const layer of [image,tops]) layer?.setOpacity(Number(get('opacity').value));};
  get('winds').onchange=()=>draw();
  get('pr').onclick = () => window.StormTrackMap.instance()?.fitBounds([[-26.8,-54.7],[-22.4,-48]]);
  document.querySelector('#map-region').textContent = 'Corredor';
  setInterval(async()=>{if(playing && state.account && !busy && frames.length){busy=true;try{const index=frames.findIndex(f=>f.id===selected);selected=frames[(index+1)%frames.length]?.id;await draw();}finally{busy=false;}}},1800);
  setInterval(refresh,10000);
  window.StormTrackRegional={refresh,clear};
  const queryMap=window.StormTrackMap.instance();
  queryMap?.on('click',async event=>{
    if (window.StormTrackSurface?.isExpanded()) return;
    const product=get('product').value;
    if (['c13','rgb','combined'].includes(product) || !selected) return;
    const scene=selected;
    try {
      const data=await api(`/api/satellite/regional/sample/${scene}/${product}?lon=${event.latlng.lng}&lat=${event.latlng.lat}`);
      if (scene!==selected || product!==get('product').value) return;
      const content=document.createElement('div');
      content.textContent=`${product} · ${data.value===null?'sem dado válido':data.value.toFixed(2)+' '+data.unit} ${data.category||''} · ${data.quality} · ${format(data.end)} · NOAA GOES-19`;
      L.popup().setLatLng(event.latlng).setContent(content).openOn(queryMap);
    } catch (_) {get('status').textContent='Consulta numérica indisponível neste ponto.';}
  });
})();
