/** Actual built App with controlled HTTP facts; not live model acceptance. */
import fs from 'node:fs';
import { createRequire } from 'node:module';
const require=createRequire(fs.realpathSync(process.argv[2]));
const { chromium }=require('playwright-core');
const root=process.argv[3];if(!root||fs.existsSync(root))throw Error('Fresh evidence directory required');
fs.mkdirSync(root,{recursive:true});
const sid='d2c74153c82c',real='http://127.0.0.1:19227',mock='http://127.0.0.1:19998';
const snapshot=await(await fetch(real+'/api/sessions/'+sid)).json();
const cache=new Map();
let active=true,identity='clock-a',offset=750000,label='推演 T+5',started=performance.now(),disconnected=false;
let last=null,legacy=false;
const checks=[],posts=[],errors=[];
const check=(v,text)=>{if(!v)throw Error(text);checks.push(text);};
function progress(){
 const p=active?{operation_id:identity,label,steps:5,wall_elapsed_ms:offset+Math.floor(performance.now()-started),started_at_ms:1}:{};
 if(legacy&&active)delete p.wall_elapsed_ms;
 return {active,operation_id:active?identity:null,progress:p,last_operation:last,
  completed_operation:last?.outcome==='success'?last:{operation_id:'old',label:'旧推演',clock_sampled_at_ms:10},
  failed_operation:last&&last.outcome!=='success'?last:legacy&&!active?{operation_id:'older-failure',error:'旧失败记录'}:null};
}
const browser=await chromium.launch({channel:'chrome',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
page.on('pageerror',e=>errors.push(e.message));
await page.addInitScript(({mock,sid})=>{window.gentactix={backendUrl:mock};localStorage.setItem('gentactix-session',sid);},{mock,sid});
await page.route(mock+'/api/**',async route=>{
 const request=route.request(),path=new URL(request.url()).pathname;
 if(request.method()!=='GET'){posts.push(path);return route.fulfill({status:500,json:{detail:'Unexpected write during recovery'}});}
 if(path.endsWith('/progress')){
  if(disconnected)return route.abort('failed');
  return route.fulfill({json:progress()});
 }
 if(path==='/api/sessions')return route.fulfill({json:{sessions:[{session_id:sid,initialized:true,turn_count:4,scenario:'时钟与结果恢复 UI 契约测试'}]}});
 if(path==='/api/sessions/'+sid)return route.fulfill({json:{...snapshot,notices:[],engine_meta:last?.outcome==='success'?last:snapshot.engine_meta}});
 if(!cache.has(path)){
  const response=await fetch(real+path);cache.set(path,{status:response.status,body:await response.text()});
 }
 const value=cache.get(path);return route.fulfill({status:value.status,contentType:'application/json',body:value.body});
});
const line=page.getByTestId('operation-progress'),timer=page.getByTestId('operation-elapsed');
function seconds(text){if(text==='--:--')return null;return text.split(':').map(Number).reduce((a,b)=>a*60+b,0);}
async function open(){
 await page.goto('http://127.0.0.1:19248');
 if(!active){await page.getByRole('tab',{name:/已保存战局/}).click();await page.locator(`[data-session-id="${sid}"] .open-battle`).click();}
 await page.getByTestId('map-workbench').waitFor({timeout:60000});
}
async function terminal(outcome,duration,id){
 active=false;last={operation_id:id,label:'推演 T+5',outcome,wall_elapsed_ms:duration,
  started_at_ms:1,clock_sampled_at_ms:duration+1,error:outcome==='success'?undefined:'测试：候选未提交',cancelled:outcome==='cancelled'};
 await open();await line.locator(':scope').waitFor({state:'visible'});
 await page.waitForFunction(outcome=>document.querySelector('[data-testid="operation-progress"]')?.getAttribute('data-state')===outcome,outcome);
 check(await line.getAttribute('data-clock-source')==='server','terminal uses server clock '+outcome);
 check(seconds(await timer.innerText())===duration/1000,'terminal duration restored '+outcome);
}
try{
 await open();await page.waitForFunction(()=>document.querySelector('[data-testid="operation-progress"]')?.getAttribute('data-state')==='running');
 check(seconds(await timer.innerText())>=750,'late attach restores12+minutes');
 check(await line.getAttribute('data-clock-source')==='server','running clock is server anchored');
 check(await line.getAttribute('role')==='progressbar'&&!await line.getAttribute('aria-valuenow'),'running progress is accessible without invented percentage');
 check((await page.getByTestId('operation-status').innerText()).includes('推演中'),'recovered operation has actual label');
 const before=seconds(await timer.innerText());await page.reload();await line.waitFor({state:'visible'});
 await page.waitForFunction(()=>document.querySelector('[data-testid="operation-progress"]')?.getAttribute('data-clock-source')==='server');
 check(seconds(await timer.innerText())>=before,'reload does not reset elapsed');
 label='推演 T+5 · 正在校验';await page.waitForTimeout(1300);
 check(seconds(await timer.innerText())>=before,'label change does not reset elapsed');
 disconnected=true;await page.waitForTimeout(1400);
 check((await line.getAttribute('title')).includes('状态连接暂不可用'),'disconnection is visible');
 check(await page.locator('.advance-button').isDisabled(),'duplicate advance blocked during disconnection');
 check(seconds(await timer.innerText())>=before,'clock continues while status is disconnected');
 disconnected=false;await page.waitForTimeout(1400);
 await page.evaluate(()=>{window.__qaClockMap=document.querySelector('.leaflet-container');});
 await page.locator('.leaflet-control-zoom-in').click();await page.waitForTimeout(700);
 check(await page.evaluate(()=>window.__qaClockMap===document.querySelector('.leaflet-container')),'map stays interactive and mounted across clock ticks');
 await page.screenshot({path:root+'/running-1440.png'});await page.setViewportSize({width:900,height:1000});
 await page.screenshot({path:root+'/running-900.png'});
 check(!await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),'narrow clock header has no horizontal overflow');
 await terminal('success',780000,'clock-a');check((await page.getByTestId('operation-status').innerText()).includes('推演完成'),'load is not falsely labeled completion of a new operation');
 const frozen=await timer.innerText();await page.waitForTimeout(1400);check(await timer.innerText()===frozen,'completed elapsed freezes');
 await terminal('failed',820000,'clock-b');await page.waitForTimeout(4200);
 check(await line.isVisible(),'failure remains visible');check(seconds(await timer.innerText())===820,'failed elapsed freezes');
 await page.screenshot({path:root+'/failed-900.png'});
 await terminal('cancelled',840000,'clock-c');
 check((await page.getByTestId('operation-status').innerText()).includes('已取消'),'cancellation is not success');
 active=true;last=null;identity='clock-new';offset=2000;started=performance.now();label='璇玑问答';
 await open();await page.waitForFunction(()=>document.querySelector('[data-testid="operation-progress"]')?.getAttribute('data-clock-source')==='server');
 check(seconds(await timer.innerText())<20,'new operation restarts its own clock');
 check((await page.getByTestId('operation-status').innerText()).includes('问答中'),'new operation label updates');
 label='因果解读';await page.waitForTimeout(1300);
 check((await page.getByTestId('operation-status').innerText()).includes('因果分析中'),'causal operation is named separately');
 label='DSH只读命令干预';await page.waitForTimeout(1300);
 check((await page.getByTestId('operation-status').innerText()).includes('只读试算中'),'readonly branch is not labeled physical execution');
 legacy=true;identity='legacy-clock';await open();await line.waitFor({state:'visible'});
 await page.waitForFunction(()=>document.querySelector('[data-testid="operation-progress"]')?.getAttribute('data-clock-source')==='unknown');
 check(await timer.innerText()==='--:--','unknown legacy duration is not invented');
 active=false;last=null;await open();
 await page.waitForTimeout(600);
 check(!await line.isVisible(),'ambiguous legacy outcome is not presented as success');
 check((await page.locator('body').innerText()).includes('操作先后顺序未登记'),'legacy failure remains inspectable without invented order');
 check(posts.length===0,'reload and terminal recovery never resubmit commands');
 check(errors.length===0,'no application errors');
 check(await page.locator('.nato-marker').count()===22,'all22 map markers retained');
 fs.writeFileSync(root+'/result.json',JSON.stringify({passed:true,checks,count:checks.length,posts,errors,
  actual_model:false,scope:'Actual built App; controlled API facts for clock/recovery only; no physical simulation'},null,2));
 console.log('PASS',checks.length,'builtApp clock/recovery checks');
}catch(error){fs.writeFileSync(root+'/result.json',JSON.stringify({passed:false,error:String(error),checks,posts,errors},null,2));await page.screenshot({path:root+'/failure.png'});throw error;}
finally{await browser.close();}
