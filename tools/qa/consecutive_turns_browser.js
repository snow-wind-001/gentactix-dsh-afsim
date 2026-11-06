async (page, {frontendUrl,backendUrl,sessionId,turns=60}) => {
  // Prepared QA checkpoint only. Every order and turn is submitted through UI.
  await page.addInitScript(({backendUrl,sessionId})=>{
    window.gentactix={backendUrl};localStorage.setItem('gentactix-session',sessionId);
  },{backendUrl,sessionId});
  await page.goto(frontendUrl);
  await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
  await page.getByTestId('command-toggle').click();
  const panel=page.getByTestId('command-panel');
  await panel.getByText('控制范围与全局约束',{exact:true}).click();
  await panel.getByLabel('教学导演：允许控制双方').check();
  let response=page.waitForResponse(r=>r.url().endsWith('/commands')&&r.request().method()==='PUT');
  await panel.getByRole('button',{name:'保存控制设置',exact:true}).click();
  if(!(await response).ok())throw Error('控制设置未保存');
  const data=await (await page.request.get(backendUrl+'/api/sessions/'+sessionId+'/commands')).json();
  for(const u of data.units){
    await panel.getByLabel('单位名单（含无坐标单位）').selectOption(u.id);
    await panel.getByTestId('unit-action').selectOption('hold');
    await panel.getByLabel('准备行动持续方式').selectOption('until_turn');
    await panel.getByLabel('准备行动截止回合').fill(String(turns));
    response=page.waitForResponse(r=>r.url().endsWith('/commands')&&r.request().method()==='PUT');
    await panel.getByTestId('enqueue-order').click();
    if(!(await response).ok())throw Error('待命命令未入队');
  }
  await page.getByTestId('command-toggle').click();
  const rows=[];
  for(let turn=1;turn<=turns;turn++){
    const response=page.waitForResponse(r=>r.url().endsWith('/next'),{timeout:180000});
    await page.getByRole('button',{name:'推进一轮',exact:true}).click();
    const r=await response,body=await r.json();
    if(!r.ok()||body.turn_count!==turn)throw Error(JSON.stringify(body));
    rows.push({turn,status:r.status()});
    // No wait for the asynchronous command-panel watcher: consecutive clicks
    // reproduce the stale-revision failure that previously appeared at T16.
  }
  return {turns:rows.length,rows,next_disabled:await page.getByRole('button',{name:'推进一轮',exact:true}).isDisabled()};
}
