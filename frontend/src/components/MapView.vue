<script setup lang="ts">
import {unitSymbolId,symbolById} from "../militarySymbols";
import {drawMilitaryPlotting} from "../mapPlotting";
import MapUnitLocator from './MapUnitLocator.vue';
import {mapUnitEntries,unitOverlapGroups} from '../mapUnits';
import type {UnitOverlapGroup} from '../mapUnits';
import {weaponLimits} from "../weaponRanges";
import type {PlotItem} from "../types";
// 🗺️ 战术地图：gentactix/viz.py build_tactical_map 的 Leaflet 移植。
// 军标、行军轨迹（含 ➤ 箭头与蚂蚁线动画）、交战定向扇区/降级空心环、
// 底图图层组与图层控制台的位置/口径都与 Folium 版一致；改这里请对照 viz.py。
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import L from "leaflet";
import {personnelStrengthPct} from '../personnelProjection';
import offlineLand from '../../public/maps/land-110m.geojson?raw';
import type { Snapshot, Unit, CommandPreview, MapPoint } from "../types";
import {
  TILE_LAYERS, natoHtml, unitPopup, iterEngagementSpecs,
  impactSectorVertices, engagementColors, withDemoEngagement, toFloat,
  escapeHtml,
} from "../tactical";

const props = defineProps<{ snap: Snapshot | null; selftest: boolean; overview?: boolean;
  toolbarTarget?: string;
  commandPreview?: CommandPreview | null; selectedUnit?: { team: string; name: string } | null;
  picking?: 'move' | 'fire' | null; plotPicking?:boolean; plotPreview?:PlotItem[] }>();
const emit = defineEmits<{ 'unit-select': [team: string, name: string]; 'map-target': [point: MapPoint]; 'plot-point':[point:MapPoint];'plot-select':[id:string] }>();

const el = ref<HTMLDivElement | null>(null);
const deploymentGap=computed(()=>{
  const world=props.snap?.war_state;
  if(props.overview||!world?.history_replay)return null;
  const units=[...(world.red_units??[]),...(world.blue_units??[])];
  return units.some(u=>unitPos(u)!==null)?null:{references:units.length};
});
let map: L.Map | null = null;
function captureMoveTarget(event: MouseEvent) {
  if (!map || (!props.plotPicking && props.picking !== 'move') || event.detail === 0) return;
  const target = event.target as Element | null;
  if (target?.closest('.leaflet-control, .leaflet-popup, button, input, select')) return;
  // Marker labels and SVG overlays extend beyond their visible symbols. During
  // destination picking, read the actual pointer location before they swallow it.
  const point = map.mouseEventToLatLng(event);
  event.preventDefault(); event.stopPropagation();
  if(props.plotPicking)emit('plot-point',{lat:point.lat,lng:point.lng});
  else emit('map-target',{lat:point.lat,lng:point.lng});
}

function focusAirRoutes() {
  const points = (props.snap?.war_state?.air_operations?.missions ?? [])
    .flatMap(task => task.events.map(event => L.latLng(event.lat, event.lng)));
  if (map && points.length) map.fitBounds(L.latLngBounds(points), { padding: [35,35], maxZoom: 13, animate: false });
}
let layerGroup: L.LayerGroup | null = null;
let commandLayer: L.LayerGroup | null = null;
let plottingLayer:L.LayerGroup|null=null;
const showAnnotations=ref(true);
function drawPlotting(){if(map&&plottingLayer){if(showAnnotations.value)drawMilitaryPlotting(map,plottingLayer,props.snap?.plotting,props.plotPreview??[],id=>emit('plot-select',id));else plottingLayer.clearLayers();}}
let centeredSession: string | null = null;
const unitMarkers = new Map<string, L.Marker>();
const unitMarkerOffsets=new Map<string,number>();
const mapEntries=computed(()=>mapUnitEntries(props.snap));
const selectedMapId=computed(()=>mapEntries.value.find(r=>r.team===props.selectedUnit?.team&&r.name===props.selectedUnit.name)?.id??'');
const unitStacks=ref<UnitOverlapGroup[]>([]);
let unitStackLayer:L.LayerGroup|null=null,stackFrame=0;
function selectMapEntry(id:string){
  const entry=mapEntries.value.find(r=>r.id===id);if(!entry||props.picking||props.plotPicking)return;
  map?.closePopup();if(map&&entry.position)map.panInside([entry.position.lat,entry.position.lng],{padding:[45,45],animate:false});
  emit('unit-select',entry.team,entry.name);
}
function openUnitStack(group:UnitOverlapGroup,at:L.LatLng){
  if(!map||props.picking||props.plotPicking)return;
  const root=document.createElement('div');root.className='unit-stack-list';
  const heading=document.createElement('strong');heading.textContent=`重叠的计算单位 · ${group.ids.length}`;root.appendChild(heading);
  const note=document.createElement('p');note.textContent='军标保留实际坐标，选择一项查看或下令。';root.appendChild(note);
  for(const id of group.ids){
    const entry=mapEntries.value.find(r=>r.id===id);if(!entry)continue;
    const button=document.createElement('button');button.type='button';button.dataset.stackMember=id;button.className=entry.team;
    const name=document.createElement('span');name.textContent=`选择${entry.team==='red'?'红':'蓝'}方 ${entry.name}`;
    const state=document.createElement('small');state.textContent=[entry.echelon,entry.status,entry.source_id].filter(Boolean).join(' · ');
    button.append(name,state);button.onclick=()=>selectMapEntry(id);root.appendChild(button);
  }
  L.DomEvent.disableClickPropagation(root);L.popup({maxWidth:360,maxHeight:330,className:'unit-stack-popup'}).setLatLng(at).setContent(root).openOn(map);
  root.querySelector('button')?.focus();
}
function refreshUnitStacks(){
  if(!map||!unitStackLayer)return;unitStackLayer.clearLayers();const size=map.getSize();
  const box=map.getContainer().getBoundingClientRect();
  const projected=mapEntries.value.filter(r=>r.position).map(r=>{
    const icon=unitMarkers.get(r.team+':'+r.name)?.getElement()?.getBoundingClientRect();
    const p=icon?.width?{x:icon.left+icon.width/2-box.left,y:icon.top+icon.height/2-box.top}:map!.latLngToContainerPoint([r.position!.lat,r.position!.lng]);
    return{id:r.id,x:p.x,y:p.y};
  });
  unitStacks.value=unitOverlapGroups(projected,size.x,size.y);
  if(props.overview)return;
  for(const group of unitStacks.value.filter(g=>g.ids.length>1)){
    const at=map.containerPointToLatLng([group.x,group.y]);
    const button=document.createElement('button');button.type='button';button.className='unit-stack-button';button.textContent=`${group.ids.length} ≡`;
    button.setAttribute('aria-label',`展开${group.ids.length}个重叠单位`);button.dataset.stackCount=String(group.ids.length);button.disabled=!!props.picking||!!props.plotPicking;
    button.onclick=e=>{e.stopPropagation();openUnitStack(group,at);};
    const marker=L.marker(at,{keyboard:false,bubblingMouseEvents:false,zIndexOffset:2000,
      icon:L.divIcon({className:'unit-stack-marker',html:button,iconSize:[40,26],iconAnchor:[0,13]})});
    unitStackLayer.addLayer(marker);
  }
}
function scheduleUnitStacks(){if(!stackFrame)stackFrame=requestAnimationFrame(()=>{stackFrame=0;refreshUnitStacks();});}
let renderFrame = 0;
function updateSelectedUnit() {
  const selected = props.selectedUnit ? props.selectedUnit.team + ':' + props.selectedUnit.name : '';
  for (const [identity, marker] of unitMarkers) {marker.getElement()?.classList.toggle('command-selected', identity === selected);marker.setZIndexOffset(identity===selected?1200:unitMarkerOffsets.get(identity)??0);}
}
function scheduleRender() {
  if (renderFrame) return;
  renderFrame = requestAnimationFrame(() => { renderFrame = 0; render(); });
}
const visible = reactive({ terrain: true, ranges: true, sectors: true, supply: true });
const view = computed(() => props.snap?.battlefield);
const terrainBase = ref(false);
const offlineBase=ref(false),tileFailures=ref(0);
const missingTiles=new Map<string,Set<string>>();
function refreshTileFailures(){tileFailures.value=offlineBase.value?0:[...missingTiles].filter(([name])=>map?.hasLayer(baseLayers[name])).reduce((n,[,tiles])=>n+tiles.size,0);}
function useOfflineBase(){if(!map)return;for(const layer of Object.values(baseLayers))map.removeLayer(layer);offlineBase.value=true;refreshTileFailures();}
function restoreOnlineBase(){if(!map)return;offlineBase.value=false;const name=terrainBase.value?'🏔️ 战术地形图':'🛰️ 天眼卫星实景';baseLayers[name]?.addTo(map);refreshTileFailures();}
const showUnitLabels = ref(false);
const overlays: Record<string, L.LayerGroup> = {};
const baseLayers: Record<string, L.TileLayer> = {};
let sizeObserver: ResizeObserver | null = null;

