async page=>{
  const api='http://127.0.0.1:18990', ui='http://127.0.0.1:18981/', checks=[];
  await page.context().addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:18990'};});
  const response=await page.request.get(api+'/api/sessions');
  if(!response.ok())throw new Error(await response.text());
  const sessions=(await response.json()).sessions, snapshots=[];
  for(const s of sessions){
    const r=await page.request.get(api+'/api/sessions/'+s.session_id);
    if(!r.ok())throw new Error(await r.text());
    snapshots.push(await r.json());
  }
  const wuhan=snapshots.find(s=>s.war_state?.historical_initial?.profile_id==='AJ06-wuhan');
  const unprofiled=snapshots.find(s=>s.adjudication.battle_choice==='长平之战');
  if(!wuhan||!unprofiled)throw new Error('Run native v2 acceptance first');
  function check(ok,label){if(!ok)throw new Error(label);checks.push(label);}
  async function open(sid){
    await page.goto(ui);await page.evaluate(id=>localStorage.setItem('gentactix-session',id),sid);
    await page.reload();await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
    await page.getByTestId('map-workbench').waitFor();await page.locator('#analysis-tab-roster').click();
    await page.getByTestId('historical-roster').waitFor();
  }
  const errors=[];const listener=e=>errors.push(e.message);page.on('pageerror',listener);
  let unexpectedFetches=0;
  const url='**/api/historical-initial?*';
  await page.route(url,route=>{unexpectedFetches++;return route.fulfill({status:503,json:{detail:'Frozen profile must not fetch mutable index'}});});
  try{
    for(const width of [1440,900]){
      await page.setViewportSize({width,height:1000});await open(wuhan.session_id);
      const panel=page.getByTestId('historical-roster');
      await panel.getByText('本局固定档案',{exact:true}).waitFor();
      check((await page.locator('[data-historical-unit]').count())===118,`${width}: 118 fixed hierarchy entries`);
      await page.getByRole('searchbox',{name:'查找历史部队'}).fill('第74军');
      check((await page.locator('[data-historical-unit]').count())===3,`${width}: finds army and its two child divisions`);
      const first=page.locator('[data-historical-unit="ww2.cn.army74"]');
      await first.locator('summary').click();
      check((await first.locator('a').getAttribute('href')).includes('1538292922'),`${width}: per-unit source URL`);
      await page.getByRole('searchbox',{name:'查找历史部队'}).fill('');
      await page.getByLabel('历史部队阵营').selectOption('blue');
      check((await page.locator('[data-historical-unit]').count())===2,`${width}: blue commands shown separately`);
      check((await panel.innerText()).includes('未知')&&(await panel.innerText()).includes('待定位'),`${width}: unknown counts and positions visible`);
      await page.screenshot({path:`.cache/qa/historical-replay-v2/roster-${width}.png`});
      check((await page.locator('.nato-marker').count())===0,`${width}: unlocated references not drawn on the map`);
    }
    check(unexpectedFetches===0,'Frozen battle uses stored OOB; live index is not fetched');
  }finally{await page.unroute(url);}
  await open(unprofiled.session_id);
  await page.getByTestId('historical-roster-missing').waitFor();
  check((await page.locator('[data-historical-unit]').count())===0,'Unprofiled battle does not get fabricated formations');
  check(errors.length===0,'No browser page errors');page.removeListener('pageerror',listener);
  return {passed:true,checks,real_source_snapshot:true,user_sessions_modified:false,
    scope:'Historical roster references and UI; no claim of combat or full initial state'};
}
