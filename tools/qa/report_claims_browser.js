async page => {
  const API='http://127.0.0.1:19122',OUT='.cache/qa/report-claim-screening-2026-11-01';
  const checks=[],errors=[],result={passed:false,actual_model:true,api_mocks:false,actual_afsim:false,checks};
  const check=(ok,label)=>{if(!ok)throw Error(label);checks.push(label);};
  const get=async path=>{const r=await page.request.get(API+'/api'+path);if(!r.ok())throw Error(await r.text());return r.json();};
  const sid='7cda77706dab',base='/sessions/'+sid,old=await get(base);
  check(old.turn_count===5,'Continue retained T+5 QA world without rebuilding its initial state');
  page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(id=>{window.gentactix={backendUrl:'http://127.0.0.1:19122'};localStorage.setItem('gentactix-session',id);},sid);
  await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:19089');
  await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
  try {
    const began=Date.now(),next=page.waitForResponse(r=>r.url()===API+'/api'+base+'/next'&&r.request().method()==='POST',{timeout:1800000});
    await page.getByRole('button',{name:'推进一轮',exact:true}).click();
    await page.getByRole('button',{name:'取消',exact:true}).waitFor();
    await page.screenshot({path:OUT+'/real-in-progress.png'});
    const response=await next;if(!response.ok())throw Error(await response.text());const after=await response.json();
    result.seconds=(Date.now()-began)/1000;result.session_id=sid;result.turn=after.turn_count;
    check(after.turn_count===6,'One successful action commits exactly T+6');
    check(after.war_state.simulation_clock.elapsed_seconds===old.war_state.simulation_clock.elapsed_seconds+1800,'Clock advances exactly30 minutes');
    const units=w=>[...w.red_units,...w.blue_units],prior=Object.fromEntries(units(old.war_state).map(u=>[u.name,u]));
    check(units(after.war_state).length===6,'All six existing execution identities remain');
    check(units(after.war_state).every(u=>JSON.stringify(u.personnel)===JSON.stringify(prior[u.name].personnel)),'Personnel account remains continuous');
    check(units(after.war_state).every(u=>u.logistics.food===prior[u.name].logistics.food-2&&u.logistics.ammo===prior[u.name].logistics.ammo),'Food charged once and no invented ammunition expenditure');
    const trace=(await get(base+'/export')).trajectory.at(-1),audit=trace.guards.report;
    result.audit={status:audit.status,issues:audit.issues,preview:audit.preview,characters:audit.original_text.length};result.engine_meta=after.engine_meta;
    check(audit.preview.report_source==='dsh_native_report_tool','Actual Native structured report supplies current prose');
    check(audit.issues.length===0&&audit.status==='screened','New actual public report passes known-claim screening');
    check(!after.war_state.afsim,'No AFSIM effect substitutes for the real DSH process');
    check(after.engine_meta.json_recoveries===0,'No free-text JSON recovery is needed');
    await page.getByRole('tab',{name:'动态战报'}).click();
    check(await page.locator('.reports').innerText().then(text=>text.includes(audit.original_text.slice(0,30))),'Actual model prose is displayed in the report panel');
    await page.screenshot({path:OUT+'/real-report-1440.png'});
    await page.reload();await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
    check(JSON.stringify((await get(base)).war_state)===JSON.stringify(after.war_state),'Browser refresh retains the exact committed world');
    check(errors.length===0,'No browser JavaScript exception');
    result.passed=true;
  } catch(error) {result.error=String(error);}
  result.scope='Six-identity estimated QA world, actual Native report and frontend; not full historical campaign or universal semantic verification';
  return result;
}
