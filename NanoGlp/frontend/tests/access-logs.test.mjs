import assert from 'node:assert/strict';
import {test,after} from 'node:test';
import {mkdtemp,rm} from 'node:fs/promises';
import {dirname,join} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import React from 'react';
import {create,act} from 'react-test-renderer';
const root=dirname(fileURLToPath(import.meta.url)),temp=await mkdtemp(join(root,'.access-'));
after(()=>rm(temp,{recursive:true,force:true}));
const entry=join(temp,'access.mjs');
await build({stdin:{resolveDir:root,contents:`export {AuthProvider,useAuth} from '../src/state/AuthContext.jsx'; export {default as AccessLogs,formatAccessTime} from '../src/pages/AccessLogs.jsx'; export {default as Guard} from '../src/components/ProtectedRoute.jsx'; export {default as Sidebar} from '../src/components/Sidebar.jsx';`},outfile:entry,bundle:true,platform:'node',format:'esm',packages:'external',plugins:[{name:'boundaries',setup(b){
 b.onResolve({filter:/services\/api$|^react-router-dom$/},a=>({path:a.path,namespace:'fixture'}));
 b.onLoad({filter:/.*/,namespace:'fixture'},({path})=>({resolveDir:root,contents:path==='react-router-dom'?`import React from 'react'; export const useLocation=()=>({pathname:'/access-logs'}); export const Navigate=()=>React.createElement('span',null,'Redirect'); export const NavLink=({to,children})=>React.createElement('a',{href:to},typeof children==='function'?children({isActive:false}):children);`:`export const TOKEN_STORAGE_KEY='token'; export const USER_STORAGE_KEY='user'; export const getMe=()=>globalThis.accessFixture.getMe(); export const loginApi=()=>{}; export const logoutApi=()=>globalThis.accessFixture.logout(); export const getAccessLogs=params=>globalThis.accessFixture.logs(params); export const extractError=(_,fallback)=>fallback;`}));
}}]});
const {AuthProvider,useAuth,AccessLogs,formatAccessTime,Guard,Sidebar}=await import(pathToFileURL(entry));
const txt=n=>n.children.map(c=>typeof c==='string'?c:txt(c)).join('');
function setup(role='SYSADMIN'){
 const storage=new Map();globalThis.localStorage={getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)};
 const user={id:1,username:'unrelated-name',role,full_name:'User',allowed_menus:['users','access_logs','samples']};
 storage.set('token','jwt');storage.set('user',JSON.stringify(user));globalThis.window=new EventTarget();
 const f=globalThis.accessFixture={user,requests:[],logoutCalls:0,getMe:async()=>({data:user}),logout:async()=>{f.logoutCalls++;},logs:async params=>{f.requests.push(params);return{data:{items:[{id:1,created_at:'2026-11-05T22:30:00+00:00',event_type:'LOGIN',username:'snapshot',role:'TFM'}],total:51}}}};
 return f;
}
function Probe(){const a=useAuth();return React.createElement('button',{onClick:a.logout},a.isAuthenticated?'Signed in':'Signed out');}
async function mount(child){let v;await act(async()=>{v=create(React.createElement(AuthProvider,null,child));});return v;}
test('explicit logout sends request before clearing and still clears on failure/401 without loops',async()=>{
 const f=setup();f.logout=async()=>{f.logoutCalls++;assert.equal(localStorage.getItem('token'),'jwt');window.dispatchEvent(new Event('nanolab:unauthorized'));throw new Error('401');};
 const v=await mount(React.createElement(Probe));
 try{await act(async()=>v.root.findByType('button').props.onClick());assert.equal(f.logoutCalls,1);assert.equal(localStorage.getItem('token'),null);assert.equal(txt(v.root),'Signed out');}finally{v.unmount();}
});
test('expired token local cleanup never sends LOGOUT',async()=>{
 const f=setup();f.getMe=async()=>{window.dispatchEvent(new Event('nanolab:unauthorized'));throw new Error('expired');};
 const v=await mount(React.createElement(Probe));try{assert.equal(f.logoutCalls,0);assert.equal(localStorage.getItem('token'),null);}finally{v.unmount();}
});
for(const role of ['SYSADMIN','ADMIN','TFM','QA','STUDY_DIRECTOR','EXECUTIVE','CUSTOM']){
 test(`${role}: menu, route and screen require actual sysadmin role`,async()=>{
  const f=setup(role);const allowed=['SYSADMIN','ADMIN'].includes(role);
  const v=await mount(React.createElement(React.Fragment,null,React.createElement(Sidebar),React.createElement(Guard,{sysadminOnly:true},React.createElement('p',null,'Protected content')),React.createElement(AccessLogs)));
  try{assert.equal(v.root.findAllByType('a').some(a=>a.props.href==='/access-logs'),allowed);assert.equal(txt(v.root).includes('Protected content'),allowed);assert.equal(f.requests.length,allowed?1:0);}finally{v.unmount();}
 });
}
test('Istanbul timestamps and local date/user/event filters with pagination',async()=>{
 const f=setup();const v=await mount(React.createElement(AccessLogs));
 try{
  assert.match(formatAccessTime('2026-11-05T22:30:00+00:00'),/6\.11\.2026.*01:30:00/);
  for(const [label,value] of [['Kullanıcı','sample-user'],['Başlangıç tarihi','2026-11-06'],['Bitiş tarihi','2026-11-07'],['Olay türü','LOGIN_FAILED']]){
   await act(async()=>v.root.findByProps({'aria-label':label}).props.onChange({target:{value}}));
  }
  await act(async()=>v.root.findByType('form').props.onSubmit({preventDefault(){}}));
  assert.deepEqual(f.requests.at(-1),{user:'sample-user',event_type:'LOGIN_FAILED',date_from:'2026-11-06',date_to:'2026-11-07',page:1,page_size:50});
  await act(async()=>v.root.findAllByType('button').find(b=>txt(b)==='Sonraki').props.onClick());assert.equal(f.requests.at(-1).page,2);
 }finally{v.unmount();}
});
