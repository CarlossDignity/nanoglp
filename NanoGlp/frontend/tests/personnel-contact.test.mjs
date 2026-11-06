import assert from 'node:assert/strict';
import {test,after} from 'node:test';
import {mkdtemp,rm} from 'node:fs/promises';
import {dirname,join} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import React from 'react';
import {create,act} from 'react-test-renderer';
const root=dirname(fileURLToPath(import.meta.url)), temp=await mkdtemp(join(root,'.contact-'));
after(()=>rm(temp,{recursive:true,force:true}));
const entry=join(temp,'component.mjs');
await build({entryPoints:[join(root,'../src/components/PersonnelContact.jsx')],outfile:entry,bundle:true,platform:'node',format:'esm',packages:'external',plugins:[{name:'api',setup(b){
 b.onResolve({filter:/services\/api$/},a=>({path:a.path,namespace:'fixture'}));
 b.onLoad({filter:/.*/,namespace:'fixture'},()=>({contents:'export const updatePersonnelContact=(...args)=>globalThis.saveContact(...args); export const extractError=(_,fallback)=>fallback;'}));
}}]});
const {default:Contact}=await import(pathToFileURL(entry));
test('contact editor submits only contact fields and supports clearing',async()=>{
 let calls=[],saved=0;globalThis.saveContact=async(...args)=>calls.push(args);
 let view;await act(async()=>{view=create(React.createElement(Contact,{person:{personnel_id:5,email:'old@example.com',phone:'555'},canEdit:true,onSaved:()=>saved++}));});
 try{
  await act(async()=>view.root.findByType('button').props.onClick());
  await act(async()=>{for(const input of view.root.findAllByType('input'))input.props.onChange({target:{value:''}});});
  await act(async()=>view.root.findByType('form').props.onSubmit({preventDefault(){}}));
  assert.deepEqual(calls,[[5,{email:null,phone:null}]]);assert.equal(saved,1);
 }finally{view.unmount();}
});
test('read-only display keeps contacts visible without edit controls',async()=>{
 const view=create(React.createElement(Contact,{person:{email:'person@example.com',phone:null},canEdit:false}));
 try{assert.equal(view.root.findAllByType('button').length,0);assert.match(JSON.stringify(view.toJSON()),/person@example.com/);assert.match(JSON.stringify(view.toJSON()),/TBD/);}finally{view.unmount();}
});
