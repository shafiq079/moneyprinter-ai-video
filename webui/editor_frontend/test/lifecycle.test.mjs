import {test} from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import vm from 'node:vm';

test('Streamlit data updates reuse one root; obsolete cleanup cannot remove the live editor', async()=>{
  const {outputFiles}=await build({entryPoints:['src/workspace.tsx'],bundle:true,write:false,format:'cjs',
    jsx:'automatic',loader:{'.css':'empty'},external:['react','react-dom/client','@xzdarcy/react-timeline-editor']});
  const roots=[];
  const host={children:[],appendChild(element){this.children.push(element);element.parent=this;}};
  const context={module:{exports:{}},exports:{},document:{createElement(){return {dataset:{},remove(){this.parent.children.splice(this.parent.children.indexOf(this),1);}};}},
    require(name){
      if(name.endsWith('.css'))return {};
      if(name==='react-dom/client')return {createRoot(element){const root={element,renders:0,unmounted:false,
        render(){this.renders++;},unmount(){this.unmounted=true;}};roots.push(root);return root;}};
      if(name==='react/jsx-runtime')return {jsx:(type,props)=>({type,props})};
      if(name==='react')return {default:{}};
      if(name==='@xzdarcy/react-timeline-editor')return {};
      throw Error(name);
    }};
  vm.runInNewContext(outputFiles[0].text,context);
  const render=context.module.exports.default;
  const cleanups=[];
  for(let i=0;i<10;i++)cleanups.push(render({parentElement:host,data:{revision:i}}));
  assert.equal(host.children.length,1);assert.equal(roots.length,1);assert.equal(roots[0].renders,10);
  cleanups.slice(0,-1).forEach(cleanup=>cleanup());
  assert.equal(host.children.length,1);assert.equal(roots[0].unmounted,false);
  cleanups.at(-1)();assert.equal(host.children.length,0);assert.equal(roots[0].unmounted,true);
  render({parentElement:host,data:{}});assert.equal(host.children.length,1);assert.equal(roots.length,2);
});
