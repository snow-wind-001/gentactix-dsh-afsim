async page=>{
 const base='http://127.0.0.1:19099/api/sessions/'+'d'.repeat(12),checks=[],errors=[];
 const check=(ok,label)=>{if(!ok)throw Error(label);checks.push(label);};
 const get=async path=>{const r=await page.request.get(path);if(!r.ok())throw Error(await r.text());return r.json();};
 page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:19099'};});
 await page.goto('http://127.0.0.1:19088');await page.evaluate(()=>localStorage.setItem('gentactix-session','d'.repeat(12)));
 await page.reload();await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
 const panel=page.getByTestId('force-organization');if(!await panel.isVisible())await page.getByTestId('analysis-tab-forces').click();await panel.getByLabel('编制关系视图',{exact:true}).waitFor();
 const current=await get(base),org=await get(base+'/force-organization'),resuming=current.turn_count===1;
 check(current.turn_count===0||resuming&&!!current.last_war_state,'Verified initial state or committed first-round predecessor');
 const before=resuming?{...current,war_state:current.last_war_state}:current;let after=current;
 const names=ids=>new Set(org.targets.filter(u=>ids.includes(u.id)).map(u=>u.name));
 const node=id=>org.nodes.find(n=>n.id===id),army=node('ww2.cn.army66');
 check(names(army.effective_execution_ids).has('第161师万家岭投入部')&&army.effective_execution_ids.length===2,'Army 66 controls both sourced elements');
 check(node('ww2.cn.division161.wjl_part').parent_id==='ww2.cn.division161','Administrative parent remains unchanged');
 await panel.getByLabel('编制关系视图',{exact:true}).selectOption('historical');
 check((await panel.locator('[data-force-node="ww2.cn.army66"]').innerText()).includes('1执行单位'),'Administrative view counts its own sourced descendant');
 await panel.getByLabel('编制关系视图',{exact:true}).selectOption('command');
 check((await panel.locator('[data-force-node="ww2.cn.army66"]').innerText()).includes('2执行单位'),'Command view shows partial operational attachment');
 check((await panel.locator('[data-force-node="ww2.cn.corps1"]').innerText()).includes('5执行单位'),'First corps covers five unique leaves');
 if(!resuming){
 await panel.getByLabel('兵团下令对象',{exact:true}).selectOption('ww2.cn.army66');
 await panel.getByLabel('兵团任务方式',{exact:true}).selectOption('advance');
 await panel.getByRole('button',{name:'在地图选择行军目标',exact:true}).click();
 const map=page.locator('.leaflet-container'),mb=await map.boundingBox(),ub=await page.getByLabel('红方 第159师',{exact:true}).boundingBox();
 await map.click({position:{x:Math.max(90,ub.x-mb.x-120),y:Math.max(120,ub.y-mb.y-80)}});await panel.waitFor({state:'visible'});
 await panel.getByRole('button',{name:'预览兵团任务',exact:true}).click();const preview=panel.getByTestId('force-task-preview');await preview.waitFor();
 check((await preview.innerText()).includes('第159师')&&(await preview.innerText()).includes('第161师万家岭投入部'),'Reviewed task includes exactly the operational members');
 await preview.getByRole('button',{name:'确认暂存兵团任务',exact:true}).click();await panel.getByRole('status').filter({hasText:'群命令已暂存'}).waitFor();
 let cs=await get(base+'/commands');const selected=new Set(cs.orders.map(o=>o.unit_id));
 check(cs.orders.length===2&&cs.orders.every(o=>o.task_context.command_chain.at(-1)==='ww2.cn.army66'),'Queued tasks retain frozen opening command chain');
 const fields=['id','unit_id','action','duration','destination','target_id','air_pool','end_turn'];
 const r=await page.request.put(base+'/commands',{data:{expected_turn:cs.turn,revision:cs.revision,world_version:cs.world_version,
  control_team:'red',director:true,no_fire:false,intent:'QA66军两投入部机动，其余明确待命',
  orders:[...cs.orders.map(o=>Object.fromEntries(Object.entries(o).filter(([k])=>fields.includes(k)))),
    ...cs.units.filter(u=>!selected.has(u.id)).map(u=>({unit_id:u.id,action:'hold',duration:'next'}))]}});if(!r.ok())throw Error(await r.text());
 await page.reload();await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
 const advanced=page.waitForResponse(r=>r.url()===base+'/next'&&r.request().method()==='POST',{timeout:120000});
 await page.getByRole('button',{name:'推进一轮',exact:true}).click();const next=await advanced;after=await next.json();if(!next.ok())throw Error(JSON.stringify(after));
 }else check(after.afsim.orders.filter(o=>o.action==='move').length===2,'Reuse committed native movement without executing it twice');
 const units=s=>s.war_state.red_units.concat(s.war_state.blue_units),moved=units(after).filter(u=>{const old=units(before).find(x=>x.historical_unit_id===u.historical_unit_id);return old.lat!==u.lat||old.lng!==u.lng;});
 check(moved.length===2&&moved.every(u=>['第159师','第161师万家岭投入部'].includes(u.name)),'Actual AFSIM moves both and only the operational pair');
 const receipts=await get(base+'/unit-decisions?start_turn=1&end_turn=1&limit=100');
 check(receipts.items.filter(r=>r.task_context?.command_chain.at(-1)==='ww2.cn.army66').length===2,'Committed receipts keep the opening command chain');
 if(!await panel.isVisible())await page.getByTestId('analysis-tab-forces').click();await panel.getByLabel('编制关系视图',{exact:true}).waitFor();
 await panel.getByLabel('选择第161师万家岭投入部及已部署下级',{exact:true}).check();
 await panel.getByLabel('任务群名称',{exact:true}).fill('独立先遣群');await panel.getByLabel('配属依据',{exact:true}).fill('QA显式抽调；不改变全161师的行政编制');
 await panel.getByRole('button',{name:'分出所选下级为任务群',exact:true}).click();await panel.getByRole('status').filter({hasText:'临时配属已保存'}).waitFor();
 const changed=await get(base+'/force-organization');check(changed.nodes.find(n=>n.id==='ww2.cn.army66').effective_execution_ids.length===1,'Temporary assignment removes old command authority');
 check(JSON.stringify((await get(base)).war_state)===JSON.stringify(after.war_state),'Reassignment never alters physical state');
 await page.setViewportSize({width:1440,height:1000});await page.screenshot({path:'.cache/qa/initial-command-2026-10-31/browser/command-1440.png'});
 check(errors.length===0,'No browser page errors');return {passed:true,checks,actual_afsim:true,api_mocks:false};
}
