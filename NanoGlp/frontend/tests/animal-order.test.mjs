import assert from 'node:assert/strict';
import {test,after} from 'node:test';
import {mkdtemp,rm} from 'node:fs/promises';
import {dirname,join} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import React from 'react';
import {create,act} from 'react-test-renderer';
const root=dirname(fileURLToPath(import.meta.url)),temp=await mkdtemp(join(root,'.animal-'));
after(()=>rm(temp,{recursive:true,force:true}));
const entry=join(temp,'animal.mjs');await build({entryPoints:[join(root,'../src/components/AnimalOrder.jsx')],outfile:entry,bundle:true,platform:'node',format:'esm',packages:'external'});
const {default:Animal}=await import(pathToFileURL(entry));
const txt=n=>n.children.map(c=>typeof c==='string'?c:txt(c)).join('');
test('server defaults and two distinct actions have no client identity fields',async()=>{
 let actions=[];const props={busy:false,onAction:b=>actions.push(b)};
 const step={can_edit:true,done:false,order_defaults:{order_date:'2026-11-06',estimated_delivery_days:15}};
 const view=create(React.createElement(Animal,{...props,step}));
 try{
  await act(async()=>view.root.findByType('button').props.onClick());assert.deepEqual(actions,[{action:'order',order_date:'2026-11-06',estimated_delivery_days:15}]);
  await act(async()=>view.update(React.createElement(Animal,{...props,step:{...step,animal_order:{order_date:'2026-11-06',ordered_by:'Ordering SD',expected_delivery_date:'2026-11-21',estimated_delivery_days:15},animal_status:'Sipariş Verildi — Teslim Bekleniyor'}})));
  assert.match(txt(view.root),/Ordering SD/);assert.match(txt(view.root),/Teslim Bekleniyor/);
  await act(async()=>view.root.findAllByType('button').find(b=>txt(b)==='Kabulü Onayla').props.onClick());
  assert.deepEqual(actions[1],{action:'receive',received_date:'2026-11-06'});
 }finally{view.unmount();}
});
test('receipt and order identities are shown separately; old completion invents none',()=>{
 const step={done:true,can_edit:false,animal_order:{order_date:'2026-11-05',ordered_by:'SD A',expected_delivery_date:'2026-11-20',received_date:'2026-11-06',received_by:'TFM B'}};
 const view=create(React.createElement(Animal,{step}));
 try{assert.match(txt(view.root),/SD A/);assert.match(txt(view.root),/TFM B/);assert.equal(view.root.findAllByType('button').length,0);
 view.update(React.createElement(Animal,{step:{done:true,can_edit:false}}));assert.match(txt(view.root),/ayrıntıları kayıtlı değil/);assert.doesNotMatch(txt(view.root),/SD A|TFM B/);
 }finally{view.unmount();}
});