function textTooltip(text: string) {
  const node = document.createElement("span");
  node.textContent = text;
  return node;
}

function toggleTerrainBase() {
  if (!map) return;
  const useTerrain = !terrainBase.value;
  const name = useTerrain ? "🏔️ 战术地形图" : "🛰️ 天眼卫星实景";
  for (const layer of Object.values(baseLayers)) map.removeLayer(layer);
  baseLayers[name]?.addTo(map);
  terrainBase.value = useTerrain;
  offlineBase.value=false;refreshTileFailures();
}

function drawBattlefield() {
  for (const group of Object.values(overlays)) group.clearLayers();
  const data = view.value;
  if (!data) return;
  const terrainColors: Record<string, string> = { ridge: "#b87940", river: "#39a9d1", road: "#c6bb99", woods: "#4d9362", urban: "#a398bd", fortification: "#ddac50" };
  const teamColor = (team: string) => team === "red" ? "#da6c67" : "#629be8";
  if (visible.terrain) for (const f of data.terrain.features) {
    const style = { color: terrainColors[f.kind] ?? "#a8a8a8", weight: 3, className: "bf-terrain", fillOpacity: 0.16 };
    const shape = f.geometry === "polygon" ? L.polygon(f.coordinates, style)
      : f.geometry === "point" ? L.circleMarker(f.coordinates[0], { ...style, radius: 5 })
      : L.polyline(f.coordinates, style);
    shape.bindTooltip(textTooltip(`${f.name} · ${f.source}${f.elevation_m == null ? "" : ` · 标注高程 ${f.elevation_m} m`}`)).addTo(overlays.terrain);
  }
  if (visible.ranges) for (const r of data.fire_ranges) {
    const tip = `${r.name} · 射程 ${r.min_range_m}—${r.max_range_m} m · ${r.source}；非杀伤半径`;
    L.circle(r.position, { radius: r.max_range_m, color: teamColor(r.team), weight: 1, fill: false,
      dashArray: r.estimated ? "6 5" : undefined, className: "bf-range" })
      .bindTooltip(textTooltip(tip)).addTo(overlays.ranges);
    if (r.min_range_m) L.circle(r.position, { radius: r.min_range_m, color: "#d9a648", weight: 1, fill: false,
      dashArray: "2 5", className: "bf-min-range" }).bindTooltip("最小射程边界").addTo(overlays.ranges);
  }
  const snap=props.snap, modelRules=snap?.war_state?.mission?.definition.combined_rules;
  if (snap && modelRules && visible.ranges) for (const u of [...snap.war_state?.red_units ?? [],...snap.war_state?.blue_units ?? []]) {
    const point=unitPos(u);if(!point)continue;
    const limits=weaponLimits(snap.war_state!,u);
    for (const [category,key,label,color] of [['artillery','bombard','炮兵间瞄射程','#d8ae73'],['air_defense','air_defense','防空平面范围（另受高度/弹药约束）','#79b9cd']] as const) {
      const limit=limits[key],radius=limit?.max_range_m??0;
      if (!u.equipment?.some(e=>e.category===category&&e.operational>0) || radius<=0)continue;
      L.circle(point,{radius,color,weight:1,dashArray:'3 7',fillOpacity:0,className:'bf-aggregate-range'})
        .bindTooltip(textTooltip(`${u.name} · ${label} ${(radius/1000).toFixed(1)}km · 教学估计，未计算遮挡`)).addTo(overlays.ranges);
      if(limit&&limit.min_range_m>0)L.circle(point,{radius:limit.min_range_m,color,weight:1,dashArray:'2 5',fill:false,className:'bf-aggregate-min-range'})
        .bindTooltip(textTooltip(`${u.name} · ${label}最小范围 ${limit.min_range_m}m；非通视判定`)).addTo(overlays.ranges);
    }
  }
  if (visible.sectors) for (const s of data.fields_of_fire) {
    L.polygon(s.coordinates, { color: teamColor(s.team), weight: 1, fillOpacity: 0.10, className: "bf-sector" })
      .bindTooltip(textTooltip(`${s.name} · 射界 ${s.bearing_deg}° / ${s.arc_deg}° · 未计算高程遮挡`)).addTo(overlays.sectors);
  }
  if (visible.supply) {
    for (const n of data.supply_nodes) {
      L.marker(n.position, { icon: L.divIcon({ className: "supply-node", html: "▣", iconSize: [22, 22], iconAnchor: [11, 11] }) })
        .bindTooltip(textTooltip(`${n.name} · 补给节点 · ${n.source}`)).addTo(overlays.supply);
    }
    const labels: Record<string, string> = { open: "几何未切断", cut: "几何受阻", threatened: "受威胁", unknown: "通行未核实" };
    for (const r of data.supply_lines) {
      const color = r.status === "cut" ? "#e05a4e" : r.estimated || r.status !== "open" ? "#e0a83e" : "#4caf7d";
      L.polyline(r.coordinates, { color, weight: 2, dashArray: r.estimated ? "7 6" : undefined, className: "bf-supply" })
        .bindTooltip(textTooltip(`${r.name} · ${labels[r.status] ?? labels.unknown} · ${r.source}${r.cut_by ? ` · 几何截断单位：${r.cut_by}` : ""}`)).addTo(overlays.supply);
    }
  }
}

