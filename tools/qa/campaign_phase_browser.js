async page => {
  const api='http://127.0.0.1:19093', sid='eeeeeeeeeeee', checks=[], errors=[];
  const check=(ok,message)=>{if(!ok)throw Error(message);checks.push(message);};
  page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:19093'};});
  await page.goto('http://127.0.0.1:19082');
  await page.evaluate(id=>localStorage.setItem('gentactix-session',id),sid);
  await page.reload();await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
  await page.getByRole('button',{name:'查看目标与结算',exact:true}).click();
  const phase=page.locator('[data-testid="phase-continuation"]:visible').first();
  await phase.locator('summary').first().click();
  await phase.getByRole('button',{name:'查找已验证配置',exact:true}).click();
  await phase.getByLabel('续接目标阶段').selectOption('a'.repeat(32));
  await phase.getByRole('button',{name:'检查继承账',exact:true}).click();
  const handoff=phase.getByTestId('phase-command-handoff');await handoff.waitFor();
  check((await handoff.innerText()).includes('续接 1'),'UI previews exactly one inherited command');
  for(const width of [1440,900]){
    await page.setViewportSize({width,height:1000});
    check(await handoff.isVisible(),width+'px: handoff status visible');
    await page.screenshot({path:'.cache/qa/campaign-contracts-2026-10-31/browser/preview-'+width+'.png'});
  }
  const response=page.waitForResponse(r=>r.url()===api+'/api/sessions/'+sid+'/phase-continuation'&&r.request().method()==='POST');
  await phase.getByRole('button',{name:'继承并打开下一阶段',exact:true}).click();
  const committed=await response;check(committed.ok(),'Actual phase commit succeeds');
  const result=await committed.json(),child=result.session_id;
  check(child!==sid,'New checkpoint has distinct identity');
  const org=await(await page.request.get(api+'/api/sessions/'+child+'/force-organization')).json();
  check(org.groups.length===1&&org.groups[0].label==='跨阶段阻援群','Organization survives actual frontend continuation');
  const cs=await(await page.request.get(api+'/api/sessions/'+child+'/commands')).json();
  check(cs.orders.length===1&&cs.orders[0].end_turn===3,'Remaining task duration preserved at three turns');
  await page.getByTestId('analysis-tab-forces').click();
  const panel=page.getByTestId('force-organization');await panel.waitFor();
  await panel.locator('[data-task-group]').first().waitFor();
  check((await panel.innerText()).includes('跨阶段阻援群'),'Inherited group visible in force panel');
  await panel.locator('[data-task-group]').first().scrollIntoViewIfNeeded();
  await page.screenshot({path:'.cache/qa/campaign-contracts-2026-10-31/browser/continued-group.png'});
  check(errors.length===0,'No page errors');
  return {passed:true,checks,source_session:sid,child_session:child,model_calls:false,api_mocks:false};
}
