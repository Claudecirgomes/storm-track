/* GLM is displayed exclusively in its own card; collection remains independent. */
(() => {
  const element=id=>document.querySelector(`#${id}`);
  let map=null, points=null, live=true, reference=null, generation=0, data=null;
  let bounds=[-73,-40,-42,-14], fitted=null;
  const format=value=>new Intl.DateTimeFormat('pt-BR',{timeZone:'America/Sao_Paulo',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'}).format(new Date(value));
  function draw() {
    const container=element('lightning-map');
    if (!container.clientWidth || !container.clientHeight || !data) return;
    if (!map) {
      map=L.map(container,{preferCanvas:true,minZoom:3,maxZoom:12,scrollWheelZoom:false,attributionControl:true});
      map.attributionControl.setPrefix('<a href="https://leafletjs.com/">Leaflet</a>');
      L.geoJSON(stormtrackMapBase.countries,{interactive:false,attribution:'Natural Earth · NOAA GOES-19 GLM',style:{color:'#8ea7ac',weight:.7,fillColor:'#153d42',fillOpacity:1}}).addTo(map);
      L.geoJSON(stormtrackMapBase.states,{interactive:false,style:{color:'#8ea7ac',weight:.5,fill:false}}).addTo(map);
    }
    map.invalidateSize({pan:false});
    const key=bounds.join(',');
    if (fitted!==key) {const [w,s,e,n]=bounds;map.fitBounds([[s,w],[n,e]],{padding:[3,3],animate:false});fitted=key;}
    if (points) map.removeLayer(points);
    points=L.geoJSON(data,{pointToLayer:(feature,position)=>L.circleMarker(position,{radius:2,stroke:false,fillColor:new Date(data.end)-new Date(feature.properties.observed_at)<120000?'#ffe260':'#ed5cd6',fillOpacity:.9}),onEachFeature:(feature,layer)=>{
      const info=document.createElement('span');info.textContent=`Flash GLM · ${format(feature.properties.observed_at)} · não identifica impacto no solo`;layer.bindTooltip(info);
    }}).addTo(map);
  }
  async function refresh() {
    if (!state.account) return;
    const request=++generation;
    try {
      let end=reference;
      if (live || !end) {
        const catalog=await api('/api/satellite/regional/catalog');
        if (request!==generation) return;
        end=catalog.products?.find(product=>product.product==='glm')?.latest_observed_end;
        bounds=catalog.bounds||bounds;
      }
      if (!end) throw new Error('Nenhum arquivo GLM coletado ainda.');
      const minutes=Number(element('lightning-window').value)||10;
      const result=await api(`/api/satellite/regional/flashes?end=${encodeURIComponent(end)}&minutes=${minutes}`);
      if (request!==generation || !state.account) return;
      data=result;bounds=result.bounds||bounds;
      element('lightning-summary').textContent=result.state==='unavailable'?'Sem dados GLM neste horário':`${result.count.toLocaleString('pt-BR')} flashes · ${result.state==='complete'?'cobertura completa':`cobertura parcial (${Math.round(result.coverage_fraction*100)}%)`}`;
      element('lightning-status').textContent=`${live?'Ao vivo':'Replay do mapa'} · ${format(result.start)} – ${format(result.end)} · ${live?`último dado há ${Math.max(0,Math.floor((Date.now()-new Date(result.end))/1000))} s`:'janela termina no quadro selecionado'}`;
      element('lightning-status').title=`${result.start} — ${result.end} UTC`;
      draw();
    } catch(error) {
      if (request!==generation) return;
      element('lightning-status').textContent=`GLM indisponível; ${data?'última exibição preservada, sem atualização. ':''}${error.message}`;
    }
  }
  function clear() {
    generation++;data=null;live=true;reference=null;
    if (points && map) map.removeLayer(points);points=null;
    element('lightning-summary').textContent='Aguardando observações';
    element('lightning-status').textContent='Aguardando coleta GLM.';
  }
  function loading() {
    generation++;data=null;
    if (points && map) map.removeLayer(points);points=null;
    element('lightning-summary').textContent='Carregando intervalo GLM…';
    element('lightning-status').textContent='Consultando o horário selecionado.';
  }
  element('lightning-window').onchange=()=>{loading();refresh();};
  element('lightning-refresh').onclick=refresh;
  if (typeof ResizeObserver!=='undefined') new ResizeObserver(()=>{if(data) draw();}).observe(element('lightning-map'));
  window.StormTrackLightning={clear,refresh,setReference(value){
    if (live!==value.live || (!value.live && reference!==value.end)) loading();
    live=value.live;reference=value.end;bounds=value.bounds||bounds;return refresh();
  }};
  setInterval(refresh,10000);
})();
