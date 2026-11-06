async page=>{
 let created;
 if(await page.getByTestId('launch-start').count()){
  const text=await page.getByTestId('historical-validation').innerText();
  if(!text.includes('AFSIM实际装载'))throw new Error(text);
  const waiting=page.waitForResponse(r=>/\/api\/sessions$/.test(r.url())&&r.request().method()==='POST');
  await page.getByTestId('launch-start').click();created=await(await waiting).json();
 }else created={session_id:await page.evaluate(()=>localStorage.getItem('gentactix-session'))};
 await page.getByTestId('map-workbench').waitFor();
 const snap=await(await page.request.get('http://127.0.0.1:18998/api/sessions/'+created.session_id)).json();
 const ids=[...snap.war_state.red_units,...snap.war_state.blue_units].map(u=>u.historical_unit_id);
 if(ids.length!==2||!ids.includes('ww2.cn.division31')||!ids.includes('ww2.jp.seya_detachment'))throw new Error('Dedicated battle imported the wrong actor set');
 if(snap.war_state.mission.definition.battle!=='抗日战争-台儿庄战役-1938.03.23至1938.04.07')throw new Error('Wrong battle binding');
 const saved=await(await page.request.get('http://127.0.0.1:18998/api/sessions/'+created.session_id+'/export')).json();
 if(!saved.session.use_rag)throw new Error('Source retrieval was disabled');
 if(await page.locator('.nato-marker').count()!==2)throw new Error('Actual actors missing from the map');
 await page.screenshot({path:'.cache/qa/ww2-phases/taierzhuang-initial.png'});
 return {passed:true,session_id:created.session_id,ids,source:snap.war_state.afsim.source,entities:snap.war_state.afsim.entity_count,use_rag:saved.session.use_rag,route_mocks:false};
}
