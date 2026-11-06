/* Actual DSH generation + two DSH-only rounds through an isolated browser/API. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs'),assert=require('node:assert/strict');
const api=process.env.GENTACTIX_QA_API,ui=process.env.GENTACTIX_QA_UI,out=process.env.GENTACTIX_QA_OUTPUT;
if(!api||!ui||!out)throw Error('Isolated QA API/UI/output required');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});page.setDefaultTimeout(20000);
 const began=Date.now();let initialized,error;const requests=[];
 try{
  await page.addInitScript(api=>{window.gentactix={backendUrl:api};},api);
  page.on('response',async r=>{
   if(!r.url().startsWith(api)||r.request().method()!=='POST')return;
   let body;try{body=await r.json();}catch{return;}
   const path=r.url().slice(api.length);requests.push({path,status:r.status()});
   if(path==='/api/historical-scenarios/build')fs.writeFileSync(out+'/generated-draft.json',JSON.stringify(body));
   if(path.endsWith('/init')&&r.ok())initialized=body;
   if(!r.ok())error=body.detail;
  });
  await page.goto(ui,{waitUntil:'domcontentloaded'});await page.getByLabel('搜索战役').fill('万家岭');
  await page.locator('.battle-option').first().click();await page.getByRole('button',{name:/继续配置/}).click();
  await page.getByLabel('战局结束方式').waitFor();assert.equal(await page.getByLabel('战局结束方式').inputValue(),'objectives');
  await page.getByTestId('execution-backend').selectOption('narrative');
  await page.getByPlaceholder('描述所选阶段、双方部署意图和目标；回合跨度以上方选择为准，缺载数值将说明估计依据。').fill(
   'QA软件验收，参数为显式估计：termination_mode严格使用objectives；滚动规划参考deadline_turn=1，连续达标required_turns=3，目标使用地域夺控。保留4个原始历史单位。目标区内保留蓝方被围部；双方资源至少支持两轮待命，不提前规定战果。');
  await page.getByTestId('launch-start').click();
  for(let i=0;i<120&&!initialized&&!error;i++){
   await page.waitForTimeout(5000);if(i%6===0)console.log('generate',await page.getByTestId('launch-feedback').innerText().catch(()=>''));
  }
  if(error)throw Error(JSON.stringify(error));assert(initialized,'Initialization timed out');
  assert.equal(initialized.war_state.mission.definition.termination_mode,'objectives');
  assert.equal(initialized.war_state.mission.definition.deadline_turn,1);
  assert.equal(initialized.time_step,'30分钟');
  const sid=initialized.session_id,path=api+'/api/sessions/'+sid;const steps=[];
  for(let i=0;i<2;i++){
   const view=await(await page.request.get(path+'/commands')).json();
   const response=await page.request.put(path+'/commands',{data:{expected_turn:view.turn,revision:view.revision,world_version:view.world_version,
    control_team:'red',director:true,no_fire:false,intent:'QA两轮双方原地待命；验证目标制不被参考轮数截断',orders:view.units.map(u=>({unit_id:u.id,action:'hold',duration:'next'}))}});
   assert(response.ok(),await response.text());
   await page.reload({waitUntil:'domcontentloaded'});await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
   const next=page.waitForResponse(r=>r.url()===path+'/next',{timeout:600000});next.catch(()=>{});
   await page.getByRole('button',{name:'推进一轮',exact:true}).click();
   const r=await next,value=await r.json();assert(r.ok(),JSON.stringify(value));
   fs.writeFileSync(out+'/turn-'+(i+1)+'.json',JSON.stringify(value));
   assert.equal(value.turn_count,i+1);assert.equal(value.war_state.mission.status,'active');
   assert(value.war_state.dsh_execution);assert(!value.war_state.afsim);assert(value.engine_meta.trace_runs>0);
   steps.push({turn:value.turn_count,status:value.war_state.mission.status,elapsed_ms:value.engine_meta.elapsed_ms});
   console.log('round',i+1,'completed');
  }
  await page.screenshot({path:out+'/two-dsh-rounds.png'});
  fs.writeFileSync(out+'/result.json',JSON.stringify({passed:true,sid,seconds:Math.round((Date.now()-began)/1000),steps,requests,actual_model:true},null,2));
 }catch(e){await page.screenshot({path:out+'/failure.png'}).catch(()=>{});console.error(e.stack);process.exitCode=1;}
 finally{await browser.close();}
})();
