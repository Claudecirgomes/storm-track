/* Surface MODEL output. Kept separate from GLM, ABI and station observations. */
(() => {
  const get=id=>document.querySelector(`#surface-${id}`);
  const MARINGA=[-23.4205,-51.9386];
  const STOPS=[-5,5,15,25,35,45];
  const COLORS=[[40,80,190],[30,185,225],[80,190,110],[245,215,65],[245,125,45],[205,45,65]];
  let data=null, mini=null, miniLayer=null, mainLayer=null, mainControl=null, mode='combined', expanded=false, live=true, generation=0, pointGeneration=0;
  const attached=new WeakSet();
  const format=value=>value?new Intl.DateTimeFormat('pt-BR',{timeZone:'America/Sao_Paulo',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}).format(new Date(value)):'horário indisponível';
  const value=(number,unit)=>Number.isFinite(number)?`${number.toFixed(1)} ${unit}`:'sem dado';
  function color(temperature) {
    const t=Math.max(STOPS[0],Math.min(STOPS.at(-1),temperature));
    const index=Math.min(STOPS.length-2,Math.max(0,STOPS.findIndex(stop=>stop>t)-1));
    if (t===STOPS.at(-1)) return `rgb(${COLORS.at(-1).join(',')})`;
    const fraction=(t-STOPS[index])/(STOPS[index+1]-STOPS[index]);
    return `rgb(${COLORS[index].map((v,c)=>Math.round(v+(COLORS[index+1][c]-v)*fraction)).join(',')})`;
  }
  function description(feature, response=data) {
    const p=feature.properties,box=document.createElement('div');
    for (const line of [p.location_name||'Superfície — modelo meteorológico',
      `Temperatura a 2 m: ${value(p.temperature_2m,'°C')}`,
      `Vento a 10 m: ${value(p.wind_speed_10m,'km/h')}`,
      `Direção de origem: ${Number.isFinite(p.wind_direction_10m)?p.wind_direction_10m.toFixed(0)+'°':'sem dado'}`,
      `Válido em ${format(p.valid_at)} (Brasília)`,
      'Fonte: Open-Meteo · seleção automática de modelos',
      response?.state==='delayed'?'Dados antigos: atualização da fonte indisponível.':'Saída de modelo; não é medição de estação.']) {
      const row=document.createElement('div');row.textContent=line;box.append(row);
    }
    return box;
  }
  async function point(target,position) {
    const request=++pointGeneration;
    try {
      const response=await api(`/api/weather/surface/point?lat=${position.lat}&lon=${position.lng}`);
      if (request!==pointGeneration || !state.account || (target!==mini && !expanded)) return;
      L.popup().setLatLng(position).setContent(description(response.features[0],response)).openOn(target);
    } catch(error) {if(request===pointGeneration)get('status').textContent=`Consulta por ponto indisponível: ${error.message}`;}
  }
  function attach(target) {
    if (attached.has(target)) return;
    attached.add(target);
    target.on('click',event=>{if(target===mini || expanded) point(target,event.latlng);});
  }
  function ensureMini() {
    const container=get('map');
    if (mini || !container.clientWidth || !container.clientHeight) return mini;
    mini=L.map(container,{preferCanvas:true,minZoom:3,maxZoom:12,scrollWheelZoom:false});
    mini.attributionControl.setPrefix('<a href="https://leafletjs.com/">Leaflet</a>');
    L.geoJSON(stormtrackMapBase.countries,{interactive:false,attribution:'Natural Earth · <a href="https://open-meteo.com/">Open-Meteo</a> (CC BY 4.0)',style:{color:'#8ea7ac',weight:.7,fillColor:'#153d42',fillOpacity:1}}).addTo(mini);
    L.geoJSON(stormtrackMapBase.states,{interactive:false,style:{color:'#8ea7ac',weight:.5,fill:false}}).addTo(mini);
    const [w,s,e,n]=data?.bounds||[-68,-39,-44,-18];
    mini.fitBounds([[s,w],[n,e]],{padding:[3,3],animate:false});attach(mini);
    return mini;
  }
  function layer(target,main=false) {
    const group=L.layerGroup([],{attribution:'<a href="https://open-meteo.com/">Open-Meteo</a> · <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>'});
    let pane='overlayPane';
    if (main) {
      pane='surfaceModel';
      if (!target.getPane(pane)) target.createPane(pane);
      target.getPane(pane).style.zIndex='450';
    }
    for (const feature of data.features) {
      const p=feature.properties,[lon,lat]=feature.geometry.coordinates,position=[lat,lon];
      if (mode!=='wind' && Number.isFinite(p.temperature_2m)) L.circleMarker(position,{pane,radius:9,color:color(p.temperature_2m),weight:1,fillColor:color(p.temperature_2m),fillOpacity:.8,bubblingMouseEvents:false}).bindPopup(description(feature)).addTo(group);
      if (mode!=='temperature' && Number.isFinite(p.wind_speed_10m) && (p.wind_speed_10m===0 || Number.isFinite(p.wind_direction_10m))) {
        const size=Math.max(14,Math.min(32,14+p.wind_speed_10m*.3));
        const angle=((p.wind_direction_10m||0)+180)%360;
        L.marker(position,{pane,icon:L.divIcon({className:'surface-wind',html:`<span style="font-size:${size}px;transform:rotate(${angle}deg)">${p.wind_speed_10m===0?'●':'↑'}</span>`,iconSize:[32,32],iconAnchor:[16,16]}),bubblingMouseEvents:false}).bindPopup(description(feature)).addTo(group);
      }
    }
    const city=data.features.find(f=>f.properties.location_name==='Maringá');
    const marker=L.circleMarker(MARINGA,{pane,radius:5,color:'#fff',weight:2,fillColor:'#ff9c43',fillOpacity:1,bubblingMouseEvents:false}).bindTooltip('Maringá / PR',{permanent:true,direction:'right'});
    if (city) marker.bindPopup(description(city));marker.addTo(group);
    return group.addTo(target);
  }
  function render() {
    if (!data || !state.account) return;
    const target=ensureMini();
    if (target) {target.invalidateSize({pan:false});if(miniLayer)target.removeLayer(miniLayer);miniLayer=layer(target);}
    const main=window.StormTrackMap.instance();
    if (mainLayer && main) main.removeLayer(mainLayer);mainLayer=null;
    if (mainControl) {mainControl.remove();mainControl=null;}
    if (expanded && live && main) {
      attach(main);mainLayer=layer(main,true);
      mainControl=L.control({position:'topright'});
      mainControl.onAdd=()=>{
        const box=document.createElement('div');box.className='surface-main-info';
        const label=document.createElement('span');label.textContent=`MODELO · ${mode==='temperature'?'Temperatura a 2 m':mode==='wind'?'Vento a 10 m':'Temperatura a 2 m + vento a 10 m'} · Open-Meteo`;
        const close=document.createElement('button');close.type='button';close.textContent='Retirar camada';close.onclick=()=>{expanded=false;render();};
        box.append(label,close);L.DomEvent.disableClickPropagation(box);return box;
      };mainControl.addTo(main);
    }
    for (const button of document.querySelectorAll('[data-surface-mode]')) button.setAttribute('aria-pressed',String(button.dataset.surfaceMode===mode));
    get('temperature-legend').hidden=mode==='wind';
    get('wind-legend').hidden=mode==='temperature';
    get('expand').disabled=!live;
    get('expand').textContent=expanded?'Retirar do principal':'Ampliar no mapa principal';
  }
  async function refresh() {
    if (!state.account) return;
    const request=++generation;
    if (!data) get('status').textContent='Consultando o modelo meteorológico…';
    try {
      const result=await api('/api/weather/surface');
      if (request!==generation || !state.account) return;
      data=result;render();
      const times=[...new Set(data.features.map(f=>f.properties.valid_at).filter(Boolean))].sort();
      get('status').textContent=`${data.state==='delayed'?'Modelo atrasado':data.state==='partial'?'Modelo com lacunas':'Modelo disponível'} · válido ${format(times[0])}${times.length>1?' – '+format(times.at(-1)):''} · ${data.complete_points}/${data.requested_points} pontos completos`;
      get('status').title=`Consulta: ${data.fetched_at}; validade: ${times.join(', ')} UTC`;
    } catch(error) {if(request===generation)get('status').textContent=`Modelo indisponível${data?'; último quadro preservado':''}: ${error.message}`;}
  }
  function clear() {
    generation++;pointGeneration++;data=null;expanded=false;live=true;
    if (miniLayer && mini) mini.removeLayer(miniLayer);miniLayer=null;
    const main=window.StormTrackMap.instance();if(mainLayer && main)main.removeLayer(mainLayer);mainLayer=null;
    if(mainControl){mainControl.remove();mainControl=null;}
    get('expand').disabled=true;
    get('timeline-note').hidden=true;
    get('status').textContent='Aguardando consulta ao modelo.';
  }
  for (const button of document.querySelectorAll('[data-surface-mode]')) button.onclick=()=>{mode=button.dataset.surfaceMode;render();};
  get('refresh').onclick=refresh;
  get('expand').onclick=()=>{
    if (!data || !live) {get('status').textContent='Use Último no mapa principal para exibir o modelo atual.';return;}
    expanded=!expanded;render();
    if (expanded) {const [w,s,e,n]=data.bounds;window.StormTrackMap.instance().fitBounds([[s,w],[n,e]]);document.querySelector('.map-panel').scrollIntoView({behavior:'smooth',block:'start'});}
  };
  if (typeof ResizeObserver!=='undefined') new ResizeObserver(()=>{if(data)render();}).observe(get('map'));
  window.StormTrackSurface={refresh,clear,isExpanded:()=>expanded,setTimeline(value){if(live===value.live)return;live=value.live;if(!live)expanded=false;get('timeline-note').hidden=live;render();}};
  setInterval(refresh,300000);refresh();
})();
