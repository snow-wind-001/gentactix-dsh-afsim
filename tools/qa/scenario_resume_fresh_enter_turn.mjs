/** Actual cold-open of the independently generated draft and bilateral control. */
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(fs.realpathSync(process.argv[2]));const {chromium}=require('playwright-core');
const root='.cache/qa/scenario-resume-2026-11-01',generated=JSON.parse(fs.readFileSync(root+'/fresh-generation-response.json'));
if(generated.http!==200)throw Error('Fresh actual generation not passed');
const browser=await chromium.launch({channel:'chrome',headless:true});const page=await browser.newPage({viewport:{width:1440,height:1000}});
const get=async url=>{const r=await fetch(url);if(!r.ok)throw Error('GET '+r.status);return r.json();};
try{
 await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19132'});await page.goto('http://127.0.0.1:19089/');
 if(process.argv[3]==='--reuse-initial'){
  const saved=JSON.parse(fs.readFileSync(root+'/fresh-initial-response.json'));page.__resumeSnapshot=await get('http://127.0.0.1:19132/api/sessions/'+saved.session_id);
  if(page.__resumeSnapshot.turn_count!==0)throw Error('Reuse requires unadvanced actual QA world');
  await page.getByRole('tab',{name:/已保存战局/}).click();await page.locator(`[data-session-id="${saved.session_id}"] .open-battle`).click();await page.getByTestId('map-workbench').waitFor();
 }else{
 await page.getByRole('textbox',{name:'搜索战役',exact:true}).fill('冀中');await page.locator('.battle-option').filter({hasText:'冀中五一反扫荡'}).click();await page.getByRole('button',{name:/继续配置/}).click();
 await page.locator('#draft-mode').selectOption('historical');await page.locator('#draft-executor').selectOption('afsim');await page.locator('[data-admission-choice="1.0.0:campaign"]').click();await page.locator('#draft-step').selectOption('6小时');
 await page.getByTestId('completed-historical-configurations').locator('summary').click();await page.locator(`[data-open-configuration="${generated.body.id}"]`).click();
 await page.getByTestId('historical-validation').waitFor();if(await page.getByTestId('legacy-campaign-delay').count())throw Error('New independent generation must contain explicit defensive policy');
 page.__resumeResult=generated;page.__enterScope='Actual frontend cold-open/entry of independently generated complete34Nativeconfiguration, no replay';const enter=eval('('+fs.readFileSync('tools/qa/scenario_resume_enter.js','utf8')+')');console.log('ENTER',JSON.stringify(await enter(page)));
 }
 const before=page.__resumeSnapshot,sid=before.session_id,url='http://127.0.0.1:19132/api/sessions/'+sid,w=before.war_state;
 fs.writeFileSync(root+'/fresh-initial-response.json',JSON.stringify(before));
 const q=await get(url+'/commands');const orders=q.units.filter(u=>u.available).map(u=>({unit_id:u.id,action:'hold',duration:'next'}));const moving=[];
 for(const side of ['red','blue']){
  const unit=w[side+'_units'].find(u=>w.campaign.actors[u.name].active&&u.formation.signal>0&&(!u.formation.motorized||u.formation.fuel_liters>0));if(!unit)throw Error('No eligible '+side+' unit');
  const center=generated.body.parameters.area.center,dx=center.lat-unit.lat,dy=center.lng-unit.lng,n=Math.hypot(dx,dy)||1;
  const target={lat:unit.lat+(n===1&&dx===0&&dy===0?.003:dx/n*.004),lng:unit.lng+dy/n*.004};
  const command=q.units.find(u=>u.name===unit.name);if(!command)throw Error('Command identity missing');
  const row=orders.find(o=>o.unit_id===command.id);if(!row)throw Error('Selected unit unavailable');Object.assign(row,{action:'move',destination:target});moving.push({team:side,name:unit.name,start:{lat:unit.lat,lng:unit.lng},target});
 }
 const queued=await page.request.put(url+'/commands',{data:{expected_turn:q.turn,revision:q.revision,world_version:q.world_version,control_team:'red',director:true,no_fire:true,unit_agents:[],orders}});
 if(!queued.ok())throw Error('Control rejected '+await queued.text());if(JSON.stringify((await get(url)).war_state)!==JSON.stringify(w))throw Error('Queue changed world');
 // Refresh the same saved world so CommandCenter owns the current queue revision.
 await page.reload();await page.getByRole('button',{name:/继续当前推演|返回推演/}).first().click().catch(async()=>{await page.getByRole('tab',{name:/已保存战局/}).click();await page.locator(`[data-session-id="${sid}"] .open-battle`).click();});
 await page.getByTestId('map-workbench').waitFor();let response=null;page.on('response',async r=>{if(r.url()===url+'/next'&&r.request().method()==='POST')response={http:r.status(),body:await r.json()};});
 await page.getByRole('button',{name:'推进一轮',exact:true}).click();console.log('MOVE_ADVANCE',JSON.stringify({session_id:sid,moving,orders:orders.length}));
 const until=Date.now()+900000;while(!response&&Date.now()<until)await new Promise(r=>setTimeout(r,1000));
 fs.writeFileSync(root+'/fresh-turn-response.json',JSON.stringify(response));if(response?.http!==200)throw Error('Turn failed '+JSON.stringify(response?.body?.detail));
 const after=await get(url);fs.writeFileSync(root+'/fresh-post-turn-response.json',JSON.stringify(after));
 for(const move of moving){const unit=after.war_state[move.team+'_units'].find(u=>u.name===move.name);if(Math.hypot(unit.lat-move.start.lat,unit.lng-move.start.lng)<.0001)throw Error('Selected '+move.team+' did not move');}
 const result={passed:true,session_id:sid,actors:34,markers:await page.locator('.nato-marker').count(),orders:orders.length,moved:moving,
  elapsed_seconds:after.war_state.simulation_clock.elapsed_seconds,returncode:after.afsim.returncode,
  scope:'Independent full34model generation then actual saved-draft UI entry, API bilateral movement/no_fire and frontend6hadvance; not historical combat or model autonomy'};
 fs.writeFileSync(root+'/fresh-control-review.json',JSON.stringify(result,null,2));await page.screenshot({path:root+'/browser-fresh-34-after-movement.png'});console.log('COMPLETE',JSON.stringify({session_id:sid,moved_sides:2,actors:34,elapsed_seconds:result.elapsed_seconds}));
}finally{await browser.close();}
