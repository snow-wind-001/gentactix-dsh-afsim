import L from 'leaflet';
import { militarySvg,symbolById,teamColor } from './militarySymbols';
import {escapeHtml} from './tactical';
import type {PlotItem,PlottingView} from './types';
export function drawMilitaryPlotting(map:L.Map,layer:L.LayerGroup,data:PlottingView|undefined,preview:PlotItem[],select:(id:string)=>void){
 layer.clearLayers();const replaced=new Set(preview.map(x=>x.id));
 for(const item of [...(data?.items??[]).filter(x=>!replaced.has(x.id)),...preview]){
  if(!item.visible)continue;const spec=symbolById(item.symbol_id),isDraft=preview.includes(item),color=teamColor(item.team);
  const live=item.unit_id?data?.units.find(u=>u.id===item.unit_id)?.position:null;
  const points=(live?[live]:item.points).map(p=>L.latLng(p.lat,p.lng));if(!points.length)continue;
  const style={color,weight:2.4,dashArray:isDraft||item.status!=='observed'?'7 5':undefined,opacity:.95,className:'military-annotation plot-'+spec.geometry};
  let shape:L.Layer;
  if(spec.geometry==='point'){
   const anchor=spec.anchor.map(n=>n*1.5) as [number,number];
   if(live){
    // A linked callout follows the unit through a leader, leaving its command hit area free.
    const target=map.layerPointToLatLng(map.latLngToLayerPoint(points[0]).add(L.point(38,-30)));
    L.polyline([points[0],target],{color,weight:1,dashArray:'2 4',interactive:false,className:'plot-unit-leader'}).addTo(layer);
    anchor[0]-=38;anchor[1]+=30;
   }
   const icon=L.divIcon({className:'plot-marker '+item.status,iconSize:[36,36],iconAnchor:anchor,
    html:`<div class="military-unit">${militarySvg(item.symbol_id,item.team)}<span class="unit-name">${escapeHtml(isDraft?'草稿 · '+item.label:item.label||spec.label)}</span></div>`});
   shape=L.marker(points[0],{icon,bubblingMouseEvents:false,title:(isDraft?'草稿 · ':'')+(item.label||spec.label),keyboard:!isDraft});
   shape.on('add',()=>{const el=(shape as L.Marker).getElement();if(el){el.dataset.plotId=item.id;el.setAttribute('aria-label','军事标注 '+(item.label||spec.label));}});
  }else if(spec.geometry==='area')shape=L.polygon(points,{...style,fillColor:color,fillOpacity:isDraft ? .06 : .11});
  else{
   shape=L.polyline(points,style);
   if(['attack-axis','retreat-route','supply-route'].includes(item.symbol_id)&&points.length>1){
    const a=map.latLngToLayerPoint(points[points.length-2]),b=map.latLngToLayerPoint(points[points.length-1]),angle=Math.atan2(b.y-a.y,b.x-a.x),size=13;
    const wings=[L.point(b.x-size*Math.cos(angle-.5),b.y-size*Math.sin(angle-.5)),b,L.point(b.x-size*Math.cos(angle+.5),b.y-size*Math.sin(angle+.5))].map(p=>map.layerPointToLatLng(p));
    L.polyline(wings,{...style,dashArray:undefined,interactive:false}).addTo(layer);
   }
  }
  const status=item.status==='planned'?'行动计划':item.status==='observed'?'来源说明（未自动核验）':'教学假设';
  const tip=document.createElement('span');tip.textContent=`${isDraft?'草稿 · ':''}${item.label||spec.label} · ${status}`;shape.bindTooltip(tip);
  if(!isDraft)shape.on('click',(e:L.LeafletMouseEvent)=>{if(e.originalEvent)L.DomEvent.stop(e.originalEvent);select(item.id);});
  shape.addTo(layer);
 }
}
