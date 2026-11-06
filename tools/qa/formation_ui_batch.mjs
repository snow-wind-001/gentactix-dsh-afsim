/** Real 32-child split/merge saves on fresh copies, without model/physics calls. */
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(fs.realpathSync(process.argv[2])),{chromium}=require('playwright-core');
const root='.cache/qa/formation-ui-2026-11-02',tag=process.argv[3],out=`${root}/${tag}`;
if(!tag||!/^[a-z0-9-]+$/.test(tag)||fs.existsSync(out))throw Error('Choose fresh evidence');fs.mkdirSync(out);
const host='http://127.0.0.1:19214/api',checks=[],errors=[],cases={};
const save=(n,v)=>fs.writeFileSync(`${out}/${n}.json`,JSON.stringify(v,null,2));
const check=(v,s)=>{if(!v)throw Error(s);checks.push(s);};
const call=async(method,path,value)=>{const r=await fetch(host+path,{method,headers:{'Content-Type':'application/json'},body:value===undefined?undefined:JSON.stringify(value)});if(!r.ok)throw Error(`${r.status}: ${await r.text()}`);return r.json();};
const get=p=>call('GET',p),all=w=>[...w.red_units,...w.blue_units];
const totals=w=>all(w).reduce((a,u)=>{for(const k of ['committed','current','casualties','noncombat_losses'])a[k]=(a[k]??0)+(u.personnel[k]??0);return a;},{});
const browser=await chromium.launch({channel:'chrome',headless:true});let page;
async function members(base){
 const tasks=await get(base+'/force-organization/tasks');check(tasks.rows.length===1,'one original persistent task remains');
 let args={kind:'members',task_id:tasks.rows[0].id,limit:16},rows=[];
 while(args){const v=await get(base+'/force-organization/tasks?'+new URLSearchParams(args));rows.push(...v.rows);args=v.next_args;}
 return rows;
}
try{
 const sources=JSON.parse(fs.readFileSync(root+'/cases.json'));
 for(const engine of ['narrative','afsim']){
  const source='/sessions/'+sources[engine].source_id,q=await get(source+'/commands');
  const created=await call('POST',source+'/commands/open-branch',{expected_turn:q.turn,revision:q.revision,world_version:q.world_version});
  const sid=created.session_id,base='/sessions/'+sid;cases[engine]={session_id:sid};save('cases',cases);
  const before=(await get(base+'/export')).session;save(engine+'-before',before);
  const v=await get(base+'/commands'),unit=v.units.find(u=>u.name==='第159师'),originalIds=new Set(v.units.filter(u=>u.present).map(u=>u.id));
  page=await browser.newPage({viewport:{width:1440,height:1000}});page.on('pageerror',e=>errors.push(String(e)));
  await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19214'});await page.goto('http://127.0.0.1:19216/');
  await page.getByRole('tab',{name:/已保存战局/}).click();await page.locator(`[data-session-id="${sid}"] .open-battle`).click();
  await page.getByTestId('analysis-tab-forces').click();const panel=page.getByTestId('formation-conversion');
  await panel.getByLabel('实体转换单位',{exact:true}).selectOption([unit.id]);
  await panel.getByLabel('实体转换依据',{exact:true}).fill('32分队真实保存边界验收；固定估计参数，不是历史改编');
  for(let i=2;i<32;i++)await panel.getByRole('button',{name:'增加分队',exact:true}).click();
  const n=unit.personnel.committed,share=Math.floor(n/32);
  for(let i=1;i<=32;i++)await panel.getByLabel(`分队${i}投入人数`,{exact:true}).fill(String(i===1?n-share*31:share));
  await panel.getByTestId('formation-preview').click();await panel.getByTestId('formation-confirm').click();
  await panel.getByTestId('formation-saved').waitFor({state:'attached',timeout:60000});
  const split=(await get(base+'/export')).session;save(engine+'-split',split);
  const actors=(await get(base+'/commands')).units.filter(u=>u.present&&!originalIds.has(u.id));
  check(actors.length===32&&all(split.war_state).length===37,engine+' 32 saved actual children, not just candidate rows');
  check(new Set(actors.map(u=>u.name)).size===32,engine+' saved child names unique');
  check(JSON.stringify(totals(split.war_state))===JSON.stringify(totals(before.war_state)),engine+' split personnel and losses conserved');
  const splitMembers=await members(base);check(splitMembers.length===32&&splitMembers.every(r=>r.executions===1),engine+' 32 task members individually inherit one delivery');
  await panel.getByLabel('实体转换方式',{exact:true}).selectOption('merge');
  await panel.getByLabel('实体转换单位',{exact:true}).selectOption(actors.map(u=>u.id));
  await panel.getByLabel('实体转换依据',{exact:true}).fill('同根同地32分队重新合并，保留伤损、库存与任务；无物理推进');
  await panel.getByTestId('formation-preview').click();await panel.getByTestId('formation-confirm').click();
  await panel.getByTestId('formation-saved').waitFor({state:'attached',timeout:60000});
  const merged=(await get(base+'/export')).session;save(engine+'-merged',merged);
  check(all(merged.war_state).length===6&&merged.war_state.formation_registry.transactions.length===2,engine+' merging all 32 returns to six actors and two transactions');
  check(JSON.stringify(totals(merged.war_state))===JSON.stringify(totals(before.war_state)),engine+' merge personnel and losses conserved');
  const mergedMembers=await members(base);check(mergedMembers.length===1&&mergedMembers[0].executions===1,engine+' merged task retains one delivery, not 32');
  check(JSON.stringify(merged.war_state.simulation_clock)===JSON.stringify(before.war_state.simulation_clock)&&merged.turn===before.turn,engine+' conversions do not advance clock or turn');
  check(JSON.stringify(merged.history)===JSON.stringify(before.history)&&JSON.stringify(merged.trajectory)===JSON.stringify(before.trajectory),engine+' original history and trajectory unchanged');
  check(JSON.stringify(merged.command_state.unit_agents)===JSON.stringify(before.command_state.unit_agents),engine+' original Native unit policy retained');
  await page.screenshot({path:`${out}/${engine}-merged.png`});await page.close();page=null;
 }
 check(!errors.length,'no uncaught application errors');save('result',{passed:true,count:checks.length,checks,cases,errors,
  scope:'Two-backend compiled UI save of32children and merge32, fixed QA estimates; no model/physics or history calibration'});
 console.log('PASS saved32split/merge',checks.length,'checks');
}catch(error){save('result',{passed:false,error:String(error),checks,cases,errors});if(page)await page.screenshot({path:`${out}/failure.png`});throw error;}
finally{await browser.close();}
