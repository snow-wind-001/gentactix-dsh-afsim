/** One real frontend turn for both northern directions; never auto-retry a turn. */
import fs from 'node:fs';import {createRequire} from 'node:module';
const require=createRequire('/home/spikebai/.nvm/versions/node/v22.20.0/lib/node_modules/@playwright/cli/package.json');
const {chromium}=require('playwright-core');
const base=process.argv[2],engine=process.argv[3],attempt=process.argv[4],expected=Number(process.argv[5]);
if(!base||!['narrative','afsim'].includes(engine)||!/^[a-z0-9-]+$/.test(attempt)||!Number.isInteger(expected))throw Error('Require root, engine, unused attempt, expected turn');
const folder=base+'/'+engine,root=folder+'/'+attempt;if(fs.existsSync(root))throw Error('Preserve earlier evidence');fs.mkdirSync(root);
const info=JSON.parse(fs.readFileSync(folder+'/case.json')),url=info.api+'/api/sessions/'+info.session_id;
const ui=process.argv[6]||info.ui;
async function get(path){const r=await fetch(url+path);if(!r.ok)throw Error(r.status+' '+await r.text());return r.json();}
const checks=[],errors=[],writes=[];const check=(v,m)=>{if(!v)throw Error(m);checks.push(m);};
const browser=await chromium.launch({channel:'chrome',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(['PUT','POST','DELETE'].includes(r.method()))writes.push({method:r.method(),path:new URL(r.url()).pathname});});
await page.addInitScript(i=>{window.gentactix={backendUrl:i.api};localStorage.setItem('gentactix-session',i.session_id);},info);
try{
 const before=(await get('/export')).session;
 check(before.turn_count===expected-1&&before.war_state.mission.status==='active','expected original committed turn is active');
 check(!(await get('/progress')).active,'no other operation is in flight');
 fs.writeFileSync(root+'/before.json',JSON.stringify(before));
 await page.goto(ui,{waitUntil:'domcontentloaded'});
 const workbench=page.getByTestId('map-workbench'),saved=page.getByRole('tab',{name:/已保存战局/});
 await Promise.race([workbench.waitFor(),saved.waitFor()]);
 if(!await workbench.isVisible()){await saved.click();await page.locator(`[data-session-id="${info.session_id}"] .open-battle`).click();}
 await workbench.waitFor();
 await page.getByRole('button',{name:/^目标与运行/}).click();
 const goals=page.getByTestId('campaign-objectives');await goals.waitFor();
 check(await goals.locator('[data-goal-id]').count()===5,'all five two-sided direction goals visible');
 await goals.getByLabel('目标阵营',{exact:true}).selectOption('blue');
 check(await goals.locator('[data-goal-id]').count()===2,'blue has its own two operational goals');
 await goals.getByLabel('目标阵营',{exact:true}).selectOption('all');
 await page.getByRole('button',{name:/^目标与运行/}).click();
 if(expected===1){
  await page.getByTestId('command-toggle').click();const command=page.getByTestId('command-panel');await command.waitFor();
  const menu=command.getByLabel('单位名单（含无坐标单位）');
  check(await menu.locator('option').count()===9,'all eight historical identities available for visual command');
  await menu.selectOption(info.command_unit);await page.getByTestId('unit-action').selectOption('move');
  await command.getByLabel('持续方式').selectOption('until_arrived');
  await command.getByRole('button',{name:'地图选目的地',exact:true}).click();
  const box=await page.locator('.campaign-goal-region').first().boundingBox();
  check(!!box,'mountain goal has actual map geometry');await page.mouse.click(box.x+box.width/2,box.y+box.height/2);
  await command.waitFor();await page.getByTestId('map-destination').waitFor();
  await page.getByTestId('enqueue-order').click();await page.waitForFunction(()=>!document.querySelector('[data-testid="enqueue-order"]')?.disabled);
  const queued=await get('/commands');
  check(queued.orders.some(o=>o.unit_id===info.command_unit&&o.action==='move'),'visual command queued without typed coordinates');
  check(queued.unit_agents.length===2,'manual map order preserves red and blue Native agents');
  check(JSON.stringify((await get('/export')).session.war_state)===JSON.stringify(before.war_state),'queue changes do not execute physics');
  await command.getByRole('button',{name:'收起指挥面板'}).click();
 }
 if(process.argv[7]==='blue-objective'){
  await page.getByTestId('command-toggle').click();const command=page.getByTestId('command-panel');await command.waitFor();
  await command.locator('summary').filter({hasText:'控制范围与全局约束'}).click();
  const intent='武汉北线双方向QA，所有数值和位置仍为估计。六份明确人工待命命令优先不变，单位Agent不写状态。'
   +'蓝方第10师团的当前目标是get_campaign_objectives返回的blue_plain后路地域，不是必须歼灭第38师。'
   +'炮弹耗尽不代表永远不能机动；若本轮可行动预算允许，应优先逐轮向该目标机动，实际进入并保持节点。'
   +'若必须休整或侦察，应说明当前可观测约束，不能凭空补弹、瞬移、跨到山地或声称已经到达。'
   +'红方第38师继续按自身防御目标和真实剩余资源选择合法行动；双方每轮经submit_unit_order提交，成功后直接确认。';
  await command.getByLabel('全局意图（软偏好）',{exact:true}).fill(intent);
  const saved=page.waitForResponse(r=>r.url()===url+'/commands'&&r.request().method()==='PUT');
  await command.getByRole('button',{name:'保存控制设置',exact:true}).click();
  check((await saved).ok(),'global natural-language preference saves through the visible command panel');
  const updated=await get('/commands');
  check(updated.intent===intent&&JSON.stringify(updated.unit_agents)===JSON.stringify(before.command_state.unit_agents),'global intent preserves both original unit Agents');
  check(JSON.stringify((await get('/export')).session.war_state)===JSON.stringify(before.war_state),'saving global intent does not advance or rewrite the world');
  await command.getByRole('button',{name:'收起指挥面板'}).click();
 }
 await page.screenshot({path:root+'/before-1440.png'});
 await page.getByRole('button',{name:'推进一轮',exact:true}).click();
 let running=null,terminal=null;const started=Date.now();
 while(Date.now()-started<1500000){
  const p=await get('/progress');
  if(p.active&&!running){
   running=p;fs.writeFileSync(root+'/running.json',JSON.stringify(p));
   if(before.command_state.unit_agents.length){
    await page.reload();await workbench.waitFor({timeout:60000});
    const reloaded=await get('/progress');
    check(reloaded.active&&reloaded.operation_id===running.operation_id,'reload retains the same in-flight Native operation');
    check(await page.locator('.advance-button').isDisabled(),'duplicate advance blocked while Native operation is active');
   }
  }
  if(!p.active&&p.last_operation?.label==='推演 T+'+expected){terminal=p;break;}
  await page.waitForTimeout(500);
 }
 check(!!terminal,'observed a durable terminal result; timeout never triggers another advance');
 fs.writeFileSync(root+'/terminal.json',JSON.stringify(terminal));
 check(terminal.last_operation.outcome==='success','real '+engine+' turn commits successfully');
 const after=(await get('/export')).session;fs.writeFileSync(root+'/after.json',JSON.stringify(after));
 check(after.turn_count===expected,'exactly one turn committed');
 check(after.war_state.simulation_clock.elapsed_seconds-before.war_state.simulation_clock.elapsed_seconds===3600,'clock advances exactly one configured hour');
 check(after.war_state.red_units.length===6&&after.war_state.blue_units.length===2,'all historical calculation identities retained on both teams');
 check(after.command_state.receipts.filter(r=>r.turn===expected).length===8,'all eight units have execution receipts');
 const decisions=after.trajectory.at(-1).decisions.filter(d=>d.source==='native_unit_agent');
 check(decisions.length===before.command_state.unit_agents.length,'each enabled Native unit produces its own decision');
 if(before.command_state.unit_agents.length){
  check(decisions.every(d=>d.proposal?.source==='dsh_native_unit_order_tool'),'decisions came from real structured Native submissions');
  const id='ww2.jp.division10',old=before.war_state.blue_units.find(u=>u.historical_unit_id===id),now=after.war_state.blue_units.find(u=>u.historical_unit_id===id);
  const moved=Math.abs(now.lat-old.lat)+Math.abs(now.lng-old.lng)>1e-5;
  if(expected===1){
   check(moved||after.command_state.receipts.some(r=>r.turn===expected&&r.unit_id===info.ids[id]&&['fire','bombard','suppress'].includes(r.action)),'blue Native unit actively moves or engages on its own axis');
  }else{
   const blue=decisions.find(d=>d.unit_id===info.ids[id]);
   check(!!blue&&typeof blue.rationale==='string'&&blue.rationale.trim().length>0,'blue has an explicit decision and public rationale, including legitimate rest');
   check(after.command_state.receipts.some(r=>r.turn===expected&&r.unit_id===info.ids[id]&&r.action===blue.action),'blue execution receipt matches its actual resource-aware choice');
  }
 }
 check(writes.filter(r=>r.method==='POST'&&r.path.endsWith('/next')).length===1,'only one frontend physical advance request');
 await page.getByRole('button',{name:/^目标与运行/}).click();await goals.waitFor();
 await page.screenshot({path:root+'/after-1440.png'});await page.setViewportSize({width:900,height:1000});await page.screenshot({path:root+'/after-900.png'});
 check(errors.length===0,'no browser application exceptions');
 fs.writeFileSync(root+'/result.json',JSON.stringify({passed:true,checks,errors,writes,session_id:info.session_id,ui,turn:expected,wall_ms:terminal.last_operation.wall_elapsed_ms,actual_dsh:engine==='narrative'||decisions.length>0,actual_afsim:engine==='afsim',scope:'Actual eight-unit two-axis estimated scenario; no full Wuhan history or numerical calibration claim.'},null,2));
 console.log('PASS',checks.length,engine,'turn',expected,terminal.last_operation.wall_elapsed_ms);
}catch(error){
 fs.writeFileSync(root+'/result.json',JSON.stringify({passed:false,error:String(error),checks,errors,writes},null,2));
 const snapshot=await get('/export').catch(()=>null);if(snapshot)fs.writeFileSync(root+'/observed-after-error.json',JSON.stringify(snapshot.session));
 await page.screenshot({path:root+'/failure.png'}).catch(()=>{});throw error;
}finally{await browser.close();}
