async page=>{
 const checked=await page.getByTestId('historical-validation').innerText();
 if(!checked.includes('AFSIM实际装载'))throw new Error(checked);
 if(await page.locator('[data-historical-actor]').count()!==2)throw new Error('Expected two sourced actors');
 const response=page.waitForResponse(r=>/\/api\/sessions$/.test(r.url())&&r.request().method()==='POST');
 await page.getByTestId('launch-start').click();const result=await(await response).json();
 await page.getByTestId('map-workbench').waitFor();
 const snapshot=await(await page.request.get('http://127.0.0.1:18998/api/sessions/'+result.session_id)).json();
 const ids=[...snapshot.war_state.red_units,...snapshot.war_state.blue_units].map(u=>u.historical_unit_id);
 if(ids.length!==2||!ids.includes('kw.cn.regiment354')||!ids.includes('kw.rok.regiment2.battalion3'))throw new Error('Wrong initial identities');
 await page.screenshot({path:'.cache/qa/korean-first/opening-workbench.png'});
 return {session_id:result.session_id,ids,source:snapshot.war_state.afsim.source,entities:snapshot.war_state.afsim.entity_count,route_mocks:false};
}
