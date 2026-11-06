async page => {
 const generated=page.__estimateBuild;
 if(generated?.http!==200)throw Error('Real1.3 Native generation has not completed');
 if(generated.body.construction.source!=='dsh_native_skill')throw Error('Native source missing');
 const start=page.getByTestId('launch-start');
 if(!await start.isEnabled())throw Error('Validated configuration cannot enter');
 const created=page.waitForResponse(r=>/\/api\/sessions$/.test(r.url())&&r.request().method()==='POST',{timeout:120000});
 const initialized=page.waitForResponse(r=>r.url().endsWith('/init')&&r.request().method()==='POST',{timeout:120000});
 await start.click();
 const creation=await created;const initial=await initialized;
 if(!creation.ok()||!initial.ok())throw Error('Session creation or initialization rejected');
 const snap=await initial.json();page.__campaignSnap=snap;
 await page.getByTestId('map-workbench').waitFor({timeout:60000});
 const units=[...snap.war_state.red_units,...snap.war_state.blue_units];
 if(units.length!==22||new Set(units.map(u=>u.historical_unit_id)).size!==22)throw Error('Historical identity missing or counted twice');
 if(await page.locator('.nato-marker').count()!==22)throw Error('Not all22 actors rendered');
 const window=snap.war_state.mission.definition.historical_calculation.parameters.campaign_scope.window;
 if(window.definition.version!=='1.3.0')throw Error('Wrong frozen calculation window');
 if(snap.war_state.afsim?.entity_count!==22)throw Error('Native world entity count differs');
 await page.screenshot({path:'.cache/qa/wanjialing-estimates-2026-11-01/browser-rc5/initial-130.png'});
 return {passed:true,session_id:snap.session_id,actors:units.length,markers:22,actual_afsim:true,actual_native_builder:true,window_version:window.definition.version,not_historical_calibration:true};
}
