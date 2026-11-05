/* Isolated behavior test, never loaded by the application. Run with Node.js. */
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
async function check(base) {
  const elements = new Map();
  const get = selector => {
    if (!elements.has(selector)) elements.set(selector,{style:{},value:selector.endsWith('product')?'combined':selector.endsWith('opacity')?'.85':'0',checked:true,
      append(){},addEventListener(){},setAttribute(){},after(){},classList:{add(){},remove(){}}});
    return elements.get(selector);
  };
  const classes = new Set();
  const panel = {querySelector:get,classList:{add(value){classes.add(value);},remove(value){classes.delete(value);},contains:value=>classes.has(value),toggle(value,active){active?classes.add(value):classes.delete(value);}}};
  const controls = {querySelector:get,append(){}};
  const document = {addEventListener(){},querySelector:selector=>selector==='.map-panel'?panel:get(selector),createElement:()=>controls};
  let catalog = [1,2].map(id=>({id:String(id),images:{c13:`${id}.png`,rgb:`${id}-rgb.png`,enhancement:`${id}-tops.png`},bounds:[-68,-39,-44,-18],
    start:`2026-01-01T00:${id===1?'00':'10'}:00Z`,end:`2026-01-01T00:${id===1?'10':'20'}:00Z`,state:'delayed'}));
  const requests = [];
  let imageFetches=0;
  const map = {removeLayer(){},on(){}};
  const cardMap={removeLayer(){},invalidateSize(){},fitBounds(){},attributionControl:{setPrefix(){}}};
  const addedCollections=[];
  get('#lightning-map').clientWidth=320;get('#lightning-map').clientHeight=240;
  const layer = () => ({addTo(){return this;},setOpacity(){}});
  let resizes=0;
  const preferences = new Map();
  const context = vm.createContext({document,window:{StormTrackMap:{instance:()=>map,regional(){},resize(){resizes++;}}},state:{account:{}},
    localStorage:{getItem:key=>preferences.get(key),setItem:(key,value)=>preferences.set(key,value)},
    authHeaders:()=>({}),fetch:async()=>{imageFetches++;return {ok:true,blob:async()=>({})};},
    Image:class {async decode(){}},URL:{createObjectURL:()=> 'test-url',revokeObjectURL(){}},
    api:async path=>{requests.push(path);return path.endsWith('catalog')?{frames:catalog,products:[{product:'glm',latest_observed_end:'2026-01-01T00:25:00Z'}],palette:{values:[-90,40],colors:[[12,10,17],[10,10,15]]}}:{features:[],state:'complete',count:0,coverage_fraction:1,start:'2026-01-01T00:00:00Z',end:'2026-01-01T00:10:00Z'};},
    stormtrackMapBase:{countries:{type:'FeatureCollection',features:[]},states:{type:'FeatureCollection',features:[]}},
    L:{map:()=>cardMap,imageOverlay:layer,geoJSON:collection=>({addTo(target){addedCollections.push({collection,target});return this;}})},setInterval(){},Intl,Date,console});
  vm.runInContext(fs.readFileSync(base+'/frontend/lightning-card.js','utf8'),context);
  vm.runInContext(fs.readFileSync(base+'/frontend/regional-satellite.js','utf8'),context);
  await context.window.StormTrackRegional.refresh();
  assert.equal(get('.regional-gradient').style.background,'linear-gradient(to right,rgb(12,10,17) 0%,rgb(10,10,15) 100%)','Legend must use the renderer palette from the API');
  assert.equal(get('#regional-time').value,1);
  assert.equal(requests.filter(path=>path.includes('/flashes?')).at(-1),'/api/satellite/regional/flashes?end=2026-01-01T00%3A25%3A00Z&minutes=10','Live GLM card must advance independently of the older ABI frame');
  assert.equal(get('#lightning-summary').textContent,'0 flashes · cobertura completa','A complete, valid zero belongs in the GLM card');
  assert.ok(addedCollections.some(entry=>entry.collection.state==='complete' && entry.target===cardMap),'GLM data must render in the dedicated card map');
  assert.ok(!addedCollections.some(entry=>entry.collection.state==='complete' && entry.target===map),'GLM must not be drawn over the central satellite map');
  const loaded=imageFetches;
  await context.window.StormTrackRegional.refresh();
  assert.equal(imageFetches,loaded,'Unchanged imagery must be reused while live overlays continue refreshing');
  get('#regional-time').value='0';
  get('#regional-time').oninput();
  await new Promise(resolve=>setTimeout(resolve,0));
  catalog=[...catalog,{...catalog[1],id:'3',end:'2026-01-01T00:30:00Z'}];
  await context.window.StormTrackRegional.refresh();
  assert.equal(get('#regional-time').value,0,'Refresh must preserve a paused replay');
  assert.match(get('#regional-status').textContent,/Histórico/);
  assert.equal(requests.filter(path=>path.includes('/flashes?')).at(-1),'/api/satellite/regional/flashes?end=2026-01-01T00%3A10%3A00Z&minutes=10','Replay GLM card window must end at the selected observation');
  get('#regional-expand').onclick();
  assert.equal(classes.has('regional-expanded'),true);
  assert.equal(get('#regional-time').value,0,'Expanding must preserve the selected frame');
  get('#regional-expand').onclick();
  assert.equal(classes.has('regional-expanded'),false);
  assert.equal(resizes,2);
  get('#regional-product').value='c13';get('#regional-product').onchange();
  await new Promise(resolve=>setTimeout(resolve,0));
  assert.equal(preferences.get('stormtrack-satellite-product'),'c13');
  context.window.StormTrackRegional.clear();
  return 'Replay, GLM, legend, map expansion and product preference: passed';
}
module.exports = check;
if (require.main === module) check(require('node:path').resolve(__dirname,'..')).then(console.log).catch(error=>{console.error(error);process.exitCode=1;});