function battleCenter(snap: Snapshot | null): [number, number] {
  const center = snap?.war_state?.center;
  if (Array.isArray(center) && center.length === 2) {
    const lat = toFloat(center[0]), lng = toFloat(center[1]);
    if (lat !== null && lng !== null && Math.abs(lat) <= 90 && Math.abs(lng) <= 180) {
      return [lat, lng];
    }
  }
  // 缺少中心时以首个有效单位定位，避免其他战役仍落在长平。
  for (const u of [...(snap?.war_state?.red_units || []), ...(snap?.war_state?.blue_units || [])]) {
    const pos = unitPos(u);
    if (pos && Math.abs(pos[0]) <= 90 && Math.abs(pos[1]) <= 180) return pos;
  }
  return [35.8, 104];
}

function unitPos(u: Unit): [number, number] | null {
  const lat = toFloat(u.lat), lng = toFloat(u.lng);
  if (lat === null || lng === null) return null;
  return [lat, lng];
}

function unitByName(snap: Snapshot, team: "red" | "blue", name: string): Unit | null {
  if (!snap.last_war_state) return null;
  const list = (team === "red" ? snap.last_war_state.red_units : snap.last_war_state.blue_units) || [];
  return list.find((u) => String(u.name ?? "") === name) ?? null;
}

// ➤ 箭头沿行军方向（方位角从正北顺时针，与 folium PolyLineTextPath 同语义）
function arrowAt(from: [number, number], to: [number, number], color: string): L.Marker {
  const mid: [number, number] = [(from[0] + to[0]) / 2, (from[1] + to[1]) / 2];
  const bearing = (Math.atan2(to[1] - from[1], to[0] - from[0]) * 180) / Math.PI;
  return L.marker(mid, {
    interactive: false,
    icon: L.divIcon({
      className: "trail-arrow",
      html: `<span style="color:${color};font-weight:bold;font-size:18px;transform:rotate(${bearing}deg);display:inline-block;">➤</span>`,
      iconSize: [18, 18], iconAnchor: [9, 9],
    }),
  });
}

function drawTrails(snap: Snapshot, team: "red" | "blue", color: string) {
  const units = (team === "red" ? snap.war_state!.red_units : snap.war_state!.blue_units) || [];
  for (const u of units) {
    const pos = unitPos(u);
    if (!pos) continue;
    const prev = unitByName(snap, team, String(u.name ?? ""));
    const prevPos = prev ? unitPos(prev) : null;
    if (!prevPos || (prevPos[0] === pos[0] && prevPos[1] === pos[1])) continue;
    layerGroup!.addLayer(L.polyline([prevPos, pos], {
      color, weight: 2, opacity: 0.6, dashArray: "5 5",
      interactive: true,
    }).bindTooltip(textTooltip(`${u.name ?? ""} 的行军路线`)));
    layerGroup!.addLayer(arrowAt(prevPos, pos, color));
    // 蚂蚁线动画（folium plugins.AntPath 的 CSS 等价实现）
    layerGroup!.addLayer(L.polyline([prevPos, pos], {
      color, weight: 5, opacity: 0.3, className: "ant-march", interactive: false,
    }));
  }
}

