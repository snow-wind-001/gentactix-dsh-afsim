/** Continue the retained actual case, including SDK resume after a host restart. */
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire('/home/spikebai/.nvm/versions/node/v22.20.0/lib/node_modules/@playwright/cli/package.json');
const {chromium}=require('playwright-core');
const base=process.argv[2]??'.cache/qa/transfer-window-2026-11-03/live-final',root=base+'/continuation';
if(fs.existsSync(root))throw Error('Preserve previous evidence');fs.mkdirSync(root);
const info=JSON.parse(fs.readFileSync(base+'/live-case.json','utf8')),url=info.api+'/api/sessions/'+info.session_id;
const actorCount=info.actor_count??4,nativeCount=info.native_decision_count??2,stepSeconds=info.step_seconds??1800;
async function call(path,body,method){const response=await fetch(url+path,{method:method??(body?'POST':'GET'),headers:{'Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{})});if(!response.ok)throw Error(response.status+' '+await response.text());return response.json();}
const browser=await chromium.launch({channel:'chrome',headless:true}),page=await browser.newPage({viewport:{width:1440,height:1000}});
const errors=[],checks=[],rounds=[];page.on('pageerror',e=>errors.push(e.message));
function check(v,label){if(!v)throw Error(label);checks.push(label);}
await page.addInitScript(i=>{window.gentactix={backendUrl:i.api};localStorage.setItem('gentactix-session',i.session_id);},info);
try{
 const original=(await call('/export')).session;
 check(original.turn_count===1&&original.war_state.mission.status==='active','retained T1 is active');
 const bindings=original.command_state.agent_sessions;check(Object.keys(bindings).length===nativeCount,'durable Native unit bindings exist');
 const targets=Object.fromEntries(original.war_state.mission.definition.campaign_plan.nodes.filter(n=>n.condition.kind==='reach').map(n=>[n.unit_ids[0],n.condition.region.center]));
 await page.goto(info.ui,{waitUntil:'domcontentloaded'});
 const workbench=page.getByTestId('map-workbench'),saved=page.getByRole('tab',{name:/已保存战局/});
 await Promise.race([workbench.waitFor(),saved.waitFor()]);
 if(!await workbench.isVisible()){await saved.click();await page.locator(`[data-session-id="${info.session_id}"] .open-battle`).click();}
 await workbench.waitFor();
 async function run(label,native){
  const before=(await call('/export')).session,view=await call('/commands');
  const byName=Object.fromEntries(before.war_state.red_units.map(u=>[u.name,u]));
  const orders=view.units.filter(u=>!native||!view.unit_agents.includes(u.id)).map(u=>({unit_id:u.id,action:'move',duration:'until_arrived',destination:targets[byName[u.name].historical_unit_id]}));
  await call('/commands',{expected_turn:view.turn,revision:view.revision,world_version:view.world_version,orders,
   control_team:'red',director:false,no_fire:true,unit_agents:native?view.unit_agents:[],intent:view.intent},'PUT');
  check(JSON.stringify((await call('/export')).session.war_state)===JSON.stringify(before.war_state),label+' command preparation preserves physics');
  let posts=0;const listener=r=>{if(r.method()==='POST'&&r.url().endsWith('/next'))posts++;};page.on('request',listener);
  await page.getByRole('button',{name:'推进一轮',exact:true}).click();
  let terminal;const started=Date.now();while(Date.now()-started<1500000){
   const p=await call('/progress');if(!p.active&&p.last_operation?.label==='推演 T+'+(before.turn_count+1)){terminal=p.last_operation;break;}await page.waitForTimeout(500);
  }
  check(terminal?.outcome==='success',label+' actual turn succeeds');
  const after=(await call('/export')).session;fs.writeFileSync(root+'/'+label+'.json',JSON.stringify(after));
  check(after.turn_count===before.turn_count+1&&after.war_state.simulation_clock.elapsed_seconds-before.war_state.simulation_clock.elapsed_seconds===stepSeconds,label+' one commit and exact clock');
  check(after.war_state.red_units.length===actorCount&&!after.war_state.blue_units.length,label+' source roster retained');
  check(after.command_state.receipts.filter(r=>r.turn===after.turn_count).length===actorCount,label+' all actor receipts present');
  check(after.war_state.campaign_plan.outcomes.blue===false,label+' inactive outcome remains false');
  check(posts===1,label+' exactly one frontend advance request');page.off('request',listener);
  if(native){
   const decisions=after.trajectory.at(-1).decisions.filter(d=>d.source==='native_unit_agent');
   check(decisions.length===nativeCount&&decisions.every(d=>d.proposal?.source==='dsh_native_unit_order_tool'),label+' structured Native decisions consumed after cold restore');
   for(const [id,binding] of Object.entries(bindings))check(after.command_state.agent_sessions[id].session_id===binding.session_id,label+' original SDK session preserved for '+id);
  }
  rounds.push({label,turn:after.turn_count,status:after.war_state.mission.status,winner:after.war_state.mission.winner,wall_ms:terminal.wall_elapsed_ms,native});
  console.log(label,after.turn_count,after.war_state.mission.status,terminal.wall_elapsed_ms);
  await page.waitForFunction(()=>!document.querySelector('.advance-button')?.disabled||document.body.innerText.includes('已结算'));
  return after;
 }
 let current=await run('post-cold-native-t2',true);
 check(current.war_state.mission.status==='active','T2 does not prematurely finish all directions');
 for(let n=3;n<=(info.maximum_turn??7)&&current.war_state.mission.status==='active';n++)current=await run('all-armies-t'+n,false);
 check(current.war_state.mission.status==='completed'&&current.war_state.mission.winner==='red','all graph conditions produce a program-decided transfer completion');
 check(current.war_state.campaign_plan.side_progress.red===2&&current.war_state.campaign_plan.side_progress.blue===0,'continuous active-side requirement preserved');
 check(current.war_state.red_units.every(u=>u.personnel.current+u.personnel.casualties+u.personnel.noncombat_losses===u.personnel.committed),'personnel accounts conserved across native and manual turns');
 check(current.war_state.historical_initial.definition_hash===original.war_state.historical_initial.definition_hash,'historical source never rewritten');
 await page.getByRole('button',{name:/^目标与运行/}).click();await page.getByTestId('single-team-goals').waitFor();
 await page.screenshot({path:root+'/completed-1440.png'});await page.setViewportSize({width:900,height:1000});await page.screenshot({path:root+'/completed-900.png'});
 check(errors.length===0,'no application exceptions throughout continuation');
  fs.writeFileSync(root+'/result.json',JSON.stringify({passed:true,checks,count:checks.length,rounds,errors,scope:`Complete explicit ${actorCount}-formation calculation goals with original Native bindings and ${info.engine??'afsim'}; not full historical loss calibration.`},null,2));
 console.log('PASS',checks.length,'continuation checks');
}catch(error){fs.writeFileSync(root+'/result.json',JSON.stringify({passed:false,error:String(error),checks,rounds,errors},null,2));await page.screenshot({path:root+'/failure.png'}).catch(()=>{});throw error;}
finally{await browser.close();}
