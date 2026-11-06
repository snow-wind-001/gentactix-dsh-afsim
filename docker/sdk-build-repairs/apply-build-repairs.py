from pathlib import Path
p=Path('scripts/build-exe-for-python-sdk.ts');s=p.read_text()
a="      '--legacy',\n";b="      '--legacy',\n      '--config.pnpmfile='+path.resolve('.gentactix-locked-deploy.cjs'),\n"
# Upstream imports may use a namespace; use the absolute cwd without assumptions.
b="      '--legacy',\n      '--config.pnpmfile='+process.cwd()+'/.gentactix-locked-deploy.cjs',\n"
if "--config.pnpmfile=" not in s:
 assert s.count(a)==1;s=s.replace(a,b)
a="      '--sea',\n"
if "      'GZip'," not in s:
 assert s.count(a)==1;s=s.replace(a,a+"      '--compress',\n      'GZip',\n")
p.write_text(s)