function drawUnits(snap: Snapshot, team: "red" | "blue", color: string) {
  const units = (team === "red" ? snap.war_state!.red_units : snap.war_state!.blue_units) || [];
  const participation=new Map(Object.values(snap.war_state?.unit_participation?.actors??{}).filter(r=>r.team===team).map(r=>[r.name,r.status]));
  const operationLabels={reserve:'后方待命',returning:'返场途中',withdrawing:'退出途中',staging:'待入场',deployed:'在场作战',offmap:'场外待命'};
  for (const u of units) {
    const pos = unitPos(u);
    if (!pos) continue;
    const binding=snap.plotting?.units.find(x=>x.team===team&&x.name===String(u.name??''));
    const override=binding?snap.plotting?.unit_symbols[binding.id]:undefined;
    const id=override||unitSymbolId(u),anchor=symbolById(id).anchor;
    const staged=snap.war_state?.campaign?.actors[String(u.name??'')]?.active===false;
    const operation=participation.get(String(u.name??''));
    const operationLabel=operation&&operation!=='deployed'&&operation!=='staging'?operationLabels[operation]:'';
    const mapEntry=mapEntries.value.find(r=>r.team===team&&r.name===String(u.name??''));
    const marker = L.marker(pos, {
      riseOnHover:true,zIndexOffset:props.selectedUnit?.team===team&&props.selectedUnit.name===u.name?1000:operationLabel?600:0,
      bubblingMouseEvents:false,title:`${team==='red'?'红':'蓝'}方 ${u.name??''}${operationLabel?' · '+operationLabel:''}`,alt:String(u.name??'单位'),
      icon:L.divIcon({className:'nato-marker'+(staged?' campaign-staging':'')+(operationLabel?' has-participation':'')+(props.selectedUnit?.team===team&&props.selectedUnit.name===u.name?' command-selected':''),html:natoHtml(u,team,override)+(operationLabel?`<span class="operation-participation">${operationLabel}</span>`:''),iconSize:[36,36],iconAnchor:[anchor[0]*1.5,anchor[1]*1.5]}),
    });
    marker.on('click',()=>{
      if(!map||!mapEntry)return;refreshUnitStacks();const group=unitStacks.value.find(g=>g.ids.includes(mapEntry.id));
      if(group&&group.ids.length>1)openUnitStack(group,L.latLng(pos));else selectMapEntry(mapEntry.id);
    });
    marker.on('add',()=>{
      const el=marker.getElement();el?.setAttribute('aria-label',`${team==='red'?'红':'蓝'}方 ${u.name??'单位'}${staged?' · 待入场':''}${operationLabel?' · '+operationLabel:''}`);
      if(staged)el?.setAttribute('data-campaign-staging','true');
      if(operation)el?.setAttribute('data-unit-participation',operation);
      if(mapEntry){el?.setAttribute('data-map-unit-id',mapEntry.id);el?.setAttribute('data-map-lat',String(pos[0]));el?.setAttribute('data-map-lng',String(pos[1]));}
    });
    const strength=personnelStrengthPct(u);
    marker.bindTooltip(textTooltip(String(u.name || '未知单位')+(strength===null?'':` · 人员保有率 ${strength}%（非编制满员率）`)+(staged?' · 待入场（计算部署）':operationLabel?' · '+operationLabel:'')), { direction: 'right' });
    layerGroup!.addLayer(marker);
    unitMarkers.set(team + ':' + String(u.name ?? ''), marker);
    unitMarkerOffsets.set(team+':'+String(u.name??''),operationLabel?600:0);
  }
}

function drawCommandPreview() {
  commandLayer?.clearLayers();
  const p = props.commandPreview;
  if (!p || !commandLayer) return;
  const origin: [number, number] = [p.origin.lat, p.origin.lng];
  L.circle(origin, { radius: p.moveKm * 1000, color: '#e9cb7d', weight: 1, dashArray: '4 6', fillOpacity: .04, interactive: false })
    .addTo(commandLayer);
  if (p.destination) {
    const target: [number, number] = [p.destination.lat, p.destination.lng];
    const distance = L.latLng(origin).distanceTo(L.latLng(target)) / 1000;
    L.polyline([origin, target], { color: '#e9cb7d', weight: 3, dashArray: '8 7' })
      .bindTooltip(textTooltip(`预定直线 ${distance.toFixed(2)} km · 本轮预算 ${p.moveKm.toFixed(2)} km · 未计算道路/高程通行`)).addTo(commandLayer);
    L.circleMarker(target, { radius: 7, color: '#ffe5a0', fillOpacity: .5 }).bindTooltip('预定目的地，尚未执行').addTo(commandLayer);
  }
}

function drawEngagements(snap: Snapshot) {
  const state = props.selftest && snap.war_state ? withDemoEngagement(snap.war_state) : snap.war_state;
  if (!state) return;
  for (const spec of iterEngagementSpecs(state)) {
    if (!spec.valid) continue;
    const bPos = [spec.lat!, spec.lng!] as [number, number];
    const radius = spec.radius!;
    const { border, fill } = engagementColors(radius);
    const sector = spec.useSector && spec.attacker;
    const tooltip = `💥 <b>${escapeHtml(spec.desc)}</b><br>交战示意范围 ≈ ${radius.toFixed(0)} 米（非杀伤半径）` +
      `<br><span style='color:#8a8a8a'>依据：${escapeHtml(spec.basis)}</span>` +
      (sector ? "" : "<br>（未提供攻击方位，仅显示范围）");

    if (sector) {
      const [aLat, aLng] = spec.attacker!;
      layerGroup!.addLayer(L.polygon(impactSectorVertices(aLat, aLng, spec.lat!, spec.lng!, radius), {
        color: border, weight: 1.5, fill: true, fillColor: fill, fillOpacity: 0.12, dashArray: "6 4",
      }).bindTooltip(tooltip));
    } else {
      layerGroup!.addLayer(L.circle(bPos, {
        radius, color: border, weight: 1.5, fill: false, dashArray: "6 4",
      }).bindTooltip(tooltip));
    }

    layerGroup!.addLayer(
      L.marker(bPos, {
        interactive: false, keyboard: false,
        icon: L.divIcon({ className: "fire-marker", html: "🔥", iconSize: [22, 22], iconAnchor: [11, 11] }),
      }).bindTooltip(`💥 <b>交战发生 (示意 ${radius.toFixed(0)} 米，非杀伤半径)</b><br>${escapeHtml(spec.desc)}`),
    );

    // 火力打击轨迹：扇区已表达方向，这里只指向落点，压细压淡（AntPath 等价）
    if (sector) {
      const [aLat, aLng] = spec.attacker!;
      layerGroup!.addLayer(L.polyline([[aLat, aLng], bPos], {
        color: border, weight: 1.5, opacity: 0.55, className: "ant-fire", interactive: false,
      }).bindTooltip("🔥 火力打击方向"));
    }
  }
}

