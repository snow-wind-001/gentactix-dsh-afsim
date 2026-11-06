async page=>{
 const base='http://127.0.0.1:19094/api/sessions/dddddddddddd',checks=[],errors=[];
 const check=(ok,msg)=>{if(!ok)throw Error(msg);checks.push(msg);};
 const read=async()=>{const r=await page.request.get(base+'/force-organization');if(!r.ok())throw Error(await r.text());return r.json();};
 page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:19094'};});
 await page.goto('http://127.0.0.1:19083');
 await page.evaluate(()=>localStorage.setItem('gentactix-session','dddddddddddd'));
 await page.reload();await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
 await page.getByTestId('analysis-tab-forces').click();
 const panel=page.getByTestId('force-organization');await panel.getByLabel('任务群名称',{exact:true}).waitFor();
 const initial=await read(),nodes=initial.nodes.filter(n=>n.team==='red'&&n.execution_ids.length===1);
 const fill=async name=>{await panel.getByLabel('任务群名称',{exact:true}).fill(name);await panel.getByLabel('配属依据',{exact:true}).fill('浏览器QA临时任务组织，原历史建制和物理账不变');};
 const detach=async (name,chosen,parent='')=>{
  for(const n of chosen)await panel.getByLabel(`选择${n.name}及已部署下级`,{exact:true}).check();
  await fill(name);await panel.getByLabel('临时上级',{exact:true}).selectOption(parent);
  await panel.getByRole('button',{name:'分出所选下级为任务群',exact:true}).click();
  await panel.getByRole('status').filter({hasText:'临时配属已保存'}).waitFor();
  const state=await read();return state.groups.find(g=>g.label===name).id;
 };
 const a=await detach('主攻群',nodes.slice(0,2));
 const b=await detach('阻援群',nodes.slice(2,4));
 for(const name of ['主攻群','阻援群'])await panel.getByLabel('合编选择'+name,{exact:true}).check();
 await fill('会战指挥群');await panel.getByRole('button',{name:'保留下级并建立共同上级',exact:true}).click();
 await panel.getByRole('status').filter({hasText:'临时配属已保存'}).waitFor();
 let state=await read(),top=state.groups.find(g=>g.label==='会战指挥群').id;
 check(state.groups.find(g=>g.id===top).member_ids.length===4,'Common HQ preserves four unique leaf members');
 check(state.groups.find(g=>g.id===a).parent_id===top,'Lower group identity retained under new HQ');
 await detach('预备群',nodes.slice(4,6),top);
 const scout=await detach('先遣群',nodes.slice(0,1),a);
 state=await read();check(state.groups.find(g=>g.id===scout).depth===2,'Three-level command tree created through UI');
 check(state.groups.find(g=>g.id===top).totals.current===18000,'HQ totals unique 18000 people, no parent double count');
 await panel.getByLabel('临时上级',{exact:true}).selectOption(b);
 await panel.getByLabel('转隶主攻群',{exact:true}).click();
 await panel.getByRole('status').filter({hasText:'临时配属已保存'}).waitFor();
 state=await read();check(state.groups.find(g=>g.id===a).parent_id===b,'Whole lower command subtree reparented');
 await panel.getByLabel('临时上级',{exact:true}).selectOption(scout);
 await panel.getByLabel('转隶会战指挥群',{exact:true}).click();
 await panel.getByRole('alert').filter({hasText:'循环'}).waitFor();
 state=await read();check(state.groups.find(g=>g.id===top).parent_id===null,'Cycle rejected without changing hierarchy');
 await panel.getByLabel('兵团下令对象',{exact:true}).selectOption(top);
 await panel.getByLabel('兵团行动',{exact:true}).selectOption('hold');
 await panel.getByRole('button',{name:'暂存群命令',exact:true}).click();
 await panel.getByRole('status').filter({hasText:'群命令已暂存'}).waitFor();
 const cs=await(await page.request.get(base+'/commands')).json();
 check(cs.orders.length===6&&new Set(cs.orders.map(o=>o.unit_id)).size===6,'Nested HQ dispatches six unique leaf orders');
 for(const width of [1440,900]){
  await page.setViewportSize({width,height:1000});await panel.locator('[data-task-group]').first().scrollIntoViewIfNeeded();
  check(await panel.isVisible(),width+'px hierarchy panel usable');
  await page.screenshot({path:'.cache/qa/force-hierarchy-2026-10-31/browser/hierarchy-'+width+'.png'});
 }
 await page.reload();await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
 await page.getByTestId('analysis-tab-forces').click();await panel.locator('[data-task-group]').first().waitFor();
 check((await panel.innerText()).includes('先遣群'),'Nested group survives reload');
 check(errors.length===0,'No page errors');
 return {passed:true,checks,api_mocks:false,model_calls:false,scope:'Real UI, 79 numerical QA leaves, command hierarchy only'};
}
