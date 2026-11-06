/** Historical sourced child IDs and explicit residual, through compiled UI. */
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(fs.realpathSync(process.argv[2])),{chromium}=require('playwright-core');
const root='.cache/qa/formation-ui-2026-11-02',tag=process.argv[3],out=`${root}/${tag}`;
if(!tag||!/^[a-z0-9-]+$/.test(tag)||fs.existsSync(out))throw Error('Choose fresh evidence');fs.mkdirSync(out);
const api='http://127.0.0.1:19214/api',checks=[],errors=[],cases={};
const save=(n,v)=>fs.writeFileSync(`${out}/${n}.json`,JSON.stringify(v,null,2));
const check=(v,s)=>{if(!v)throw Error(s);checks.push(s);};
const call=async(method,path,value)=>{const r=await fetch(api+path,{method,headers:{'Content-Type':'application/json'},body:value===undefined?undefined:JSON.stringify(value)});if(!r.ok)throw Error(`${r.status}: ${await r.text()}`);return r.json();};
const get=p=>call('GET',p),browser=await chromium.launch({channel:'chrome',headless:true});let page;
try{
 const sources=JSON.parse(fs.readFileSync(process.env.FORMATION_HISTORICAL_CASES??root+'/historical-cases.json'));
 for(const engine of ['narrative','afsim']){
  const original='/sessions/'+sources[engine].session_id,v=await get(original+'/commands');
  const branch=await call('POST',original+'/commands/open-branch',{expected_turn:v.turn,revision:v.revision,world_version:v.world_version});
  const base='/sessions/'+branch.session_id;cases[engine]={session_id:branch.session_id};save('cases',cases);
  const before=(await get(base+'/export')).session;save(engine+'-before',before);
  const q=await get(base+'/commands'),parent=q.units.find(u=>u.name==='第74军'),initialIds=new Set(q.units.filter(u=>u.present).map(u=>u.id));
  page=await browser.newPage({viewport:{width:1440,height:1000}});page.on('pageerror',e=>errors.push(String(e)));
  await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19214'});await page.goto('http://127.0.0.1:19216/');
  await page.getByRole('tab',{name:/已保存战局/}).click();await page.locator(`[data-session-id="${branch.session_id}"] .open-battle`).click();
  await page.getByTestId('analysis-tab-forces').click();const panel=page.getByTestId('formation-conversion');
  await panel.getByLabel('实体转换单位',{exact:true}).selectOption([parent.id]);
  await panel.getByLabel('实体转换依据',{exact:true}).fill('有来源的74军下属51、58师；4000/4000/2000仅QA分配估计，不是历史兵额');
  await panel.getByLabel('分队1历史身份',{exact:true}).waitFor({timeout:10000});
  check(await panel.getByLabel('分队1名称',{exact:true}).count()===0,engine+' historical mode offers source identities rather than free names');
  await panel.getByLabel('分队1历史身份',{exact:true}).selectOption('ww2.cn.division51');
  check(await panel.getByLabel('分队1历史身份',{exact:true}).locator('option').filter({hasText:'第58师'}).count()===1,engine+' frozen present direct children are available');
  await panel.getByLabel('分队2历史身份',{exact:true}).selectOption('ww2.cn.division58');
  check(await panel.getByTestId('formation-preview').isDisabled(),engine+' incomplete child coverage cannot omit residual');
  check((await panel.innerText()).includes('须保留未分配余部'),engine+' residual requirement explained');
  await panel.getByRole('button',{name:'增加分队',exact:true}).click();
  await panel.getByLabel('分队3历史身份',{exact:true}).selectOption('__residual__');
  for(const [i,n] of [[1,4000],[2,4000],[3,2000]])await panel.getByLabel(`分队${i}投入人数`,{exact:true}).fill(String(n));
  const previewResponse=page.waitForResponse(r=>r.url().endsWith('/conversion-preview')&&r.request().method()==='POST');
  await panel.getByTestId('formation-preview').click();const response=await previewResponse,body=response.request().postDataJSON();
  save(engine+'-preview-request',{status:response.status(),body:await response.json(),request:body});
  check(response.status()===200,engine+' actual historical request accepted');
  check(body.allocations.every(a=>Object.keys(a).sort().join(',')==='committed,historical_unit_id,id')&&body.allocations[2].historical_unit_id===null,engine+' historical request sends source IDs and explicit null residual, no labels');
  check(JSON.stringify((await get(base+'/export')).session)===JSON.stringify(before),engine+' historical preview whole-session readonly');
  await panel.getByTestId('formation-confirm').click();await panel.getByTestId('formation-saved').waitFor({state:'attached',timeout:60000});
  const split=(await get(base+'/export')).session;save(engine+'-split',split);
  const actors=(await get(base+'/commands')).units.filter(u=>u.present&&!initialIds.has(u.id));
  check(actors.length===3&&actors.some(u=>u.name==='第51师')&&actors.some(u=>u.name==='第58师')&&actors.some(u=>u.name.includes('未分配余部')),engine+' actual sourced children and explicit residual saved');
  await panel.getByLabel('实体转换方式',{exact:true}).selectOption('merge');await panel.getByLabel('实体转换单位',{exact:true}).selectOption(actors.map(u=>u.id));
  await panel.getByTestId('formation-preview').click();await panel.getByTestId('formation-confirm').click();await panel.getByTestId('formation-saved').waitFor({state:'attached',timeout:60000});
  const merged=(await get(base+'/export')).session;save(engine+'-merged',merged);
  check(merged.war_state.formation_registry.transactions.length===2,engine+' historical split and merge both saved');
  check(merged.turn_count===before.turn_count&&JSON.stringify(merged.history)===JSON.stringify(before.history)&&JSON.stringify(merged.trajectory)===JSON.stringify(before.trajectory),engine+' historical conversions do not advance or rewrite history');
  const current=(await get(base+'/commands')).units.find(u=>u.present&&u.name==='第74军');check(!!current,engine+' complete merge restores current parent identity');
  await panel.getByLabel('实体转换方式',{exact:true}).selectOption('split');
  const noChildren=(await get(base+'/commands')).units.find(u=>u.present&&u.name==='第159师');
  await panel.getByLabel('实体转换单位',{exact:true}).selectOption([noChildren.id]);
  check((await panel.innerText()).includes('未载本阶段可用的直接下级'),engine+' missing historical children explained without fabrication');
  check(await panel.getByTestId('formation-preview').isDisabled(),engine+' unsupported historical split cannot submit invented names');
  await page.screenshot({path:`${out}/${engine}-history-gap.png`});await page.close();page=null;
 }
 check(!errors.length,'no uncaught application errors');save('result',{passed:true,count:checks.length,checks,cases,errors,
  scope:'Private coarse QA windows over frozen sourced identities, fixed estimated resources/deployment; no new historical fact, model or physics execution'});
 console.log('PASS historical child/residual UI',checks.length,'checks');
}catch(error){save('result',{passed:false,error:String(error),checks,cases,errors});if(page)await page.screenshot({path:`${out}/failure.png`});throw error;}
finally{await browser.close();}
