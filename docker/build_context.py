#!/usr/bin/env python3
"""Create an explicit delivery context; never send the developer checkout wholesale."""
import argparse, hashlib, json, shutil
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--source',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--out',type=Path,required=True);p.add_argument('--sdk-wheels',type=Path,required=True);p.add_argument('--afsim-runtime',type=Path);a=p.parse_args()
root=a.source.resolve();out=a.out.resolve()
if out.exists():raise SystemExit('Output must not already exist')
out.mkdir(parents=True)
ignore=shutil.ignore_patterns('__pycache__','*.pyc','.git','node_modules','.cache','.pytest_cache','.env','.env.*','*.enc','*.key','wheels')
for name in ('backend','gentactix','corpus','adjudication','plugins'):
 shutil.copytree(root/name,out/name,ignore=ignore)
shutil.copytree(root/'data',out/'data',ignore=lambda directory,names:[n for n in names if n=='military-symbols-v2' or n in ignore(directory,names)])
for name in ('afsim-mcp','afsim-skill'):
 shutil.copytree(root/'vendor/afsim'/name,out/'vendor/afsim'/name,ignore=ignore)
for name in ('README.md','dependencies.lock.json'):
 shutil.copy2(root/'vendor/afsim'/name,out/'vendor/afsim'/name)
shutil.copytree(root/'tools/afsim',out/'tools/afsim',ignore=ignore)
(out/'frontend').mkdir()
for name in ('src','public'):shutil.copytree(root/'frontend'/name,out/'frontend'/name,ignore=ignore)
for name in ('package.json','package-lock.json','index.html','vite.config.ts'):shutil.copy2(root/'frontend'/name,out/'frontend'/name)
for file in(root/'frontend').glob('tsconfig*.json'):shutil.copy2(file,out/'frontend'/file.name)
for name in ('LICENSE','NOTICE.md'):shutil.copy2(root/name,out/name)
shutil.copytree(Path(__file__).parent,out/'docker',ignore=ignore)
(out/'docker/wheels').mkdir()
manifest=json.loads((out/'docker/sdk-wheels.json').read_text())
for item in manifest['artifacts']:
 file=a.sdk_wheels/item['filename']
 if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest()!=item['sha256']:raise SystemExit('SDK checksum failed: '+file.name)
 shutil.copy2(file,out/'docker/wheels'/file.name)
if a.afsim_runtime:
 if not (a.afsim_runtime/'bin/mission.exe').is_file():raise SystemExit('AFSIM runtime must contain bin/mission.exe')
 shutil.copytree(a.afsim_runtime/'bin',out/'afsim-runtime/bin',ignore=ignore)
 for file in (out/'afsim-runtime/bin').rglob('*'):
  file.chmod(0o755 if file.is_dir() else 0o644)
 (out/'afsim-runtime/bin').chmod(0o755)
 shutil.copy2(Path(__file__).with_name('AFSIM-DISTRIBUTION-NOTICE.txt'),out/'afsim-runtime/AFSIM-DISTRIBUTION-NOTICE.txt')
 # Do not remove DLLs or embedded notices. Additional runtime resources can be
 # deliberately added only after the corresponding application scenario requires them.
(out/'.dockerignore').write_text('**/__pycache__\n**/*.pyc\n**/node_modules\n**/.git\n**/.env*\n**/*.enc\n**/*.key\n')
files={str(f.relative_to(out)):{'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'bytes':f.stat().st_size}for f in out.rglob('*')if f.is_file()}
for name in files:
 if any(part in ('.git','node_modules','wineprefix','state','sessions')for part in Path(name).parts) or name.endswith(('.enc','.key')):raise SystemExit('Forbidden context path: '+name)
(out.parent/(out.name+'-manifest.json')).write_text(json.dumps({'files':files,'bytes':sum(v['bytes']for v in files.values())},ensure_ascii=False,indent=2))
print('Prepared',len(files),'files;',sum(v['bytes']for v in files.values()),'bytes')
