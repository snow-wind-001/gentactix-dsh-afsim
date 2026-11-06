async page=>{
 const API='http://127.0.0.1:19116',checks=[],errors=[];
 const check=(ok,label)=>{if(!ok)throw Error(label);checks.push(label);};
 const get=async path=>{const r=await page.request.get(API+'/api'+path);if(!r.ok())throw Error(await r.text());return r.json();};
 const entry=(await get('/sessions')).sessions.find(s=>s.scenario.startsWith('单世界阶段采样说明复核；'));if(!entry)throw Error('Run message-probe first');
 const base='/sessions/'+entry.session_id,before=await get(base);page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(id=>{window.gentactix={backendUrl:'http://127.0.0.1:19116'};localStorage.setItem('gentactix-session',id);},entry.session_id);
 await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:19088');
 await page.getByRole('button',{name:'返回当前战局',exact:true}).click();await page.getByRole('button',{name:/目标与运行/}).click();
 const life=page.getByTestId('campaign-lifecycle');await life.waitFor({state:'visible'});
 check((await life.getByTestId('lifecycle-current').innerText()).includes('QA阶段2'),'UI identifies the stage activated at the last endpoint');
 await life.scrollIntoViewIfNeeded();await page.screenshot({path:'.cache/qa/campaign-lifecycle-2026-10-31/message-stage-1440.png'});
 const goals=page.getByTestId('campaign-objectives'),goal=goals.locator('[data-goal-id=milestone2]');await goal.scrollIntoViewIfNeeded();
 check((await goal.innerText()).includes('等待阶段采样'),'Activated-but-unobserved goal uses sampling status');
 check((await goal.innerText()).includes('本轮物理观察尚未轮到该阶段'),'Reason refers to actual observation scope rather than falsely denying activation');
 check((await goals.innerText()).includes('刚进入阶段的目标最早在下一轮评分'),'Stage/observation timing is explicitly explained');
 check(!(await goal.innerText()).includes('条件不成立'),'Unknown future predicate is not displayed as false');
 await page.setViewportSize({width:900,height:1000});await goal.scrollIntoViewIfNeeded();
 await page.screenshot({path:'.cache/qa/campaign-lifecycle-2026-10-31/message-goal-900.png'});
 const after=await get(base);check(after.turn_count===1&&JSON.stringify(after.war_state)===JSON.stringify(before.war_state),'Reading stage metadata does not repeat a turn or mutate the world');
 check(errors.length===0,'No browser page errors');
 return {passed:true,session_id:entry.session_id,checks,actual_afsim_input:true,api_mocks:false,model_calls:false};
}
