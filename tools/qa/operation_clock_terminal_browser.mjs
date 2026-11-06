/** Read persisted real success/refusal through the final built UI, no writes. */
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(fs.realpathSync(process.argv[2]));const {chromium}=require('playwright-core');
const base='.cache/qa/operation-clock-2026-11-03',root=base+'/'+(process.argv[3]??'terminal-browser');
if(fs.existsSync(root))throw Error('Preserve previous evidence');fs.mkdirSync(root);
const cases=JSON.parse(fs.readFileSync(process.argv[4]??base+'/terminal-cases.json','utf8'));
const apiRoot=process.argv[5]??'http://127.0.0.1:19247',uiRoot=process.argv[6]??'http://127.0.0.1:19248';
const browser=await chromium.launch({channel:'chrome',headless:true}),checks=[],errors=[],posts=[];
const check=(value,label)=>{if(!value)throw Error(label);checks.push(label);};
try{
 for(const item of cases){
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST')posts.push(r.url());});
  await page.addInitScript(({id,api})=>{window.gentactix={backendUrl:api};localStorage.setItem('gentactix-session',id);},{id:item.session_id,api:apiRoot});
  const url=apiRoot+'/api/sessions/'+item.session_id;
  const before=(await(await page.request.get(url+'/export')).json()).session;
  const progress=await(await page.request.get(url+'/progress')).json();
  check(!progress.active&&progress.last_operation.outcome===item.outcome,'persisted terminal fact '+item.outcome);
  await page.goto(uiRoot);await page.getByRole('tab',{name:/已保存战局/}).click();
  await page.locator(`[data-session-id="${item.session_id}"] .open-battle`).click();
  await page.getByTestId('map-workbench').waitFor({timeout:60000});
  await page.waitForFunction(outcome=>document.querySelector('[data-testid="operation-progress"]')?.getAttribute('data-state')===outcome,item.outcome);
  const line=page.getByTestId('operation-progress'),timer=page.getByTestId('operation-elapsed');
  check(await line.getAttribute('data-clock-source')==='server','cold terminal uses server clock '+item.outcome);
  const text=await timer.innerText(),seconds=text.split(':').map(Number).reduce((a,b)=>a*60+b,0);
  check(seconds===Math.floor(progress.last_operation.wall_elapsed_ms/1000),'cold duration equals persisted fact '+item.outcome);
  await page.waitForTimeout(1000);check(await timer.innerText()===text,'cold terminal time frozen '+item.outcome);
  if(item.outcome==='failed'){
   check((await page.getByTestId('operation-status').innerText()).includes('只读试算未完成'),'refused analysis not labeled committed battle');
   check((await page.locator('body').innerText()).includes('未找到当前开局的回合轨迹'),'actual refusal error visible');
  }else check((await page.getByTestId('operation-status').innerText()).includes(item.kind==='turn'?'推演完成':'问答完成'),'restored success refers to actual operation');
  if(item.kind==='turn'){
    const view=await(await page.request.get(url+'/commands')).json();
    const unit=view.units.find(u=>u.name==='日军第106师团');
    await page.getByTestId('command-toggle').click();
    await page.getByLabel('单位名单（含无坐标单位）').selectOption(unit.id);
    check((await page.getByTestId('selected-unit-strength').innerText()).includes(String(unit.personnel_strength_pct)+'%'),'current casualty strength rendered from actual account');
  }else if(item.outcome==='success'){
    await page.getByRole('tab',{name:'璇玑问答',exact:true}).click();
    check(await page.locator('.msg.assistant').count()===before.chat_messages.filter(m=>m.role==='assistant').length,'stored actual answer remains visible after reload');
    check((await page.locator('.msg.assistant .message-content').last().innerText()).length>0,'actual answer text rendered after recovery');
  }
  await page.screenshot({path:root+'/'+item.outcome+'-1440.png'});await page.setViewportSize({width:900,height:1000});
  await page.screenshot({path:root+'/'+item.outcome+'-900.png'});
  check(await page.locator('.nato-marker').count()===22,'22markers retained '+item.outcome);
  check(!await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),'no narrow overflow '+item.outcome);
  const after=(await(await page.request.get(url+'/export')).json()).session;
  check(JSON.stringify(after)===JSON.stringify(before),'whole session unchanged by readonly recovery '+item.outcome);
  await page.close();
 }
 check(posts.length===0&&errors.length===0,'zero POST or browser errors');
 fs.writeFileSync(root+'/result.json',JSON.stringify({passed:true,checks,count:checks.length,errors,posts,
  actual_model:false,scope:'Readonly UI recovery of persisted actual SDK question, API refusal and optional physical-turn results; this run makes no new model or physical-turn call'},null,2));
 console.log('PASS',checks.length,'actual terminal recovery checks');
}catch(error){fs.writeFileSync(root+'/result.json',JSON.stringify({passed:false,error:String(error),checks,errors,posts},null,2));throw error;}
finally{await browser.close();}
