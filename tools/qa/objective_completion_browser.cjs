/* Uses an isolated API seeded from a copied expired battle. Real native step. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs'),assert=require('node:assert/strict');
const api=process.env.GENTACTIX_QA_API,ui=process.env.GENTACTIX_QA_UI;
const out=process.env.GENTACTIX_QA_OUTPUT||'.cache/qa/objective-browser';
if(!api||!ui)throw Error('Isolated QA API/UI required');
fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});page.setDefaultTimeout(15000);
 try{
  const sessions=await(await page.request.get(api+'/api/sessions')).json();
  const sid=sessions.sessions.find(s=>s.initialized&&s.turn_count>0).session_id;
  const original=await(await page.request.get(api+'/api/sessions/'+sid)).json();
  await page.addInitScript(({api,sid})=>{window.gentactix={backendUrl:api};if(!localStorage.getItem('gentactix-session'))localStorage.setItem('gentactix-session',sid);},{api,sid});
  await page.goto(ui,{waitUntil:'domcontentloaded'});
  await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
  await page.getByTestId('phase-outcome').waitFor();
  assert.match(await page.getByTestId('phase-outcome').innerText(),/截止回合目标未达成/);
  await page.getByRole('button',{name:'查看目标与结算',exact:true}).click();
  const forkResponse=page.waitForResponse(r=>r.url()===api+'/api/sessions/'+sid+'/objective-branch');
  forkResponse.catch(()=>{});
  await page.getByTestId('continue-by-objectives').click();
  const fork=await forkResponse;const created=await fork.json();assert(fork.ok(),JSON.stringify(created));
  assert.notEqual(created.session_id,sid);assert.equal(created.war_state.mission.status,'active');
  assert.equal(created.war_state.mission.definition.termination_mode,'objectives');
  assert.equal(created.war_state.current_time,original.war_state.current_time);
  for(const key of ['red_units','blue_units','supply_nodes','combined_arms'])assert.deepEqual(created.war_state[key],original.war_state[key]);
  await page.getByTestId('phase-outcome').waitFor({state:'hidden'});
  const path=api+'/api/sessions/'+created.session_id;
  const v=await(await page.request.get(path+'/commands')).json();
  const save=await page.request.put(path+'/commands',{data:{expected_turn:v.turn,revision:v.revision,world_version:v.world_version,
   control_team:'red',director:true,no_fire:false,intent:'QA双方待命，验证超过旧截止仍可继续',orders:v.units.map(u=>({unit_id:u.id,action:'hold',duration:'next'}))}});
  assert(save.ok(),await save.text());
  await page.reload({waitUntil:'domcontentloaded'});await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
  const stepResponse=page.waitForResponse(r=>r.url()===path+'/next',{timeout:120000});
  stepResponse.catch(()=>{});
  await page.getByRole('button',{name:'推进一轮',exact:true}).click();
  const step=await stepResponse,after=await step.json();assert(step.ok(),JSON.stringify(after));
  assert.equal(after.turn_count,original.turn_count+1);assert.equal(after.war_state.mission.status,'active');
  assert(after.war_state.afsim.returncode===0);
  await page.getByTestId('top-status').click();await page.getByTestId('outside-source-window').waitFor();
  await page.screenshot({path:out+'/continued-beyond-window.png'});
  const untouched=await(await page.request.get(api+'/api/sessions/'+sid)).json();
  assert.deepEqual(untouched.war_state,original.war_state);assert.equal(untouched.turn_count,original.turn_count);
  await page.getByTestId('top-controls').click();await page.getByRole('button',{name:'想定管理',exact:true}).click();
  await page.getByLabel('搜索战役').fill('万家岭');await page.locator('.battle-option').first().click();
  await page.getByRole('button',{name:/继续配置/}).click();
  assert.equal(await page.locator('#draft-step').inputValue(),'30分钟');
  assert.equal(await page.getByLabel('战局结束方式').inputValue(),'objectives');
  await page.getByTestId('termination-policy').waitFor();
  assert.match(await page.getByTestId('termination-policy').innerText(),/史料日期不作为自动结束时间/);
  await page.getByLabel('战局结束方式').selectOption('deadline');
  await page.getByTestId('historical-window').filter({hasText:'当前计算窗口'}).waitFor();
  await page.getByLabel('战局结束方式').selectOption('objectives');
  await page.getByTestId('historical-window').filter({hasText:'史料参考时间窗'}).waitFor();
  fs.writeFileSync(out+'/result.json',JSON.stringify({passed:true,original:sid,branch:created.session_id,
   original_turn:original.turn_count,continued_turn:after.turn_count,afsim:after.war_state.afsim,
   source_unchanged:true,new_default_step:'30分钟',new_default_completion:'objectives',llm_calls:0},null,2));
  console.log('PASS expired notice, immutable branch, actual native continuation and new launch defaults');
 }catch(error){await page.screenshot({path:out+'/failure.png'}).catch(()=>{});throw error;}finally{await browser.close();}
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