function render() {
  if (!map || !layerGroup) return;
  layerGroup.clearLayers();
  unitMarkers.clear();
  unitMarkerOffsets.clear();unitStackLayer?.clearLayers();unitStacks.value=[];
  const snap = props.snap;
  if (!snap?.war_state) return;
  const boundary=snap.war_state.mission?.definition.operation_boundary;
  if(boundary&&Number.isFinite(boundary.center.lat)&&Number.isFinite(boundary.center.lng)&&Number.isFinite(boundary.radius_km)&&boundary.radius_km>0){
    L.circle([boundary.center.lat,boundary.center.lng],{radius:boundary.radius_km*1000,color:'#91b6bd',weight:2,dashArray:'9 6',fillOpacity:.015,className:'operation-boundary'})
      .bindTooltip(textTooltip('计算作战区边界 · '+boundary.assumption+'；区外仍在同一仿真世界。')).addTo(layerGroup);
    for(const route of boundary.routes)L.polyline([[route.inside.lat,route.inside.lng],[route.outside.lat,route.outside.lng]],
      {color:route.team==='red'?'#ce8e88':'#83accb',weight:3,dashArray:'4 5',className:'operation-route'})
      .bindTooltip(textTooltip(`${route.id} · 已登记直线出入通路 · 半宽${route.corridor_km} km；${route.assumption}`)).addTo(layerGroup);
  }
  if (snap.war_state.history_replay) {
    const references = snap.war_state.history_replay.geo_references;
    for (const point of references) L.circleMarker([point.lat, point.lng], { radius: 7, color: '#d4bb85', fillOpacity: .15 })
      .bindTooltip(textTooltip(`${point.name} · 地名参考，非部队部署 · 定位不确定度${point.metadata.uncertainty_km ?? '未知'}km`)).addTo(layerGroup);
    if (centeredSession !== snap.session_id && references.length) {
      map.fitBounds(L.latLngBounds(references.map(p => [p.lat, p.lng] as [number, number])), {padding: [55, 55], maxZoom: 10, animate: false});
      centeredSession = snap.session_id;
    }
    // Historical units with known positions share the normal symbol renderer.
    // Unknown positions remain unplotted; never place them on a locality marker.
    drawUnits(snap, "red", "red");
    drawUnits(snap, "blue", "blue");
    scheduleUnitStacks();
    return;
  }
  // 新会话重新定位；同一局下一回合和渲染自检保留用户的平移、缩放。
  if (centeredSession !== snap.session_id) {
    const positions = [...(snap.war_state.red_units || []), ...(snap.war_state.blue_units || [])]
      .map(unitPos).filter((position): position is [number, number] => position !== null);
    if (positions.length > 1) map.fitBounds(L.latLngBounds(positions), { padding: [55, 55], maxZoom: 13, animate: false });
    else map.setView(battleCenter(snap), 11, { animate: false });
    centeredSession = snap.session_id;
  }
  drawTrails(snap, "red", "red");
  drawTrails(snap, "blue", "blue");
  drawUnits(snap, "red", "red");
  drawUnits(snap, "blue", "blue");
  scheduleUnitStacks();
  drawEngagements(snap);
  const terrain=snap.war_state.mission?.definition.terrain_model;
  if(terrain){
    for(const b of terrain.barriers)L.polyline([b.a,b.b],{color:'#dfad70',weight:3,dashArray:'5 4',className:'terrain-barrier'})
      .bindTooltip(textTooltip(`登记地形障碍 · ${b.blocks.join(' / ')} · ${b.source}`)).addTo(layerGroup);
    for(const r of terrain.roads)L.polyline([r.a,r.b],{color:'#9cae9d',weight:4,opacity:.65,className:'terrain-road'})
      .bindTooltip(textTooltip(`登记道路 · 速度系数${r.speed_factor} · ${r.source}`)).addTo(layerGroup);
  }
  const combined=snap.war_state?.combined_arms;
  if (combined && snap.war_state?.mission?.definition.combined_rules?.bridge_enabled!==false) {
    for(const b of [combined.bridge,...(combined.bridge.crossing_network?.sites??[])]){
    const status=b.crossing_model?`吞吐 ${b.crossing_model.throughput_work_per_hour} 工作量/小时`:`通行${b.used}/${b.capacity}批次`;
    L.circleMarker([b.lat,b.lng],{radius:9,color:b.progress===100&&b.integrity>=50?'#8de0b6':'#efbc72',weight:3,fillOpacity:.3})
      .bindTooltip(textTooltip(`${b.name}（计算设施）· 施工${b.progress}% · 完整度${b.integrity}% · ${status}`)).addTo(layerGroup!);
    if(b.crossing_model){
      const m=b.crossing_model;
      if(b.id===combined.bridge.id)L.polyline([m.barrier.a,m.barrier.b],{color:'#9abbd0',weight:5,opacity:.65,className:'crossing-barrier'})
        .bindTooltip(textTooltip('计算河线 · 显式估计，不是历史水文测绘')).addTo(layerGroup!);
      L.polyline([m.banks.a,m.banks.b],{color:'#e9c78b',weight:3,dashArray:'5 5',className:'crossing-corridor'})
        .bindTooltip(textTooltip(`渡运通道 · ${m.throughput_work_per_hour} 工作量/小时 · ${m.assumption}`)).addTo(layerGroup!);
      for(const [key,point] of Object.entries(m.banks))L.circleMarker(point,{radius:5,color:'#e9c78b',fillOpacity:.7})
        .bindTooltip(textTooltip(`通道岸点 ${key.toUpperCase()} · 计算估计`)).addTo(layerGroup!);
      for(const boat of b.ferry_state?.boats??m.ferry?.boats.map(x=>({id:x.id,...m.banks[x.initial_bank],phase:'idle',manifest_personnel:0,passenger:null}))??[]){
        const spec=m.ferry?.boats.find(x=>x.id===boat.id);
        const phases:Record<string,string>={idle:'靠岸',loading:'装载',outbound:'载客航行',unloading:'卸载',returning:'空艇返航'};
        const color=spec?.team==='blue'?'#99c9f4':'#ef9a8d';
        L.marker([boat.lat,boat.lng],{title:`舟艇 ${spec?.name??boat.id}`,alt:`舟艇 ${spec?.name??boat.id}`,bubblingMouseEvents:false,
          icon:L.divIcon({className:'ferry-boat-marker',iconSize:[24,24],iconAnchor:[44,12],html:`<svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true"><path d="M3 12h18l-4 7H7zM7 12V6h10v6M12 6V2" fill="#102e3e" stroke="${color}" stroke-width="2"/><path d="M2 21h20" stroke="${color}"/></svg>`})})
         .bindTooltip(textTooltip(`${spec?.name??boat.id}（计算舟艇）· ${phases[boat.phase]??boat.phase} · 乘载${boat.manifest_personnel}/${spec?.seats??'?'}人 · ${boat.passenger??'空艇'} · ${boat.lat.toFixed(6)}, ${boat.lng.toFixed(6)}`)).addTo(layerGroup!);
      }
    }
  }
    }
  for (const task of snap.war_state?.air_operations?.missions ?? []) {
    const route: L.LatLngExpression[] = task.events.map(event => [event.lat, event.lng]);
    const color = task.team === 'red' ? '#91e9e0' : '#b3c4ff';
    if (route.length > 1) L.polyline(route, { color, weight: 3, dashArray: '9 6', className: 'air-mission-route' })
      .bindTooltip(textTooltip(`航空任务 · ${task.requester} → ${task.target} · ${task.outcome === 'strike' ? '打击并返场' : '中止并返场'}（教学）`)).addTo(layerGroup!);
    const strike = task.events.find(event => event.phase === 'strike' || event.phase === 'abort_target_moved');
    if (strike) L.circleMarker([strike.lat, strike.lng], { color, radius: 8, weight: 2, fillOpacity: .18 })
      .bindTooltip(textTooltip(`航空目标 · ${task.target} · ${task.personnel_effect}人期望减员，${task.aircraft_lost}架飞机损失（教学）`)).addTo(layerGroup!);
  }
  drawBattlefield();
  drawPlotting();
  const mission = snap.war_state?.mission;
  if (mission) {
    const spec = mission.definition;
    if(spec.campaign_plan){
      for(const node of spec.campaign_plan.nodes){
        const region=node.condition.region;if(!region)continue;
        const state=snap.war_state?.campaign_plan?.nodes[node.id];
        const met=state?.status==='completed'&&state.condition;
        const color=met?'#8bd5a5':node.team==='red'?'#df9290':'#94b9eb';
        const status=state?.status==='completed'?(state.condition?'已达成':'里程碑已达成，当前未满足'):state?.status==='pending'?'尚未运行':'尚未达成';
        const scope=node.condition.kind==='defend'
          ?`防御部署区，允许接敌；突破核心见“${spec.campaign_plan.nodes.find(target=>target.id===node.condition.against_node)?.label??node.condition.against_node}”`
          :'计算估计范围';
        L.circle([region.center.lat,region.center.lng],{radius:region.radius_km*1000,color,weight:2,
          fillOpacity:.06,dashArray:node.condition.kind==='reach'?'2 5':'6 4',className:'campaign-goal-region'})
          .bindTooltip(textTooltip(`${node.team==='red'?'红方':'蓝方'} · ${node.label} · ${status} · ${scope}`)).addTo(layerGroup);
      }
    }else{
    const defensiveDelay=spec.campaign_definition?.objective_policy==='defensive-delay-1';
    L.circle([spec.objective.lat, spec.objective.lng], { radius: spec.goal_radius_km * 1000, color: '#eac87b', weight: 2, fillOpacity: .08, dashArray: '5 5' }).bindTooltip(textTooltip((defensiveDelay?'参考据点区 · 本迟滞规则不要求夺占。':'计算目标区 · ') + spec.goal)).addTo(layerGroup);
    for(const [index,region] of (spec.campaign_definition?.objective.relief_regions??[]).entries()){
      L.circle([region.center.lat,region.center.lng],{radius:region.radius_km*1000,color:'#84c3bc',weight:2,fillOpacity:.04,dashArray:'3 7'})
        .bindTooltip(textTooltip(`${defensiveDelay?'参考阻援区':'阻援区域'} ${index+1} · 计算估计范围${defensiveDelay?'；本迟滞规则不要求夺占':''}`)).addTo(layerGroup);
    }
    L.circle([spec.exit.lat, spec.exit.lng], { radius: 600, color: '#76c9b2', weight: 2, fillOpacity: .06 }).bindTooltip(textTooltip('教学后方出口 · 600米')).addTo(layerGroup);
    }
  }
}

