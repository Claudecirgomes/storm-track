/* Local geometry and Leaflet are bundled; only detailed basemap tiles use the network. */
(() => {
  const regionBounds = [[-36, -73], [-18, -42]];
  const maringa = [-23.4205, -51.9386];
  let map = null;
  let observations = [];
  let observationLayer = null;
  let detailedLayer = null;
  let terrainLayer = null;
  let baseMode = "local";
  let resizeObserver = null;
  let loadedTiles = 0;
  let failedTiles = 0;
  let failedBatches = 0;
  let tileTimer = null;
  let regionalMode = false;

  function validObservations(collection) {
    return (Array.isArray(collection?.features) ? collection.features : []).filter(feature => {
      const coordinates = feature?.geometry?.coordinates;
      return feature?.geometry?.type === "Point" && Array.isArray(coordinates)
        && coordinates.length >= 2 && typeof coordinates[0] === "number"
        && typeof coordinates[1] === "number" && Number.isFinite(coordinates[0])
        && Number.isFinite(coordinates[1]) && Math.abs(coordinates[0]) <= 180
        && Math.abs(coordinates[1]) <= 90;
    });
  }

  function baseStatus(text) {
    document.querySelector("#map-base-status").textContent = text;
  }

  function armTileFallback() {
    clearTimeout(tileTimer);
    tileTimer = setTimeout(() => {
      if (baseMode === "detailed" && (loadedTiles === 0 || detailedLayer.isLoading())) {
        setBase("local", "Mapa detalhado indispon\u00edvel. Base local ativa; tente novamente no seletor.");
      }
    }, 12000);
  }

  function setBase(mode, message = "") {
    if (!map) return;
    baseMode = mode;
    clearTimeout(tileTimer);
    if (terrainLayer && map.hasLayer(terrainLayer)) map.removeLayer(terrainLayer);
    if (mode === 'terrain') {
      if (map.hasLayer(detailedLayer)) map.removeLayer(detailedLayer);
      document.querySelector('#map-base-select').value='terrain';
      terrainLayer.addTo(map);
      baseStatus('Terreno NASA Blue Marble · base estática de agosto/2004; nuvens NOAA são observações separadas.');
      return;
    }
    if (mode === "detailed") {
      failedBatches = 0;
      loadedTiles = 0;
      document.querySelector("#map-base-select").value = "detailed";
      baseStatus("Carregando mapa detalhado...");
      if (!map.hasLayer(detailedLayer)) detailedLayer.addTo(map);
      armTileFallback();
    } else {
      if (map.hasLayer(detailedLayer)) map.removeLayer(detailedLayer);
      document.querySelector("#map-base-select").value = "local";
      baseStatus(message || "Base local ativa · limites simplificados, sem cidades e ruas detalhadas.");
    }
  }

  function drawObservations() {
    // Lightning is exclusive to its dedicated GLM card, including fallback mode.
    if (observationLayer) observationLayer.clearLayers();
  }

  function ensureMap() {
    const container = document.querySelector("#observations-map");
    if (map || !container || !container.clientWidth || !container.clientHeight) return map;
    map = L.map(container, {
      minZoom: 3, maxZoom: 18, zoomSnap: .25, zoomDelta: .5,
      scrollWheelZoom: true, touchZoom: true, dragging: true, keyboard: true,
      preferCanvas: true,
    });
    // Keep the Leaflet credit, without the flag SVG in its default prefix.
    map.attributionControl.setPrefix('<a href="https://leafletjs.com/" title="Biblioteca de mapas interativos">Leaflet</a>');
    map.createPane("localBase");
    map.createPane("satellite");
    map.getPane("satellite").style.zIndex = "250";
    map.getPane("satellite").style.pointerEvents = "none";
    map.createPane("borders");
    map.getPane("borders").style.zIndex = "350";
    for (const collection of [stormtrackMapBase.countries, stormtrackMapBase.states]) {
      L.geoJSON(collection, {pane:"borders", interactive:false, style:{color:"#e2e6dc",weight:.8,opacity:.85,fill:false}}).addTo(map);
    }
    map.getPane("localBase").style.zIndex = "180";
    map.getPane("localBase").style.pointerEvents = "none";
    const colors = {Brazil:"#123b39", Argentina:"#17333c", Uruguay:"#19413e", Paraguay:"#23463a", Bolivia:"#28443c", Chile:"#253c43", Peru:"#24433d"};
    L.geoJSON(stormtrackMapBase.countries, {
      pane: "localBase", interactive: false,
      attribution: '<a href="https://www.naturalearthdata.com/" target="_blank" rel="noopener noreferrer">Natural Earth</a>',
      style: feature => ({color:"#56777c", weight:1.4, fillColor:colors[feature.properties.country] || "#1b353c", fillOpacity:1}),
    }).addTo(map);
    const stateColors = {Paraná:"#174d43", "Santa Catarina":"#1a443f", "Rio Grande do Sul":"#21483e", "São Paulo":"#23493d", "Mato Grosso do Sul":"#294f3e"};
    L.geoJSON(stormtrackMapBase.states, {
      pane:"localBase", interactive:false,
      style:feature => ({color:"#51756e", weight:1, fillColor:stateColors[feature.properties.name] || "#244338", fillOpacity:.85}),
    }).addTo(map);
    // Online tiles sit above local geography; the local map remains under gaps.
    detailedLayer = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom:19, noWrap:true,
      attribution:'&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors',
    });
    terrainLayer=L.tileLayer('https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_ShadedRelief_Bathymetry/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpg',{
      maxNativeZoom:8,maxZoom:18,noWrap:true,
      attribution:'NASA GIBS / Blue Marble · terreno estático (2004)',
    });
    let terrainErrors=0;
    terrainLayer.on('tileload',()=>{terrainErrors=0;});
    terrainLayer.on('tileerror',()=>{if (++terrainErrors>=4 && baseMode==='terrain') queueMicrotask(()=>{if(baseMode==='terrain') setBase('local','Terreno indisponível; base local ativa.');});});
    detailedLayer.on("loading", () => {
      loadedTiles = 0;
      failedTiles = 0;
      if (baseMode === "detailed") {
        baseStatus("Carregando mapa detalhado...");
        armTileFallback();
      }
    });
    detailedLayer.on("tileload", () => {
      loadedTiles++;
      failedBatches = 0;
      if (baseMode === "detailed") baseStatus("Mapa detalhado ativo · OpenStreetMap · requer internet.");
    });
    detailedLayer.on("tileerror", () => { failedTiles++; });
    detailedLayer.on("load", () => {
      if (baseMode !== "detailed") return;
      if (loadedTiles > 0) {
        clearTimeout(tileTimer);
        if (failedTiles) baseStatus("Algumas partes do mapa detalhado falharam; a base local permanece ao fundo.");
      } else if (failedTiles) {
        failedBatches++;
        if (failedBatches >= 2 || failedTiles >= 4) {
          // Leaflet finishes accessing this layer after firing the load event.
          // Defer removal until that callback has returned.
          queueMicrotask(() => {
            if (baseMode === "detailed") setBase("local", "Mapa detalhado indisponível. Base local ativa; tente novamente no seletor.");
          });
        }
      }
    });
    L.control.scale({imperial:false, position:"bottomleft"}).addTo(map);
    const focus = L.circleMarker(maringa, {radius:8, color:"#fff", weight:3, fillColor:"#e26724", fillOpacity:1});
    focus.bindTooltip("Maringá / PR", {permanent:true, direction:"right", className:"maringa-label"}).addTo(map);
    focus.bindPopup("Maringá/PR · foco inicial do StormTrack.");
    for (const [name, lat, lon] of [
      ["Curitiba",-25.43,-49.27], ["Florianópolis",-27.60,-48.55],
      ["Porto Alegre",-30.03,-51.23], ["Campo Grande",-20.47,-54.62],
      ["Asunción",-25.26,-57.58], ["Buenos Aires",-34.60,-58.38],
      ["Montevidéu",-34.90,-56.16],
    ]) L.circleMarker([lat,lon], {radius:3, color:"#365b68", weight:1, fillColor:"#fff", fillOpacity:1}).bindTooltip(name).addTo(map);
    observationLayer = L.layerGroup().addTo(map);
    map.fitBounds(regionBounds, {padding:[8,8],animate:false});
    drawObservations();
    document.querySelector("#map-base-select").addEventListener("change", event => setBase(event.target.value));
    document.querySelector("#map-home").addEventListener("click", () => map.fitBounds([[-34,-58],[-22,-48]]));
    document.querySelector("#map-maringa").addEventListener("click", () => map.setView(maringa, 9));
    document.querySelector("#map-region").addEventListener("click", () => map.fitBounds(regionBounds, {padding:[18,18]}));
    map.zoomControl._zoomInButton.setAttribute("aria-label", "Aproximar mapa");
    map.zoomControl._zoomOutButton.setAttribute("aria-label", "Afastar mapa");
    if (typeof ResizeObserver !== "undefined") {
      resizeObserver = new ResizeObserver(() => { if (container.clientWidth) map.invalidateSize({pan:false}); });
      resizeObserver.observe(container);
    }
    setBase("terrain");
    return map;
  }

  window.addEventListener("offline", () => { if (map) setBase("local", "Sem internet. Base local ativa."); });
  window.StormTrackMap = {
    resize() {
      const active = ensureMap();
      if (active) active.invalidateSize({pan:false});
    },
    updateObservations(collection) {
      observations = validObservations(collection);
      const existing = Boolean(map);
      ensureMap();
      if (existing) drawObservations();
      return observations.length;
    },
    instance() { return ensureMap(); },
    regional(active) { regionalMode = active; drawObservations(); },
    clearObservations() {
      observations = [];
      if (observationLayer) observationLayer.clearLayers();
    },
  };
})();
