"""Prepare the explicit UI-only QA page, then serve frontend with Vite on 18983.

Run tools/qa/campaign_components_browser.js via playwright-cli against that page
and the existing QA preview on 18982. Remove frontend/.qa-campaign* afterwards.
"""
import json
from pathlib import Path
import shutil
from tools.qa.campaign_fixture import inputs
from gentactix.historical_operations import initial


def main():
    snapshot,parameters=inputs();ids=set(parameters['actors'])
    data={'parameters':parameters,'world':initial(snapshot,parameters),
          'actors':[u for u in snapshot['definition']['units'] if u['id'] in ids]}
    Path('frontend/.qa-campaign-data.json').write_text(json.dumps(data,ensure_ascii=False))
    shutil.copy2(Path(__file__).with_suffix('.html').with_name('campaign_components.html'),'frontend/.qa-campaign.html')


if __name__=='__main__':main()
