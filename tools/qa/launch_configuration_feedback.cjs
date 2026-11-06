/* Browser regression for launch feedback. All writes/model calls are intercepted.
 * GENTACTIX_QA_UI and GENTACTIX_QA_API must point to isolated QA services.
 * PLAYWRIGHT_MODULE may identify an existing Playwright installation.
 */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs');
const assert=require('node:assert/strict');
const ui=process.env.GENTACTIX_QA_UI,api=process.env.GENTACTIX_QA_API;
if(!ui||!api)throw Error('Set isolated GENTACTIX_QA_UI and GENTACTIX_QA_API');
const output=process.env.GENTACTIX_QA_OUTPUT||'.cache/qa/launch-feedback';
fs.mkdirSync(output,{recursive:true});
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const results=[];
 try{
  for(const width of [1440,390]){
   const page=await browser.newPage({viewport:{width,height:1000}});
   page.setDefaultTimeout(10000);
   await page.addInitScript(api=>{window.gentactix={backendUrl:api};localStorage.clear();},api);
   await page.goto(ui,{waitUntil:'domcontentloaded'});
   await page.getByLabel('搜索战役').fill('湘西会战');
   await page.locator('.battle-option').first().click();
   await page.getByRole('button',{name:/继续配置/}).click();
   await page.locator('#draft-mode').selectOption('synthetic');
   await page.locator('#draft-synthetic-basis').selectOption('representative');
   await page.getByTestId('scenario-basis').waitFor();
   await page.locator('#draft-executor').selectOption('narrative');
   let builds=0,created=0,fixture,submitted;
   const mission=await page.locator('#draft-mission').inputValue();
   const base=await (await page.request.get(api+'/api/scenarios/basis/'+encodeURIComponent(mission))).json();
   await page.route(api+'/api/scenarios/build',async route=>{
    builds++;await new Promise(resolve=>setTimeout(resolve,1200));
    if(!fixture)await route.fulfill({status:502,json:{detail:'QA：配置读取失败，模型连接未建立'}});
    else await route.fulfill({json:fixture});
   });
   await page.route(api+'/api/sessions',async route=>{
    if(route.request().method()!=='POST')return route.continue();
    created++;submitted=route.request().postDataJSON();
    await route.fulfill({status:422,json:{detail:'QA：已捕获创建请求，未写入对局'}});
   });
   await page.getByTestId('launch-start').click();
   await page.getByTestId('launch-feedback').waitFor();
   assert.match(await page.getByTestId('launch-feedback').innerText(),/正在/);
   await page.getByTestId('launch-error').waitFor();
   assert.match(await page.getByTestId('launch-error').innerText(),/配置读取失败/);
   const box=await page.getByTestId('launch-error').boundingBox();
   assert(box&&box.y>=0&&box.y+box.height<=1000,'error must remain visible without scrolling');
   assert(await page.getByTestId('launch-start').isEnabled(),'retry must be enabled');
   await page.screenshot({path:`${output}/failure-${width}.png`});
   fixture={...base,id:'a'.repeat(32),execution_backend:'narrative',construction:{skill:'QA fixture',explanation:'UI regression only'}};
   await page.getByTestId('launch-start').click();
   await page.getByTestId('launch-error').filter({hasText:'已捕获创建请求'}).waitFor();
   assert.equal(created,1);assert.equal(submitted.scenario_draft_id,fixture.id);
   assert.equal(submitted.execution_backend,'narrative');
   const personnel=page.getByRole('spinbutton',{name:'red-0-人员',exact:true});
   await personnel.fill('0');
   await page.getByTestId('launch-start').click();
   await page.getByTestId('launch-error').filter({hasText:'人员至少1人'}).waitFor();
   assert.equal(builds,2);assert.equal(created,1,'invalid edited fields must not submit');
   results.push({width,pending_visible:true,failure_visible:true,retry_submits_once:true,invalid_fields_explained:true});
   await page.close();
  }
  fs.writeFileSync(output+'/result.json',JSON.stringify({passed:true,model_calls:false,results},null,2));
  console.log('PASS desktop/mobile waiting, error, retry, launch and invalid-field feedback');
 }finally{await browser.close();}
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