onMounted(() => {
  if (!el.value) return;
  // 与 build_tactical_map 一致：以战局 center 开局、zoom 11；后续回合只重画图层，
  // 不重置用户缩放（对应 app.py 固定组件 key 的意图）
  map = L.map(el.value, { center: battleCenter(props.snap), zoom: props.snap?.war_state ? 11 : 4, zoomControl: true });
  el.value.addEventListener('click', captureMoveTarget, true);
  map.on('click', (event: L.LeafletMouseEvent) => {
    if (props.picking === 'move' && !(event.originalEvent?.target as Element | null)?.closest('.leaflet-marker-icon'))
      emit('map-target', { lat: event.latlng.lat, lng: event.latlng.lng });
  });
  // Bundled public-domain coastlines keep the China overview usable without tile access.
  map.createPane('offline-land');
  map.getPane('offline-land')!.style.zIndex = '150';
  const activeMap = map;
  L.geoJSON(JSON.parse(offlineLand), { pane: 'offline-land', style: { color: '#51697b', weight: 1, fillColor: '#243b4a', fillOpacity: 1 },
    attribution: 'Offline coastline: Natural Earth (public domain)' }).addTo(activeMap);
  if (props.overview) {
    for (const [name, lat, lng] of [['北京', 39.90, 116.40], ['沈阳', 41.80, 123.43], ['上海', 31.23, 121.47], ['西安', 34.34, 108.94], ['成都', 30.57, 104.07], ['广州', 23.13, 113.26]] as [string, number, number][]) {
      L.circleMarker([lat, lng], { radius: 3, color: '#7fe1ef', weight: 1, fillOpacity: 1 })
        .bindTooltip(textTooltip(name), { permanent: true, direction: 'right', className: 'overview-city' }).addTo(map);
    }
  }
  let firstShown: L.TileLayer | null = null;
  for (const cfg of TILE_LAYERS) {
    if (cfg.enabled === false) continue; // 高德 GCJ-02 偏移：与 Folium 版一样保持隐藏
    const layer = L.tileLayer(cfg.url, {
      attribution: cfg.attr, maxZoom: 19, maxNativeZoom: cfg.maxNativeZoom,
    });
    const missing=new Set<string>();missingTiles.set(cfg.name,missing);
    const tileKey=(event:L.TileEvent)=>`${event.coords.z}/${event.coords.x}/${event.coords.y}`;
    layer.on('tileerror',(event:L.TileErrorEvent)=>{missing.add(tileKey(event));refreshTileFailures();});
    const clearTile=(event:L.TileEvent)=>{missing.delete(tileKey(event));refreshTileFailures();};
    layer.on('tileload',clearTile);layer.on('tileunload',clearTile);
    baseLayers[cfg.name] = layer;
    if (cfg.show) { layer.addTo(map); firstShown = layer; }
  }
  if (!firstShown) baseLayers[TILE_LAYERS[0].name]?.addTo(map);
  L.control.layers(baseLayers, {}, { position: "topright", collapsed: true }).addTo(map);
  map.on("baselayerchange", (e: L.LayersControlEvent) => { terrainBase.value = e.name === "🏔️ 战术地形图";offlineBase.value=false;refreshTileFailures(); });
  for (const name of Object.keys(visible)) overlays[name] = L.layerGroup().addTo(map);

  // 全屏展开（folium plugins.Fullscreen 等价）
  const Fullscreen = L.Control.extend({
    options: { position: "topleft" },
    onAdd: () => {
      const btn = L.DomUtil.create("a", "leaflet-control-fullscreen leaflet-bar leaflet-control");
      btn.title = "展开全屏战术地图";
      btn.textContent = "⛶";
      btn.style.cssText = "display:flex;align-items:center;justify-content:center;font-size:18px;text-decoration:none;cursor:pointer;";
      L.DomEvent.on(btn, "click", (e) => {
        L.DomEvent.stop(e);
        if (document.fullscreenElement) void document.exitFullscreen();
        else void el.value?.requestFullscreen();
      });
      return btn;
    },
  });
  new Fullscreen().addTo(map);

  layerGroup = L.layerGroup().addTo(map);
  commandLayer = L.layerGroup().addTo(map);
  plottingLayer=L.layerGroup().addTo(map);
  unitStackLayer=L.layerGroup().addTo(map);
  map.on('zoomend moveend resize',scheduleUnitStacks);
  map.on("zoomend",drawPlotting);
  render();
  drawPlotting();
  drawCommandPreview();
  sizeObserver = new ResizeObserver(() => map?.invalidateSize({ pan: false }));
  sizeObserver.observe(el.value);
});

