"""Reuse the full packaged-workbench flow and add delayed progress assertions."""
from pathlib import Path
import subprocess

root=Path(__file__).resolve().parents[2]
code=(root/'tools/qa/map_workbench_packaged.js').read_text().replace('3.4.0','3.4.1').replace('.cache/qa/map-workbench/','.cache/qa/turn-feedback/')
needle="  const done=page.waitForResponse(r=>r.url()===API+path+'/next',{timeout:120000});"
assert code.count(needle)==1
code=code.replace(needle,"""  await page.route(API+path+'/next',async route=>{await page.waitForTimeout(2200);await route.continue();},{times:1});
"""+needle)
needle="  await page.getByRole('button',{name:'推进一轮',exact:true}).click();"
assert code.count(needle)==1
code=code.replace(needle,needle+"""
  const bar=page.getByTestId('operation-progress');await bar.waitFor({state:'visible'});
  assert(await bar.getAttribute('data-state')==='running','packaged pending indicator visible');
  assert(await bar.getAttribute('aria-valuenow')===null,'packaged waiting has no invented percent');
  await page.waitForFunction(()=>{const el=document.querySelector('[data-testid=operation-elapsed]');return el&&el.textContent!=='00:00';});
  checks.push('packaged elapsed timer updates');
  await page.screenshot({path:'.cache/qa/turn-feedback/packaged-waiting.png'});
""")
subprocess.run(['playwright-cli','-s=feedback-packaged','run-code',code],check=True)
