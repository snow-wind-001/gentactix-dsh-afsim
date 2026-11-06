#!/usr/bin/env python3
"""Fetch the reviewed release wheels, or verify an already downloaded directory."""
import argparse, hashlib, json
from pathlib import Path
from urllib.request import urlopen
p=argparse.ArgumentParser();p.add_argument('--directory',type=Path,default=Path(__file__).parent/'wheels');p.add_argument('--verify-only',action='store_true');a=p.parse_args()
m=json.loads(Path(__file__).with_name('sdk-wheels.json').read_text());a.directory.mkdir(parents=True,exist_ok=True)
for item in m['artifacts']:
 target=a.directory/item['filename']
 if not target.exists() and not a.verify_only:
  temporary=target.with_suffix('.download')
  with urlopen(m['release_base']+'/'+item['filename'],timeout=120) as response, temporary.open('wb') as output:
   while chunk:=response.read(1024*1024):output.write(chunk)
  temporary.replace(target)
 if not target.is_file() or target.stat().st_size!=item['bytes'] or hashlib.sha256(target.read_bytes()).hexdigest()!=item['sha256']:
  raise SystemExit('SDK artifact absent or checksum mismatch: '+target.name)
 print('Verified '+target.name)
