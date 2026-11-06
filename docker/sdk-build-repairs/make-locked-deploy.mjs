import {readFileSync,writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {createRequire} from 'node:module';
const root=resolve(process.argv[2] ?? process.cwd());
const require=createRequire(root+'/package.json');
const lock=require('js-yaml').load(readFileSync(root+'/pnpm-lock.yaml','utf8'));
const entries={};
for(const [path,row] of Object.entries(lock.importers)){
 const file=resolve(root,path,'package.json');let pkg;try{pkg=JSON.parse(readFileSync(file,'utf8'));}catch{continue;}
 entries[pkg.name+'@'+pkg.version]=Object.fromEntries(['dependencies','optionalDependencies'].map(k=>[k,Object.fromEntries(Object.entries(row[k]??{}).map(([n,v])=>[n,v.version]))]));
}
for(const [key,row] of Object.entries(lock.snapshots)){
 const base=key.split('(')[0];
 const data=Object.fromEntries(['dependencies','optionalDependencies'].map(k=>[k,Object.fromEntries(Object.entries(row[k]??{}).map(([n,v])=>[n,v.split('(')[0]]))]));
 const rows=entries[base]??{}; for(const kind of ['dependencies','optionalDependencies']){rows[kind]??={};for(const [name,version]of Object.entries(data[kind])){const prior=rows[kind][name];rows[kind][name]=[...new Set([...(Array.isArray(prior)?prior:prior?[prior]:[]),version])];}}entries[base]=rows;
}
const code=`// Local packaging repair: resolve legacy deploy exclusively through the reviewed workspace lock.\nconst entries=${JSON.stringify(entries)}; const semver=require(${JSON.stringify(require.resolve('semver'))});\nmodule.exports={hooks:{readPackage(pkg){const locked=entries[pkg.name+'@'+pkg.version];if(!locked)return pkg;for(const kind of ['dependencies','optionalDependencies'])for(const [name,range]of Object.entries(pkg[kind]??{})){const versions=locked[kind]?.[name];if(!versions||range.startsWith('workspace:')||range.startsWith('link:')||range.startsWith('file:'))continue;const options=(Array.isArray(versions)?versions:[versions]).filter(v=>semver.valid(v)&&semver.satisfies(v,range));if(options.length)pkg[kind][name]=options.sort(semver.compare)[0];}return pkg;}}};\n`;
writeFileSync(resolve(root,'.gentactix-locked-deploy.cjs'),code);
console.log('Locked dependency edge records:',Object.keys(entries).length);
