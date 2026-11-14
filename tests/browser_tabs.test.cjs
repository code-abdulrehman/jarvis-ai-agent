const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
function browser(){
 let nextId=100;const closed=[];
 const tabs=new Map([
  [11,{id:11,title:'GitHub',url:'https://github.com/',active:true,index:0,windowId:1}],
  [22,{id:22,title:'New tab',url:'about:blank',active:false,index:1,windowId:1}],
  [33,{id:33,title:'Orca',url:'https://orca.dev/',active:false,index:2,windowId:1}],
 ]);
 const chrome={
  storage:{local:{get:async()=>({}),set:async()=>{},remove:async()=>{}}},
  alarms:{create(){},onAlarm:{addListener(){}}},
  runtime:{onStartup:{addListener(){}},onInstalled:{addListener(){}},onMessage:{addListener(){}}},
  permissions:{contains:async()=>true},
  windows:{getLastFocused:async()=>({id:1}),update:async()=>({id:1})},
  tabs:{
   query:async q=>[...tabs.values()].filter(t=>!q.active||t.active).map(t=>({...t})),
   get:async id=>{if(!tabs.has(id))throw Error('No tab with id');return {...tabs.get(id)};},
   update:async(id,updates)=>{const t=tabs.get(id);if(!t)throw Error('Unknown tab');if(updates.active)for(const other of tabs.values())other.active=false;Object.assign(t,updates);return {...t};},
   remove:async id=>{const t=tabs.get(id);if(!t)throw Error('Unknown tab');closed.unshift({lastModified:Date.now()/1000,tab:{...t,sessionId:'closed-'+id}});tabs.delete(id);},
   create:async opts=>{const tab={id:nextId++,title:opts.url,url:opts.url,active:true,index:tabs.size,windowId:opts.windowId||1};for(const t of tabs.values())t.active=false;tabs.set(tab.id,tab);return {...tab};},
  },
  sessions:{getRecentlyClosed:async()=>closed,restore:async sessionId=>{const index=closed.findIndex(x=>x.tab.sessionId===sessionId);if(index<0)throw Error('Closed session missing');const old=closed.splice(index,1)[0].tab;const restored={...old,id:nextId++,active:true};delete restored.sessionId;tabs.set(restored.id,restored);return {tab:restored};}},
  scripting:{executeScript:async target=>[{result:{target:target.target.tabId}}]},
 };
 const context=vm.createContext({chrome,console,URL,setInterval,clearInterval,setTimeout,Date});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../browser-extension/worker.js'),'utf8'),context);
 return {tabs,closed,run:(command,params={})=>vm.runInContext(`perform(${JSON.stringify(command)},${JSON.stringify(params)})`,context)};
}
test('close Orca by stable ID leaves GitHub and blank tab intact',async()=>{
 const b=browser();await b.run('list_tabs');
 const result=await b.run('close_tab',{tab_id:'33',tab_query:'orca'});
 assert.equal(result.tab_id,'33');assert.equal(b.tabs.has(11),true);assert.equal(b.tabs.has(22),true);assert.equal(b.tabs.has(33),false);
});
test('mismatched title and ID cannot close a different tab',async()=>{
 const b=browser();await assert.rejects(b.run('close_tab',{tab_id:'11',tab_query:'orca'}),/match/i);assert.equal(b.tabs.size,3);
});
test('missing or stale close target never falls back to first tab',async()=>{
 const b=browser();await assert.rejects(b.run('close_tab'),/target|specify|tab_id/i);
 await assert.rejects(b.run('close_tab',{tab_id:'999',tab_query:'orca'}),/exist|found|unknown|stale/i);assert.equal(b.tabs.size,3);
});
test('duplicate tab names require a unique target',async()=>{
 const b=browser();b.tabs.set(44,{id:44,title:'Orca docs',url:'https://orca.dev/docs',active:false,index:3,windowId:1});
 await assert.rejects(b.run('close_tab',{tab_query:'orca'}),/ambiguous|multiple/i);assert.equal(b.tabs.size,4);
});
test('explicit tab ID targets reads and actual active tab follows user changes',async()=>{
 const b=browser();await b.run('switch_tab',{tab_id:'33'});
 const explicit=await b.run('get_url',{tab_id:'11'});assert.equal(explicit.url,'https://github.com/');
 b.tabs.get(33).active=false;b.tabs.get(22).active=true;
 const active=await b.run('get_url');assert.equal(active.url,'about:blank');
});
test('restore Orca restores that closed session and stale ID cannot close GitHub',async()=>{
 const b=browser();await b.run('close_tab',{tab_id:'33',tab_query:'orca'});
 const result=await b.run('restore_tab',{tab_query:'orca'});
 assert.equal(result.url,'https://orca.dev/');assert.notEqual(result.tab_id,'33');
 await assert.rejects(b.run('close_tab',{tab_id:'33',tab_query:'orca'}),/exist|found|unknown|stale/i);assert.equal(b.tabs.has(11),true);
});
test('switch index refers to last observed tab identity, not reordered position',async()=>{
 const b=browser();await b.run('list_tabs');
 const orca=b.tabs.get(33);b.tabs.delete(33);const entries=[...b.tabs];b.tabs.clear();b.tabs.set(33,orca);for(const [id,t]of entries)b.tabs.set(id,t);
 const result=await b.run('switch_tab',{tab_index:2});assert.equal(String(result.tab_id),'33');
});

test('a current-tab flag cannot redirect an explicit target to another tab',async()=>{
 const b=browser();await assert.rejects(b.run('close_tab',{tab_id:'33',current_tab:true}),/current tab/i);assert.equal(b.tabs.size,3);
});
