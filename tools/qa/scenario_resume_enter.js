async page => {
 const generated=page.__resumeResult;
 if(generated?.http!==200||generated.body.kind!=='historical_operation')throw Error('Actual completed Native configuration required');
 const button=page.getByTestId('launch-start');if(!await button.isEnabled())throw Error('Verified configuration not enterable');
 const creation=page.waitForResponse(r=>r.url().endsWith('/api/sessions')&&r.request().method()==='POST',{timeout:120000});
 const initialization=page.waitForResponse(r=>r.url().endsWith('/init')&&r.request().method()==='POST',{timeout:120000});
 await button.click();const created=await creation;const initial=await initialization;
 if(!created.ok()||!initial.ok())throw Error('Create/init failed');
 const snap=await initial.json();page.__resumeSnapshot=snap;
 await page.getByTestId('map-workbench').waitFor({timeout:60000});
 const units=[...snap.war_state.red_units,...snap.war_state.blue_units];
 if(units.length!==34||new Set(units.map(u=>u.historical_unit_id)).size!==34)throw Error('Missing or duplicated source unit');
 const markers=await page.locator('.nato-marker').count();if(markers!==34)throw Error('34markers required');
 if(snap.war_state.afsim?.entity_count!==34)throw Error('Native load entity count mismatch');
 await page.screenshot({path:'.cache/qa/scenario-resume-2026-11-01/browser-34-initial.png'});
 page.__resumeEnter={passed:true,session_id:snap.session_id,identities:units.length,markers,
  scope:page.__enterScope??'Actual frontend create/init;20revalidated old actors+14new real model actors, not full historical process'};
 return page.__resumeEnter;
}
