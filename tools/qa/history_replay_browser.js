async page => {
  await page.setViewportSize({width:1440,height:1000});
  await page.goto('http://127.0.0.1:18901/?history_acceptance='+Date.now());
  await page.getByRole('textbox',{name:'搜索战役'}).fill('湘江');
  await page.locator('.battle-option').first().click();
  await page.getByRole('button',{name:/继续配置/}).click();
  await page.locator('#draft-mode').selectOption('replay');
  await page.waitForFunction(()=>document.querySelector('#draft-executor').value==='afsim' && !document.querySelector('#draft-mission'));
  const initialized=page.waitForResponse(r=>r.url().endsWith('/init'));
  await page.getByRole('button',{name:'创建并进入推演',exact:true}).click();
  const response=await initialized,initial=await response.json();
  if(!response.ok())throw new Error(JSON.stringify(initial));
  await page.getByTestId('history-replay').waitFor();
  if(!(await page.getByLabel('本轮决策意图').isDisabled()))throw new Error('historical commands enabled');
  if(await page.getByRole('button',{name:'🗺️ 态势与战损',exact:true}).count())throw new Error('unknown losses shown as open-model ledger');
  const id=initial.session_id,total=initial.war_state.history_replay.total;
  for(let turn=0;turn<total-1;turn++){
    const done=page.waitForResponse(r=>r.url().endsWith('/next'));
    await page.getByRole('button',{name:'⏩ 下一史料事件',exact:true}).click();
    const next=await done,snap=await next.json();
    if(!next.ok()||snap.turn_count!==turn+1)throw new Error(JSON.stringify(snap));
    if(snap.war_state.red_units.length||snap.war_state.blue_units.length)throw new Error('invented deployment');
    if(snap.afsim.phase!=='historical_replay'||snap.afsim.source!=='dsh_native_mcp_controller')throw new Error('not real native source replay');
  }
  await page.getByTestId('history-replay').waitFor();
  await page.waitForTimeout(300);
  if(!(await page.getByRole('button',{name:'⏩ 下一史料事件',exact:true}).isDisabled()))throw new Error('replay did not terminate');
  await page.screenshot({path:'.cache/qa/combined-arms/history-wide.png'});
  await page.setViewportSize({width:820,height:900});
  await page.screenshot({path:'.cache/qa/combined-arms/history-narrow.png'});
  return {passed:true,session_id:id,frames:total,commands_disabled:true,unknown_deployment_preserved:true};
}
