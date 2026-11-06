import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(fs.realpathSync(process.argv[2]));const {chromium}=require('playwright-core');
const root='.cache/qa/state-observation-map-2026-11-01';const browser=await chromium.launch({channel:'chrome',headless:true});
const page=await browser.newPage();const checks=[],errors=[];
page.on('pageerror',e=>errors.push(String(e)));const check=(value,label)=>{if(!value)throw Error(label);checks.push(label);};
async function groups(){return page.evaluate(()=>{
 const map=document.querySelector('.map-fill').getBoundingClientRect();const rows=[...document.querySelectorAll('.nato-marker')].map(e=>({id:e.dataset.mapUnitId,b:e.getBoundingClientRect()})).filter(r=>r.b.right>=map.left&&r.b.left<=map.right&&r.b.bottom>=map.top&&r.b.top<=map.bottom);
 const pending=new Set(rows.map((_,i)=>i)),out=[];
 while(pending.size){const group=[],todo=[pending.values().next().value];pending.delete(todo[0]);while(todo.length){const i=todo.pop();group.push(rows[i].id);for(const j of [...pending]){const a=rows[i].b,b=rows[j].b;if(a.left<=b.right+.01&&a.right+.01>=b.left&&a.top<=b.bottom+.01&&a.bottom+.01>=b.top){todo.push(j);pending.delete(j);}}}out.push(group.sort());}return out;
});}
async function checkGroups(label){
 await page.waitForTimeout(100);const expected=(await groups()).filter(g=>g.length>1).map(g=>g.length).sort((a,b)=>a-b);
 const actual=await page.locator('.unit-stack-button').evaluateAll(es=>es.map(e=>Number(e.dataset.stackCount)).sort((a,b)=>a-b));
 check(JSON.stringify(expected)===JSON.stringify(actual),label+' rectangles and visible count badges agree');return expected;
}
async function allSelections(count,label){
 const trigger=page.getByTestId('map-unit-locator').locator('.locator-trigger');await trigger.click();const ids=await page.locator('[data-locate-unit]').evaluateAll(es=>es.map(e=>e.dataset.locateUnit));check(new Set(ids).size===count,label+' stable unique selection IDs');
 for(let i=0;i<ids.length;i++){
  if(i)await trigger.click();await page.locator('[data-locate-unit]').nth(i).click();
  const selected=await page.locator('.nato-marker.command-selected').getAttribute('data-map-unit-id');check(selected===ids[i],label+' selectsID '+ids[i]);
 }
 return ids;
}
try{
 for(const count of [22,34])for(const width of [1440,900]){
  const label=count+'units '+width;await page.setViewportSize({width,height:900});await page.goto('http://127.0.0.1:19134/?count='+count);
  await page.locator('.nato-marker').nth(count-1).waitFor();await page.getByTestId('map-unit-locator').waitFor();
  const before=await page.evaluate(()=>JSON.stringify(window.qa.snap));check(await page.locator('.nato-marker').count()===count,label+' keeps every physical marker');
  const sizes=await checkGroups(label);check(sizes.length>0,label+' actual overlap reproduced');
  // A rendered count button must expose a complete connected component, not24px neighbors.
  let opened=false;
  for(const button of await page.locator('.unit-stack-button').all()){
   try{await button.click({timeout:1500});opened=true;break;}catch{}
  }
  check(opened,label+' count badge is pointer reachable');const popup=page.locator('.unit-stack-popup');await popup.waitFor();
  const popupIds=await popup.locator('[data-stack-member]').evaluateAll(es=>es.map(e=>e.dataset.stackMember).sort());
  check((await groups()).some(g=>JSON.stringify(g)===JSON.stringify(popupIds)),label+' popup lists full overlap component');
  await popup.locator('[data-stack-member]').last().click();
  await allSelections(count,label);
  check(await page.evaluate(()=>JSON.stringify(window.qa.snap))===before,label+' selections do not mutate any world field');
  const trigger=page.getByTestId('map-unit-locator').locator('.locator-trigger');await trigger.click();
  const q=await page.locator('[data-locate-unit]').first().locator('.locator-name').innerText();
  await page.getByRole('searchbox',{name:'地图单位搜索'}).fill(q.split(' · ').slice(1).join(' · '));check(await page.locator('[data-locate-unit]').count()>=1,label+' searchable unit list');
  await page.getByRole('searchbox',{name:'地图单位搜索'}).press('Escape');check(await trigger.getAttribute('aria-expanded')==='false',label+' Escape closes locator');
  check(await trigger.evaluate(e=>e===document.activeElement),label+' Escape returns focus');
  await page.locator('.leaflet-control-zoom-out').click();await page.waitForTimeout(400);await checkGroups(label+' zoom out');
  await page.locator('.leaflet-control-zoom-in').click();await page.waitForTimeout(400);await checkGroups(label+' zoom in');
  await page.screenshot({path:root+`/map-${count}-${width}.png`});
 }
 // Controlled network failure verifies truthful offline fallback, without inventing terrain.
 await page.route('**/MapServer/tile/**',route=>route.abort());await page.goto('http://127.0.0.1:19134/?count=22');
 await page.getByTestId('map-base-status').waitFor();await page.getByRole('button',{name:'仅显示离线轮廓',exact:true}).click();
 check((await page.getByTestId('map-base-status').innerText()).includes('无道路与高程'),'offline fallback states geographic limits');
 check(await page.locator('.nato-marker').count()===22,'offline fallback preserves every military marker');
 await page.screenshot({path:root+'/map-offline-fallback.png'});await page.unroute('**/MapServer/tile/**');
 check(errors.length===0,'no browser application errors');
 fs.writeFileSync(root+'/map-browser-review.json',JSON.stringify({passed:true,checks,count:checks.length,errors,scope:'Actual MapView and components with captured real22/34snapshots; no backend physics or model call'},null,2));console.log('PASS',checks.length,'map checks');
}catch(e){fs.writeFileSync(root+'/map-browser-failure.json',JSON.stringify({error:String(e),checks,errors},null,2));await page.screenshot({path:root+'/map-failure.png'});throw e;}
finally{await browser.close();}
