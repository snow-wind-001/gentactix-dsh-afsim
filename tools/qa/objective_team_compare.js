async page=>{
 const checks=[],check=(v,s)=>{if(!v)throw new Error(s);checks.push(s);};
 const sid=page.__objectiveSession,base='http://127.0.0.1:18998/api/sessions/'+sid;
 const factual=await(await page.request.get(base)).json();
 check(factual.turn_count===1&&factual.war_state.mission.progress===1,'real first move establishes blue control');
 check(factual.war_state.afsim.orders.length===2&&!factual.war_state.afsim.model_skipped,'native DSH orders both sourced formations');
 check(factual.war_state.current_time==='1951-10-05 04:30','exact 30-minute progression');
 for(const team of ['red','blue'])check(factual.war_state[team+'_units'].every(u=>u.personnel.casualties===0),'no invented '+team+' losses without fire');
 await page.getByTestId('top-status').click();const panel=page.getByTestId('mission-panel');
 check((await panel.getByTestId('mission-objective-owner').innerText()).includes('蓝方'),'goal owner visible in the live mission');
 check((await panel.innerText()).includes('历史局部目标'),'historical task is labelled as a local historical goal');
 await panel.getByText('目标进度、补给账与重放凭据',{exact:true}).click();
 const pending=page.waitForResponse(r=>r.url().endsWith('/counterfactual')&&r.request().method()==='POST',{timeout:120000});
 await panel.getByRole('button',{name:'对照上一轮：蓝方全部原地待命',exact:true}).click();
 const response=await pending,comparison=await response.json();page.__objectiveComparison=comparison;
 check(response.status()===200,'actual readonly native comparison succeeds');
 check(comparison.alternative.mission.progress===0,'holding the blue goal owner prevents control');
 check(comparison.alternative.mission.definition.objective_team==='blue','comparison preserves frozen blue ownership');
 const red=factual.war_state.red_units[0],altred=comparison.alternative.red_units[0];
 check(red.lat===altred.lat&&red.lng===altred.lng,'comparison keeps red withdrawal unchanged');
 check(JSON.stringify((await(await page.request.get(base)).json()).war_state)===JSON.stringify(factual.war_state),'comparison does not mutate the authoritative world');
 await page.screenshot({path:'.cache/qa/objective-team/comparison-1440.png'});
 return {passed:true,session_id:sid,checks,route_mocks:false};
}
