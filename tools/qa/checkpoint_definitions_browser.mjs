/** Real browser downloads and imports a complete T6 file into an isolated API. */
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(fs.realpathSync(process.argv[2]));
const {chromium}=require('playwright-core');
const base='.cache/qa/checkpoint-definitions-2026-11-03',root=base+'/'+(process.argv[3]??'browser');
if(fs.existsSync(root))throw Error('Preserve prior evidence');fs.mkdirSync(root);
const info=JSON.parse(fs.readFileSync(base+'/case.json','utf8')),sid=info.session_id;
const browser=await chromium.launch({channel:'chrome',headless:true});
const checks=[],errors=[],posts=[],gets=[];
const check=(value,label)=>{if(!value)throw Error(label);checks.push(label);};
let source,target;
async function open(api,selected=false){
 const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});
 const page=await context.newPage();page.setDefaultTimeout(60000);
 page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{if(r.method()==='POST')posts.push({api,path:new URL(r.url()).pathname});
  if(r.method()==='GET'&&r.url().includes('/export'))gets.push(r.url());});
 await page.addInitScript(({api,sid,selected})=>{window.gentactix={backendUrl:api};if(selected)localStorage.setItem('gentactix-session',sid);},{api,sid,selected});
 await page.goto(info.ui);return page;
}
try{
 source=await open(info.source_api,true);
 await source.getByRole('tab',{name:/已保存战局/}).click();
 await source.locator(`[data-session-id="${sid}"] .open-battle`).click();
 await source.getByTestId('map-workbench').waitFor();
 check(await source.locator('.nato-marker').count()===22,'source renders all22 units');
 await source.getByTestId('top-controls').click();
 for(const [name,file] of [['导出战局','compact.json'],['兼容导出','expanded.json']]){
  const pending=source.waitForEvent('download');await source.getByRole('button',{name,exact:true}).click();
  const download=await pending;check(download.suggestedFilename().includes('_T6')&&download.suggestedFilename().endsWith('.json'),'download filename identifies retained turn '+name);
  await download.saveAs(root+'/'+file);check(!await download.failure(),'actual server file downloaded '+name);
  if(file==='compact.json')check(fs.statSync(root+'/'+file).size<64*1024*1024,'compact file fits existing import limit');
 }
 check(gets.some(x=>x.endsWith('/export?compact=true'))&&gets.some(x=>x.endsWith('/export')),'compact and legacy routes both used');
 // Controlled failed download tests UX only; no model or world mutation is simulated.
 await source.route('**/export?compact=true',async route=>{await new Promise(r=>setTimeout(r,800));await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'QA controlled download unavailable'})});});
 await source.getByRole('button',{name:'导出战局',exact:true}).click();
 check(await source.getByRole('button',{name:'兼容导出',exact:true}).isDisabled(),'duplicate exports blocked while download pending');
 await source.getByText(/导出失败：/).first().waitFor();
 check(await source.getByRole('button',{name:'导出战局',exact:true}).isEnabled(),'failed download restores export control');
 check(await source.locator('.nato-marker').count()===22,'controlled download failure retains all22 units');
 await source.unroute('**/export?compact=true');
 target=await open(info.target_api);
 await target.getByRole('button',{name:'导入战局',exact:true}).click();
 await target.locator('dialog[open] input[type="file"]').first().setInputFiles(root+'/compact.json');
 const preview=target.getByTestId('import-preview');await preview.waitFor();
 check((await preview.innerText()).includes('22 个单位'),'real import preview restores all22 units');
 check((await preview.innerText()).includes('T+6'),'real import preview retains T6');
 await target.getByRole('button',{name:'确认导入并打开',exact:true}).click();
 await target.getByTestId('map-workbench').waitFor();
 check(await target.locator('.nato-marker').count()===22,'imported map renders all22 units');
 await target.getByTestId('top-controls').click();
 await target.getByRole('button',{name:'导入战局',exact:true}).click();
 await target.locator('dialog[open] input[type="file"]').first().setInputFiles(root+'/compact.json');
 await target.getByTestId('import-preview').waitFor();
 check((await target.getByTestId('import-preview').innerText()).includes('该 ID 已存在'),'duplicate import visibly rejected');
 check(await target.getByRole('button',{name:'确认导入并打开',exact:true}).isDisabled(),'duplicate import cannot overwrite existing game');
 await target.getByRole('button',{name:'取消',exact:true}).click();
 await target.getByTestId('focus-map').click();
 await target.screenshot({path:root+'/imported-1440.png'});await target.setViewportSize({width:900,height:1000});
 await target.screenshot({path:root+'/imported-900.png'});
 check(!await target.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),'imported map has no900px horizontal overflow');
 check(posts.filter(x=>x.api===info.source_api).length===0,'source browser never writes the old game');
 check(posts.filter(x=>x.path==='/api/sessions/import').length===1,'exactly one import committed');
 check(posts.every(x=>x.path==='/api/sessions/import'||x.path==='/api/sessions/import/preview'),'no advance,chat,init or other mutation');
 check(errors.length===0,'zero application errors');
 fs.writeFileSync(root+'/result.json',JSON.stringify({passed:true,checks,count:checks.length,posts,gets,errors,actual_model:false,
  physical_turn:false,compact_bytes:fs.statSync(root+'/compact.json').size,legacy_bytes:fs.statSync(root+'/expanded.json').size,
  scope:'Actual browser download, preview and import over real APIs; one controlled503 tests only export UX; no model call or physical turn'},null,2));
 console.log('PASS',checks.length,'actual download/import checks');
}catch(error){
 fs.writeFileSync(root+'/result.json',JSON.stringify({passed:false,error:String(error),checks,posts,gets,errors},null,2));
 await(target??source)?.screenshot({path:root+'/failure.png'}).catch(()=>{});throw error;
}finally{await browser.close();}