// Metadata, chat and elapsed-time updates must not traverse/rebuild the world.
// Committed snapshots replace these references; selection only changes a class.
watch(() => [props.snap?.session_id, props.snap?.war_state, props.snap?.last_war_state,
  props.snap?.battlefield, props.selftest], scheduleRender);
watch(() => props.selectedUnit, updateSelectedUnit);
watch(() => props.commandPreview, drawCommandPreview, { deep: true });
watch(() => [props.picking,props.plotPicking], value => { if (value.some(Boolean)) map?.closePopup();scheduleUnitStacks(); });
watch(visible, drawBattlefield);
watch(showAnnotations,drawPlotting);
watch(()=>props.plotPreview,drawPlotting,{deep:true});
watch(()=>props.snap?.plotting,(value,old)=>{if(JSON.stringify(value?.unit_symbols)!==JSON.stringify(old?.unit_symbols))scheduleRender();else drawPlotting();});

onBeforeUnmount(() => { if (renderFrame) cancelAnimationFrame(renderFrame);if(stackFrame)cancelAnimationFrame(stackFrame);unitMarkers.clear();unitMarkerOffsets.clear(); el.value?.removeEventListener('click', captureMoveTarget, true); sizeObserver?.disconnect(); map?.remove(); map = null; });
</script>

<template>
  <div class="map-shell" :class="{ 'hide-unit-labels': !showUnitLabels, 'command-picking': !!picking }">
    <div v-if="deploymentGap" class="deployment-gap" role="status" data-testid="history-deployment-gap">
      <strong>史料事件已载入，部队部署未就绪</strong>
      <span>已登记{{deploymentGap.references}}项参战参考，已定位部队为0。地图圆圈是地名参考点，不能用于单位操控或交战验证；缺载阵地不会自动编造。</span>
    </div>
    <Teleport defer :to="toolbarTarget || 'body'" :disabled="!toolbarTarget">
    <div v-if="!overview" class="map-toolbar" aria-label="战场地图图层">
      <button @click="toggleTerrainBase" :aria-pressed="terrainBase">{{ terrainBase ? '卫星底图' : '地形底图' }}</button>
      <button v-if="snap?.war_state?.air_operations?.missions.length" @click="focusAirRoutes">定位航空航路</button>
      <label><input type="checkbox" v-model="showUnitLabels" />单位标注</label>
      <label><input type="checkbox" v-model="showAnnotations" />军事标图 {{snap?.plotting?.items.length??0}}</label>
      <span v-if="snap?.war_state?.history_replay" class="map-key">史料地名参考点 · 非本帧部队部署 · 不补写缺载射界、火力或补给线</span>
      <template v-else>
      <label><input type="checkbox" v-model="visible.terrain" />地形要素 {{ view?.terrain.features.length || '未记录' }}</label>
      <label><input type="checkbox" v-model="visible.sectors" />射界 {{ view?.fields_of_fire.length || '未记录' }}</label>
      <label><input type="checkbox" v-model="visible.ranges" />火力射程 {{ view?.fire_ranges.length ?? 0 }}</label>
      <label><input type="checkbox" v-model="visible.supply" />补给线 {{ view?.supply_lines.length || '未记录' }}</label>
      <span class="map-key">虚线：估计 · 红色补给线：受阻 · 射界未算遮挡</span>
      <span v-if="snap?.war_state?.air_operations?.missions.length" class="map-key">青/紫色航路：本轮航空任务</span>
      </template>
    </div>
    </Teleport>
    <div ref="el" class="map-fill" role="region" :aria-label="overview ? (snap?.war_state ? '想定部署地图' : '中国地图') : '战场态势地图'"></div>
    <MapUnitLocator v-if="!overview&&mapEntries.length" :units="mapEntries" :groups="unitStacks" :selected="selectedMapId" :picking="!!picking||!!plotPicking" @select="selectMapEntry" />
    <div v-if="tileFailures||offlineBase" class="base-status" role="status" data-testid="map-base-status"><span>{{offlineBase?'离线地理轮廓 · 无道路与高程':'在线底图部分未载入 · '+tileFailures+'块瓦片'}}</span><button v-if="!offlineBase" type="button" @click="useOfflineBase">仅显示离线轮廓</button><button v-else type="button" @click="restoreOnlineBase">恢复在线底图</button></div>
  </div>
