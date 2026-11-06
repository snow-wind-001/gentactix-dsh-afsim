/** Real map command, Native SDK unit decisions, AFSIM execution and reload. */
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire('/home/spikebai/.nvm/versions/node/v22.20.0/lib/node_modules/@playwright/cli/package.json');
const {chromium}=require('playwright-core');
const base=process.argv[3]??'.cache/qa/transfer-window-2026-11-03/live-final',attempt=process.argv[2]??'browser';
if(!/^[a-z0-9-]+$/.test(attempt))throw Error('Invalid QA attempt');const root=base+'/'+attempt;
if(fs.existsSync(root))throw Error('Preserve earlier browser evidence');fs.mkdirSync(root);
const info=JSON.parse(fs.readFileSync(base+'/live-case.json','utf8')),api=info.api+'/api/sessions/'+info.session_id;
const actorCount=info.actor_count??4,goalCount=info.goal_count??6,nativeCount=info.native_decision_count??2,stepSeconds=info.step_seconds??1800;
const get=async path=>{const r=await fetch(api+path);if(!r.ok)throw Error('HTTP '+r.status+' '+path);return r.json();};
const checks=[],errors=[],requests=[];
function check(v,label){if(!v)throw Error(label);checks.push(label);}
const browser=await chromium.launch({channel:'chrome',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(['PUT','POST'].includes(r.method()))requests.push({method:r.method(),path:new URL(r.url()).pathname});});
await page.addInitScript(({api,sid})=>{window.gentactix={backendUrl:api};localStorage.setItem('gentactix-session',sid);},{api:info.api,sid:info.session_id});
try{
 const before=(await get('/export')).session;fs.writeFileSync(root+'/before.json',JSON.stringify(before));
 await page.goto(info.ui,{waitUntil:'domcontentloaded'});
 const workbench=page.getByTestId('map-workbench'),saved=page.getByRole('tab',{name:/已保存战局/});
 await Promise.race([workbench.waitFor(),saved.waitFor()]);
 if(!await workbench.isVisible()){await saved.click();await page.locator(`[data-session-id="${info.session_id}"] .open-battle`).click();}
 await workbench.waitFor();
 await page.getByRole('button',{name:/^目标与运行/}).click();
 await page.getByTestId('single-team-goals').waitFor();
 const panel=page.getByTestId('mission-panel');
 check(!(await panel.innerText()).includes('双方同时达标'),'solo window does not claim a two-sided draw');
 check(!(await panel.innerText()).includes('蓝方连续达标'),'inactive side has no misleading progress');
 check(await panel.locator('[data-goal-id]').count()===goalCount,'all source-window goals visible');
 await page.getByTestId('command-toggle').click();
 const command=page.getByTestId('command-panel');await command.waitFor({state:'visible'});
 const menu=command.getByLabel('单位名单（含无坐标单位）');
 check(await menu.locator('option').count()===actorCount+1,'all formation identities in command menu, no command-HQ infantry');
 await menu.selectOption(info.command_unit);
 const actions=await page.getByTestId('unit-action').locator('option').evaluateAll(rows=>rows.map(r=>r.value));
 check(!actions.some(a=>['fire','bombard','air_support','capture'].includes(a)),'no fictional enemy attack or surrender actions');
 await page.getByTestId('unit-action').selectOption('move');
 await command.getByLabel('持续方式').selectOption('until_arrived');
 await command.getByRole('button',{name:'地图选目的地',exact:true}).click();
 const map=page.locator('.leaflet-container').first(),box=await map.boundingBox();
 check(!!box,'interactive map available');await map.click({position:{x:box.width*.52,y:box.height*.52}});
 await command.waitFor({state:'visible'});await page.getByTestId('map-destination').waitFor();
 check((await page.getByTestId('map-destination').innerText()).includes('目的地 '),'map click supplies coordinates without natural-language coordinates');
 await page.getByTestId('enqueue-order').click();
 await page.waitForFunction(()=>!document.querySelector('[data-testid="enqueue-order"]')?.disabled);
 const queued=await get('/commands');
 check(queued.orders.some(r=>r.unit_id===info.command_unit&&r.action==='move'&&r.duration==='until_arrived'),'map-selected move queued by UI');
 check(queued.unit_agents.length===nativeCount,'existing Native assignments retained by UI queue edit');
 check(JSON.stringify((await get('/export')).session.war_state)===JSON.stringify(before.war_state),'queueing a map command does not change the physical world');
 await page.screenshot({path:root+'/queued-map-command-1440.png'});
 await command.getByRole('button',{name:'收起指挥面板'}).click();
 await page.getByRole('button',{name:'推进一轮',exact:true}).click();
 let running;const deadline=Date.now()+120000;
 while(Date.now()<deadline){const p=await get('/progress');if(p.active&&p.progress.wall_elapsed_ms>=4000){running=p;break;}await page.waitForTimeout(250);}
 check(!!running,'actual Native operation observed');fs.writeFileSync(root+'/running.json',JSON.stringify(running,null,2));
 await page.reload();await page.getByTestId('map-workbench').waitFor({timeout:60000});
 const recovered=await get('/progress');
 check(recovered.active&&recovered.operation_id===running.operation_id,'reload retains one actual in-flight operation');
 check(await page.locator('.advance-button').isDisabled(),'duplicate turn blocked during actual operation');
 await page.screenshot({path:root+'/running-reloaded-1440.png'});
 console.log('ACTUAL_NATIVE_RUNNING',info.session_id,running.operation_id);
 let terminal;const end=Date.now()+1500000;
 while(Date.now()<end){const p=await get('/progress');if(!p.active&&p.last_operation?.operation_id===running.operation_id){terminal=p;break;}await page.waitForTimeout(500);}
 check(!!terminal,'actual operation reaches a durable terminal result');
 fs.writeFileSync(root+'/terminal.json',JSON.stringify(terminal,null,2));
 check(terminal.last_operation.outcome==='success','actual '+(info.engine??'afsim')+' turn succeeds');
 const after=(await get('/export')).session;fs.writeFileSync(root+'/after.json',JSON.stringify(after));
 check(after.turn_count===before.turn_count+1,'actual turn commits exactly once');
 check(after.war_state.simulation_clock.elapsed_seconds-before.war_state.simulation_clock.elapsed_seconds===stepSeconds,'clock advances exactly the configured step');
 check(after.war_state.red_units.length===actorCount&&after.war_state.blue_units.length===0,'all formations retained with no invented enemy');
 check(after.command_state.receipts.filter(r=>r.turn===after.turn_count).length===actorCount,'all execution receipts retained');
 const native=after.trajectory.at(-1).decisions.filter(d=>d.source==='native_unit_agent');
 check(native.length===nativeCount&&native.every(d=>d.proposal?.source==='dsh_native_unit_order_tool'),'actual Native structured decisions bound to units');
 check(after.war_state.mission.status==='active','one physical round does not pretend to complete the historical transfer');
 check(after.war_state.campaign_plan.outcomes.blue===false,'empty opposing goals stay false after native execution');
 check(requests.filter(r=>r.path.endsWith('/next')).length===1,'reload never duplicates physical execution');
 await page.getByRole('button',{name:/^目标与运行/}).click();await page.getByTestId('single-team-goals').waitFor();
 await page.screenshot({path:root+'/committed-goals-1440.png'});
 await page.setViewportSize({width:900,height:1000});await page.screenshot({path:root+'/committed-goals-900.png'});
 check(errors.length===0,'no browser application exceptions');
 fs.writeFileSync(root+'/result.json',JSON.stringify({passed:true,actual_model:true,actual_afsim:(info.engine??'afsim')==='afsim',checks,count:checks.length,errors,requests,session_id:info.session_id,operation:terminal.last_operation,
  scope:`Estimated ${actorCount}-formation window; one actual turn and map control. Not full historical calibration.`},null,2));
 console.log('PASS',checks.length,'map/Native/AFSIM checks');
}catch(error){
 const snapshot=await get('/export').catch(()=>null);if(snapshot&&!fs.existsSync(root+'/after.json'))fs.writeFileSync(root+'/after.json',JSON.stringify(snapshot.session));
 fs.writeFileSync(root+'/result.json',JSON.stringify({passed:false,error:String(error),checks,errors,requests},null,2));
 await page.screenshot({path:root+'/failure.png'}).catch(()=>{});throw error;
}finally{await browser.close();}
