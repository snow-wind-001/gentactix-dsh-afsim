"""Run the composer UI flow; --live invokes DSH, --packaged preserves file renderer."""
import argparse
import json
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--live',action='store_true');p.add_argument('--packaged',action='store_true')
p.add_argument('--port',type=int,default=18912);p.add_argument('--session',default='history-process')
p.add_argument('--log',type=Path,default=ROOT/'.cache/qa/history-process/composer-browser.log')
p.add_argument('--fixture',type=Path,default=ROOT/'.cache/qa/history-process/composer-live-bound/generated.json',help='Prior genuine DSH-generated artifact; corresponding staged record must exist in this isolated backend')
a=p.parse_args();assert 18900<=a.port<=18999
code=(ROOT/'tools/qa/scenario_composer_browser.js').read_text().replace('18912',str(a.port))
if not a.live:
    fixture=json.loads(a.fixture.read_text())
    code=code.replace('const generationFixture = null;','const generationFixture = '+json.dumps(fixture,ensure_ascii=False)+';')
if a.packaged:
    code=code.replace("window.gentactix={backendUrl:'http://127.0.0.1:"+str(a.port)+"'};",'')
    code=code.replace("await page.goto('http://127.0.0.1:18901/');",'await page.reload();')
a.log.parent.mkdir(parents=True,exist_ok=True)
with a.log.open('w') as f:
    subprocess.run(['playwright-cli','-s='+a.session,'run-code',code],stdout=f,stderr=subprocess.STDOUT,check=True)
output=a.log.read_text()
if '### Error' in output or '"passed":true' not in output:
    raise SystemExit('Browser flow failed; inspect '+str(a.log))