</template>

<style scoped>
.map-shell { position:relative;width: 100%; height: 100%; display: flex; flex-direction: column; isolation: isolate; }
.deployment-gap{position:absolute;z-index:500;bottom:30px;left:12px;right:12px;max-width:540px;pointer-events:none;padding:12px 18px;background:var(--panel);border-left:2px solid #ad8b53;color:var(--muted);font-size:12px;line-height:1.7}
.deployment-gap strong{display:block;color:#ead6b1;font-size:13px}
.map-fill { width: 100%; flex: 1; min-height: 180px; }
/* SVG outlines use the path's bounding rectangle, not the military geometry.
   Keyboard users get a glow along the actual path instead of a large box. */
.map-fill :deep(path.leaflet-interactive:focus) { outline: none; }
.map-fill :deep(path.leaflet-interactive:focus-visible) {
  filter: drop-shadow(0 0 1px #071d2b) drop-shadow(0 0 3px #ffda73);
}
.map-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 6px 14px; padding: 7px 12px; background: var(--panel); border-bottom: 1px solid var(--line); font-size: 12px; }
.map-toolbar button { padding: 4px 8px; font-size: 12px; }
.map-toolbar label { display: flex; align-items: center; gap: 4px; white-space: nowrap; cursor: pointer; }
.map-toolbar input { accent-color: var(--accent); }
.map-key { font-size: 11px; color: var(--muted); }
.base-status{position:absolute;right:12px;bottom:30px;z-index:800;display:flex;align-items:center;gap:10px;max-width:calc(100% - 24px);padding:6px 9px;background:#102536ed;border:1px solid #456173;border-radius:4px;color:#bbced8;font-size:11px}.base-status button{font-size:11px;padding:3px 7px;min-height:28px;white-space:nowrap}.base-status span{overflow-wrap:anywhere}
</style>

<style>
/* Folium DivIcon 等价：去掉 Leaflet 默认的白底边框 */
.nato-marker { background: transparent; border: none; }
.unit-stack-marker{background:transparent;border:0;pointer-events:none}
.unit-stack-button{pointer-events:auto;min-width:34px;min-height:26px;padding:2px 6px;background:#142d3cf2;color:#ead59d;border:1px solid #9a8859;border-radius:12px;font-size:11px;box-shadow:0 2px 5px #030d17a0;white-space:nowrap}
.unit-stack-button:focus-visible{outline:2px solid #91d1d0;outline-offset:2px}
.unit-stack-popup .leaflet-popup-content-wrapper,.unit-stack-popup .leaflet-popup-tip{background:#102638;color:#d9e7ed}
.unit-stack-list>strong{display:block;margin-bottom:6px}.unit-stack-list>p{font-size:11px;color:#a6bdc8;margin:5px 0 9px}
.unit-stack-list>button{display:grid;gap:3px;width:100%;min-height:44px;padding:8px 5px;border:0;border-top:1px solid #355063;border-radius:0;background:transparent;text-align:left;font-size:12px}
.unit-stack-list>button:hover{background:#1a3a4e}.unit-stack-list>button:focus-visible{outline:2px solid #8bd3d4}.unit-stack-list small{font-size:10px;color:#9db5c1;overflow-wrap:anywhere}.unit-stack-list .red>span{color:#efaca8}.unit-stack-list .blue>span{color:#a9c8ee}
.nato-marker.campaign-staging{opacity:.55;outline:1px dashed #b9c5ca;outline-offset:3px}
.operation-participation{position:absolute;left:50%;top:-18px;transform:translateX(-50%);white-space:nowrap;padding:1px 4px;border:1px solid var(--warn);background:var(--panel);color:var(--text);font-size:10px;line-height:15px;pointer-events:none}
.nato-marker.command-selected { filter: drop-shadow(0 0 5px #ffe196); outline: 2px solid #ffe196; outline-offset: 5px; border-radius: 2px; }
.fire-marker { background: transparent; border: none; font-size: 20px; text-align: center; pointer-events: none; }
.trail-arrow { background: transparent; border: none; }
.supply-node { background: #222b38; color: #f0c777; border: 1px solid #f0c777; text-align: center; font-size: 17px; line-height: 20px; }
.command-picking .leaflet-popup-pane { visibility: hidden; pointer-events: none; }

/* folium plugins.AntPath 的 CSS 动画等价：行军蚂蚁线 / 火力曳光线 */
.ant-march { stroke-dasharray: 15 20; animation: antdash 1.6s linear infinite; }
.ant-fire { stroke-dasharray: 5 20; animation: antdash 0.8s linear infinite; }
@keyframes antdash { to { stroke-dashoffset: -35; } }
@media (prefers-reduced-motion: reduce) { .ant-march, .ant-fire { animation: none; } }
</style>
