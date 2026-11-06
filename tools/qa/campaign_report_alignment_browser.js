async page=>{
 const API='http://127.0.0.1:19115',checks=[],errors=[];
 const check=(ok,label)=>{if(!ok)throw Error(label);checks.push(label);};
 const get=async path=>{const r=await page.request.get(API+'/api'+path);if(!r.ok())throw Error(await r.text());return r.json();};
 page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19115'});
 await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:19088');
 const entries=(await get('/sessions')).sessions;
 for(const [name,turn] of [['afsim',2],['narrative',2],['报告最终源码首轮 confirmed-first',1]]){
  const entry=entries.find(s=>s.scenario.startsWith('持续任务验收 '+name+'；'));
  if(!entry)throw Error('Actual case missing: '+name);
  const snapshot=await get('/sessions/'+entry.session_id),world=JSON.stringify(snapshot.war_state);
  check(snapshot.turn_count===turn,name+' expected real backend round');
  await page.evaluate(id=>localStorage.setItem('gentactix-session',id),entry.session_id);await page.reload();
  await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
  await page.getByRole('tab',{name:'动态战报',exact:true}).click();
  const report=page.locator('.reports .report').first();await report.waitFor({state:'visible'});
  const prose=await report.innerText();
  check(prose.includes('T+'+turn)&&prose.includes(snapshot.war_state.current_time),name+' rendered round and clock match committed state');
  check(!(turn>1&&prose.includes('首轮执行'))&&!prose.includes('待后续回合观察确认')
   &&!prose.includes('非战局首轮编号')&&!prose.includes('各方向目标尚未经物理观察评分'),name+' known contradictory source prose is absent');
  check(prose.includes('第161师万家岭投入部'),name+' partial formation scope retained');
  if(turn===2)check(prose.includes('南侧方向控制：当前条件成立；目标条件满足'),name+' completed south goal uses same-frame host result');
  if(name==='narrative'){
   const previous=page.locator('.reports .report').nth(1);await previous.scrollIntoViewIfNeeded();
   check((await previous.innerText()).includes('原模型文字触发事实校验'),'Earlier conservative fallback remains visible with explanation');
   await report.scrollIntoViewIfNeeded();
  }
  const trace=await get('/sessions/'+entry.session_id+'/traces/'+turn),issues=trace.record.guards.report.issues;
  check(!issues.some(i=>['narrative_turn','goal_verdict'].includes(i.code)),name+' fresh current source has no known turn/goal contradiction');
  if(name==='报告最终源码首轮 confirmed-first'){
   check(!issues.some(i=>i.code==='inventory_claim'),name+' zero-expenditure source is not rejected as ammunition exhaustion');
   await page.setViewportSize({width:900,height:1000});
   const box=await page.getByTestId('analysis-panel').boundingBox();
   check(!!box&&box.x>=0&&box.x+box.width<=900,'Report panel remains within 900 px viewport');
   await page.screenshot({path:'.cache/qa/campaign-report-alignment-2026-10-31/ui-report-900.png'});
   await page.setViewportSize({width:1440,height:1000});
  }
  await page.screenshot({path:'.cache/qa/campaign-report-alignment-2026-10-31/'+name+'-report.png'});
  const after=await get('/sessions/'+entry.session_id);
  check(after.turn_count===turn&&JSON.stringify(after.war_state)===world,name+' review causes no physical mutation or duplicate step');
 }
 check(errors.length===0,'No browser page errors');
 return {passed:true,checks,api_mocks:false,actual_model_input:true,actual_afsim_input:true};
}
