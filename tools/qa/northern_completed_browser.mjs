/** Reopen the actual validated model draft; test the UI contract without regeneration. */
import fs from 'node:fs';import {createRequire} from 'node:module';
const require=createRequire('/home/spikebai/.nvm/versions/node/v22.20.0/lib/node_modules/@playwright/cli/package.json');
const {chromium}=require('playwright-core');
const base=process.argv[2],api=process.argv[3],ui=process.argv[4],mode=process.argv[5],attempt=process.argv[6];
if(!base||!api||!ui||!['expect-blocked','enter'].includes(mode)||!/^[a-z0-9-]+$/.test(attempt))throw Error('Require root, API, UI, mode, unused attempt');
const root=base+'/'+attempt;if(fs.existsSync(root))throw Error('Preserve earlier evidence');fs.mkdirSync(root);
const draftPath=base+'/resume-proof/draft.json',draft=JSON.parse(fs.readFileSync(draftPath)),scenario=JSON.parse(fs.readFileSync(base+'/generation-case.json'));
const browser=await chromium.launch({channel:'chrome',headless:true}),page=await browser.newPage({viewport:{width:1440,height:1000}});
page.setDefaultTimeout(30000);const checks=[],errors=[],writes=[],responses=[];
const check=(v,m)=>{if(!v)throw Error(m);checks.push(m);};
page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(['POST','PUT','DELETE'].includes(r.method()))writes.push({path:new URL(r.url()).pathname,method:r.method()});});
page.on('response',async r=>{if(r.request().method()==='POST'){const body=await r.text().catch(()=>null);responses.push({path:new URL(r.url()).pathname,http:r.status(),body});}});
await page.addInitScript(api=>window.gentactix={backendUrl:api},api);
try{
 await page.goto(ui,{waitUntil:'domcontentloaded'});
 await page.getByRole('textbox',{name:'搜索战役',exact:true}).fill(scenario.battle_query);await page.locator('.battle-option').first().click();
 await page.getByRole('button',{name:/继续配置/}).click();await page.locator('#draft-mode').selectOption('historical');
 await page.locator('#draft-executor').selectOption('narrative');await page.locator('#draft-step').selectOption(scenario.time_step);
 await page.getByLabel('编制范围',{exact:true}).selectOption('campaign');await page.getByLabel('会战窗口',{exact:true}).selectOption(scenario.window);
 await page.getByLabel('生成时必须按时间计算粮秣',{exact:true}).check();await page.getByLabel('生成时采用的耗粮模型',{exact:true}).selectOption('personnel-rations-1');
 await page.getByLabel('生成时必须校验运动与疲劳反馈',{exact:true}).check();
 const open=page.locator(`[data-open-configuration="${draft.id}"]`);await open.waitFor({state:'attached'});
 if(!await open.isVisible())await page.getByTestId('completed-historical-configurations').locator('summary').click();
 await open.click();const validation=page.getByTestId('historical-validation');await validation.waitFor();
 check(await page.locator('[data-historical-actor]').count()===8,'same actually generated eight-unit draft loaded');
 const text=await validation.innerText();fs.writeFileSync(root+'/validation.txt',text);
 await page.screenshot({path:root+'/loaded-1440.png'});
 if(mode==='expect-blocked'){
  check(!text.includes('可创建DSH战局'),'old UI contradicts backend-valid delay graph before the fix');
  check(writes.length===0,'negative UI reproduction makes no new configuration or world');
 }else{
  check(text.includes('可创建DSH战局'),'backend-validated multi-direction delay graph is accepted by frontend');
  check((await page.locator('body').innerText()).includes('按会战目标图逐方向评分'),'goal help describes the graph rather than the legacy single objective');
  check(await page.getByTestId('legacy-campaign-delay').count()===0,'goal graph is not mislabeled as a legacy policy requiring an incompatible upgrade');
  const initializing=page.waitForResponse(r=>r.url().endsWith('/init')&&r.request().method()==='POST',{timeout:120000});
  await page.getByTestId('launch-start').click();const response=await initializing;
  check(response.ok(),'existing actual model configuration initializes through ordinary frontend');
  const snapshot=await response.json();await page.getByTestId('map-workbench').waitFor();
  check(snapshot.turn_count===0&&snapshot.war_state.simulation_clock.elapsed_seconds===0,'no physical turn hidden in loading or initialization');
  check(snapshot.war_state.red_units.length===6&&snapshot.war_state.blue_units.length===2,'both teams appear with all eight calculation identities');
  await page.screenshot({path:root+'/initialized-1440.png'});await page.setViewportSize({width:900,height:1000});await page.screenshot({path:root+'/initialized-900.png'});
  fs.writeFileSync(base+'/live-case.json',JSON.stringify({session_id:snapshot.session_id,draft_id:draft.id,draft_path:draftPath,api,ui,actor_count:8,step_seconds:3600,goal_count:5},null,2));
  fs.writeFileSync(root+'/initial.json',JSON.stringify(snapshot));
 }
 check(!writes.some(r=>r.path.endsWith('/historical-scenarios/build')||r.path.endsWith('/historical-scenarios/resume')),'reopening never calls the model to regenerate or resume');
 check(errors.length===0,'no browser application exceptions');
 fs.writeFileSync(root+'/result.json',JSON.stringify({passed:true,mode,checks,errors,writes,scope:'Same real validated draft; UI contract and ordinary initialization only, not history calibration.'},null,2));
 console.log('PASS',checks.length,mode);
}catch(error){
 fs.writeFileSync(root+'/result.json',JSON.stringify({passed:false,error:String(error),checks,errors,writes,responses},null,2));
 await page.screenshot({path:root+'/failure.png'}).catch(()=>{});throw error;
}finally{await browser.close();}
