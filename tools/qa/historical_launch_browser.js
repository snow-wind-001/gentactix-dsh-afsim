// Archived 3.7.0 teaching-entry regression. It does not prove current historical
// correctness; use historical_named_launch_start.js and its finish checks instead.
async page => {
 const API='__API__',UI='__UI__',OUT='.cache/qa/historical-launch-fix',checks=[],submitted=[],built=[],validated=[];
 const assert=(ok,label)=>{if(!ok)throw new Error(label);checks.push(label);};
 const seed=await(await page.request.get(API+'/api/scenarios/basis/CA-AJ18-v1')).json();
 const fixture=(engine,id)=>({id,mission_id:'CA-AJ18-v1',configuration:seed.configuration,preview_world:seed.preview_world,
  execution_backend:engine,definition_hash:'explicit-browser-fixture',construction:{source:'explicit_browser_fixture',skill:'fixture'},
  afsim:engine==='afsim'?{version:'fixture',entity_count:2,returncode:0}:null});
 // UI contracts use named fixtures; genuine model/native runs are verified separately.
 await page.route(API+'/api/sessions',async route=>{
  if(route.request().method()!=='POST')return route.continue();submitted.push(route.request().postDataJSON());
  await route.fulfill({status:422,json:{detail:'QA已捕获创建参数，未创建战局'}});
 });
 await page.route(API+'/api/scenarios/build',async route=>{const p=route.request().postDataJSON();built.push(p);await route.fulfill({json:fixture(p.execution_backend,'a'.repeat(32))});});
 await page.route(API+'/api/scenarios/validate',async route=>{const p=route.request().postDataJSON();validated.push(p);await route.fulfill({json:{...fixture(p.execution_backend,'b'.repeat(32)),configuration:p.configuration}});});
 if(UI.startsWith('http'))await page.context().addInitScript(base=>{window.gentactix={backendUrl:base};localStorage.removeItem('gentactix-session');},API);
 async function configure(){
  if(UI.startsWith('http'))await page.goto(UI);else{await page.evaluate(()=>localStorage.removeItem('gentactix-session'));await page.reload();}
  await page.getByLabel('搜索战役').fill('湘西会战');await page.locator('.battle-option').first().click();await page.getByRole('button',{name:/继续配置/}).click();
 }
 await page.setViewportSize({width:1440,height:1000});
 for(const purpose of ['analysis','historical','synthetic'])for(const engine of ['narrative','afsim']){
  await configure();await page.locator('#draft-mode').selectOption(purpose);await page.locator('#draft-executor').selectOption(engine);
  assert(await page.locator('#draft-mode').inputValue()===purpose&&await page.locator('#draft-executor').inputValue()===engine,purpose+'/'+engine+' selections stay independent');
  if(purpose!=='analysis')await page.getByTestId('scenario-basis').waitFor();
  const next=page.getByTestId('launch-start');assert(await next.isEnabled(),purpose+'/'+engine+' next action enabled');
  const before=submitted.length;const response=page.waitForResponse(r=>r.url()===API+'/api/sessions'&&r.request().method()==='POST');
  await next.click();await response;assert(submitted.length===before+1,purpose+'/'+engine+' reaches create request exactly once');
  const p=submitted.at(-1);assert(p.product_mode===purpose&&p.execution_backend===engine&&p.simulation_mode===(purpose==='analysis'?'replay':'open'),purpose+'/'+engine+' submits matching contract');
  if(purpose==='historical'&&engine==='afsim')assert(!!p.mission_id&&!!p.scenario_draft_id,'historical AFSIM uses calculable rules rather than motion-only preview');
  if(purpose==='synthetic'&&engine==='narrative'){
   await page.waitForFunction(()=>!document.querySelector('[data-testid=launch-start]').disabled);
   assert((await page.getByTestId('scenario-validation').textContent()).includes('未启动AFSIM'),'DSH validation does not claim native load');
   await page.locator('#draft-executor').selectOption('afsim');
   assert((await page.getByTestId('scenario-validation').textContent()).includes('未验证'),'engine change invalidates previous validation');
   assert(await page.getByTestId('validate-scenario').isEnabled(),'engine change has actionable revalidation');
  }
 }
 await configure();await page.locator('#draft-executor').selectOption('narrative');await page.locator('#draft-mode').selectOption('analysis');
 await page.setViewportSize({width:390,height:844});
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'launch configuration fits phone width');
 await page.getByTestId('launch-start').scrollIntoViewIfNeeded();
 assert(await page.getByTestId('launch-start').evaluate(el=>{const r=el.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight;}),'next action remains reachable in narrow viewport');
 await page.screenshot({path:OUT+'/matrix-phone.png'});await page.setViewportSize({width:1440,height:1000});await page.screenshot({path:OUT+'/matrix-wide.png'});
 assert(built.length===4,'four open paths invoke skill generation; source replay does not');
 assert(submitted.length===6,'six combinations submit without silent extra game creation');
 return {passed:true,checks,created_request_count:submitted.length,generation_fixture_calls:built.length,validation_fixture_calls:validated.length,
  actual_model_calls:false,game_creation_intercepted:true};
}
