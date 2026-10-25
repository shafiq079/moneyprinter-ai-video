import {build} from 'esbuild';
import {readFile,writeFile,mkdir,readdir} from 'node:fs/promises';
await mkdir('dist',{recursive:true});
await build({entryPoints:['src/workspace.tsx'],outdir:'dist',bundle:true,format:'esm',minify:true,
  jsx:'automatic',target:['es2020'],legalComments:'linked',define:{'process.env.NODE_ENV':'"production"'}});
// Distribute the upstream notices with our offline bundle, including transitive
// runtime dependencies. No third-party source or model asset is fetched at runtime.
const deps=[];
for (const entry of await readdir('node_modules',{withFileTypes:true})) {
  if (!entry.isDirectory() || entry.name.startsWith('.')) continue;
  if (entry.name.startsWith('@')) for(const child of await readdir(`node_modules/${entry.name}`)) deps.push(`${entry.name}/${child}`);
  else deps.push(entry.name);
}
let notices='MoneyPrinter editor workspace: bundled third-party notices\n\n';
for(const name of deps.sort()){
  const path=`node_modules/${name}`;
  try{
    const pkg=JSON.parse(await readFile(`${path}/package.json`,'utf8'));
    notices+=`\n--- ${name}@${pkg.version} (declared license: ${pkg.license||'see notice'}) ---\n`;
    for(const file of (await readdir(path)).filter(f=>/^licen[sc]e|^copying/i.test(f)).sort()){
      notices+=`${file}\n${await readFile(`${path}/${file}`,'utf8')}\n`;
    }
  }catch{}
}
for(const file of (await readdir('licenses')).sort()) notices+=`\n--- Upstream ${file} ---\n${await readFile(`licenses/${file}`,'utf8')}\n`;
await writeFile('dist/THIRD_PARTY_NOTICES.txt',notices.split('\n').map(line=>line.trimEnd()).join('\n').trimEnd()+'\n');
