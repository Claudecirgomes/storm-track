const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
async function check(base) {
  const elements=new Map();
  const get=id=>{if(!elements.has(id))elements.set(id,{clientWidth:320,clientHeight:240,style:{},append(){},scrollIntoView(){}});return elements.get(id);};
  const modes=['temperature','wind','combined'].map(surfaceMode=>({dataset:{surfaceMode},setAttribute(){}}));
  const createMap=()=>({groups:[],handlers:{},panes:{},controls:[],attributionControl:{setPrefix(){}},fitBounds(){this.fitted=true;},invalidateSize(){},on(name,fn){this.handlers[name]=fn;},removeLayer(group){this.groups=this.groups.filter(item=>item!==group);},getPane(name){return this.panes[name];},createPane(name){this.panes[name]={style:{}};}});
  const mini=createMap(),main=createMap();
  const shape=(kind,options)=>({bindPopup(){return this;},bindTooltip(){return this;},addTo(group){if(group.items)group.items.push({kind,options});return this;}});
  const document={querySelector:get,querySelectorAll:()=>modes,createElement:()=>({append(){},style:{}})};
  const data={features:[{geometry:{coordinates:[-51.9386,-23.4205]},properties:{temperature_2m:24.6,wind_speed_10m:9.7,wind_direction_10m:282,valid_at:'2026-11-05T21:30:00Z',location_name:'Maringá'}},{geometry:{coordinates:[-55,-27]},properties:{temperature_2m:null,wind_speed_10m:0,wind_direction_10m:null,valid_at:'2026-11-05T21:30:00Z'}}],bounds:[-68,-39,-44,-18],state:'partial',complete_points:1,requested_points:2,fetched_at:'2026-11-05T21:35:00Z'};
  const context=vm.createContext({document,window:{StormTrackMap:{instance:()=>main}},state:{account:{}},api:async()=>data,
    stormtrackMapBase:{countries:{},states:{}},Intl,Date,WeakSet,setInterval(){},
    L:{map:()=>mini,geoJSON:()=>shape('base',{}),layerGroup:()=>({items:[],addTo(target){target.groups.push(this);return this;}}),
      circleMarker:(_,options)=>shape('circle',options),marker:(_,options)=>shape('wind',options),divIcon:options=>options,
      control:()=>({addTo(target){this.onAdd();return this;},remove(){}}),DomEvent:{disableClickPropagation(){}}}});
  vm.runInContext(fs.readFileSync(base+'/frontend/surface-weather.js','utf8'),context);
  await new Promise(resolve=>setTimeout(resolve,0));
  assert.equal(main.groups.length,0,'Opening the card must not change the principal map');
  assert.ok(mini.groups.at(-1).items.some(item=>item.kind==='wind' && item.options.icon.html.includes('rotate(102deg)')),'Arrow shows flow direction, opposite the meteorological from-direction');
  modes[0].onclick();
  assert.equal(mini.groups.at(-1).items.filter(item=>item.kind==='wind').length,0,'Temperature-only mode removes wind glyphs');
  get('#surface-expand').onclick();
  assert.equal(context.window.StormTrackSurface.isExpanded(),true);
  assert.equal(main.groups.length,1);
  context.window.StormTrackSurface.setTimeline({live:false});
  assert.equal(main.groups.length,0,'Current model overlay is removed during replay');
  assert.equal(get('#surface-expand').disabled,true);
  assert.equal(get('#surface-timeline-note').hidden,false);
  context.window.StormTrackSurface.clear();
  return 'Surface card modes, wind direction, opt-in principal overlay, and replay isolation: passed';
}
module.exports=check;
if(require.main===module)check(require('node:path').resolve(__dirname,'..')).then(console.log).catch(error=>{console.error(error);process.exitCode=1;});
