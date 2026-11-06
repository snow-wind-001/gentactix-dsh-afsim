/** Final wide/narrow, two-engine review: no state-changing requests. */
import fs from 'node:fs';import {createRequire} from 'node:module';
const require=createRequire('/home/spikebai/.nvm/versions/node/v22.20.0/lib/node_modules/@playwright/cli/package.json');
const {chromium}=require('playwright-core');
const base=process.argv[2],ui=process.argv[3],attempt=process.argv[4];
if(!base||!ui||!/^[a-z0-9-]+$/.test(attempt))throw Error('Require root, UI and unused attempt');
const root=base+'/'+attempt;if(fs.existsSync(root))throw Error('Preserve previous review');fs.mkdirSync(root);
const browser=await chromium.launch({channel:'chrome',headless:true});const summaries=[];
try{
 for(const engine of ['afsim','narrative']){
  const info=JSON.parse(fs.readFileSync(base+'/'+engine+'/case.json')),url=info.api+'/api/sessions/'+info.session_id;
  async function get(path){const r=await fetch(url+path);if(!r.ok)throw Error(r.status+' '+path);return r.json();}
  const before=(await get('/export')).session,progress=await get('/progress');
  const checks=[],writes=[],errors=[];const check=(v,m)=>{if(!v)throw Error(engine+': '+m);checks.push(m);};
  check(!progress.active,'committed operation is idle');
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(['POST','PUT','PATCH','DELETE'].includes(r.method()))writes.push(new URL(r.url()).pathname);});
  await page.addInitScript(i=>{window.gentactix={backendUrl:i.api};localStorage.setItem('gentactix-session',i.session_id);},info);
  await page.goto(ui,{waitUntil:'domcontentloaded'});
  const work=page.getByTestId('map-workbench'),saved=page.getByRole('tab',{name:/已保存战局/});
  await Promise.race([work.waitFor(),saved.waitFor()]);
  if(!await work.isVisible()){await saved.click();await page.locator(`[data-session-id="${info.session_id}"] .open-battle`).click();}
  await work.waitFor();
  check((await page.getByTestId('execution-kind').innerText()).includes(engine==='afsim'?'AFSIM':'DSH独立推演'),'purpose and execution path remain clearly distinguished');
  await page.getByTestId('command-toggle').click();const command=page.getByTestId('command-panel');await command.waitFor();
  const menu=command.getByLabel('单位名单（含无坐标单位）');check(await menu.locator('option').count()===9,'all eight historical calculation units remain selectable');
  for(const id of ['ww2.cn.division38','ww2.jp.division10']){
   await menu.selectOption(info.ids[id]);
   check(await command.getByLabel('启用此单位的 DSH 原生 Agent',{exact:true}).isChecked(),'original '+id+' Agent remains enabled');
   const unit=before.war_state[(id.includes('.cn.')?'red':'blue')+'_units'].find(u=>u.historical_unit_id===id);
   check((await page.getByTestId('selected-unit-resources').innerText()).includes(String(unit.personnel.current)),id+' visible current personnel matches the ledger');
   check((await page.getByTestId('selected-unit-strength').innerText()).includes('非核定编制满员率'),id+' retention ratio is not described as historical full strength');
   const recordResponse=page.waitForResponse(r=>new URL(r.url()).pathname===new URL(url).pathname+'/unit-decisions'&&new URL(r.url()).searchParams.get('unit_id')===info.ids[id]&&r.request().method()==='GET');
   await command.getByRole('button',{name:'本单位决策／执行回执',exact:true}).click();
   check((await recordResponse).ok(),id+' decision lookup uses the selected historical unit identity');
   const records=command.getByRole('region',{name:'单位决策记录',exact:true});await records.waitFor();
   await page.waitForFunction(()=>document.querySelector('[aria-label="单位决策记录"] article'));
   check(await records.locator('article').count()>=before.turn_count,id+' public decisions and execution receipts remain available');
   await records.scrollIntoViewIfNeeded();
   await page.screenshot({path:root+'/'+engine+'-'+(id.includes('.cn.')?'red':'blue')+'-decisions-1440.png'});
  }
  await page.screenshot({path:root+'/'+engine+'-commands-1440.png'});
  await command.getByRole('button',{name:'收起指挥面板'}).click();
  await page.getByRole('button',{name:/^目标与运行/}).click();const goals=page.getByTestId('campaign-objectives');await goals.waitFor();
  check(await goals.locator('[data-goal-id]').count()===5,'all five goal states remain visible');
  await goals.getByLabel('目标阵营',{exact:true}).selectOption('red');check(await goals.locator('[data-goal-id]').count()===3,'red has three independent/dependent goals');
  await goals.getByLabel('目标阵营',{exact:true}).selectOption('blue');check(await goals.locator('[data-goal-id]').count()===2,'blue has its own two direction goals');
  await goals.getByLabel('目标阵营',{exact:true}).selectOption('all');
  if(engine==='afsim'){
   const status=await page.getByTestId('afsim-status').innerText();
   check(status.includes('未额外调用全局规划模型')&&!status.includes('未调用模型。'),'AFSIM status accurately distinguishes unit calls from global planning');
  }else check(!!before.war_state.dsh_execution&&!before.war_state.afsim,'DSH path retains its separate estimated-effect provenance');
  for(const width of [1440,900]){
   await page.setViewportSize({width,height:1000});
   check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),width+' layout has no document horizontal overflow');
   await page.screenshot({path:root+'/'+engine+'-goals-'+width+'.png'});
  }
  check(writes.length===0,'viewing units/decisions/goals never submits mutation requests');
  check(JSON.stringify((await get('/export')).session)===JSON.stringify(before),'complete typed session, trajectory and bindings remain unchanged');
  check(JSON.stringify(await get('/progress'))===JSON.stringify(progress),'operation terminal state remains unchanged');
  check(errors.length===0,'no browser application exceptions');
  summaries.push({engine,session_id:info.session_id,turn:before.turn_count,passed:true,checks,writes,errors});await page.close();
 }
 fs.writeFileSync(root+'/result.json',JSON.stringify({passed:true,cases:summaries,ui,scope:'Read-only current estimated two-axis games; not full-history, all tabs or long-run certification.'},null,2));
 console.log('PASS final read-only reviews',summaries.map(s=>s.engine+':'+s.checks.length).join(', '));
}catch(error){fs.writeFileSync(root+'/result.json',JSON.stringify({passed:false,error:String(error),completed_cases:summaries},null,2));throw error;}
finally{await browser.close();}
