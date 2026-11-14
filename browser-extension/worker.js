let socket=null, currentToken=null, observedTabs=[];
async function status(text){await chrome.storage.local.set({connectionStatus:text});}
async function connect(){
 const cfg=await chrome.storage.local.get(['profileId','token','bridgePort']);if(!cfg.token)return;
 if(socket&&currentToken!==cfg.token){socket.close();socket=null;}
 if(socket && (socket.readyState===WebSocket.OPEN||socket.readyState===WebSocket.CONNECTING))return;
 const ws=new WebSocket(`ws://127.0.0.1:${Number(cfg.bridgePort)||8766}/profile`);socket=ws;currentToken=cfg.token;let pingTimer=null;
 ws.onopen=()=>{ws.send(JSON.stringify({profileId:cfg.profileId,token:cfg.token}));pingTimer=setInterval(()=>{if(ws.readyState===WebSocket.OPEN)ws.send(JSON.stringify({ping:true}));},20000);};
 ws.onmessage=async event=>{
  let message;try{message=JSON.parse(event.data);}catch{return;}
  if(message.connected){status('Connected');return;}
  if(message.pong)return;
  if(message.error&&!message.id){status(message.error);return;}
  if(!message.id||!message.command)return;
  try{
   const now=await chrome.storage.local.get('token');if(now.token!==currentToken)throw Error('Profile disconnected');
   const result=await perform(message.command,message.parameters||{});
   if(ws.readyState===WebSocket.OPEN)ws.send(JSON.stringify({id:message.id,result}));
  }catch(e){if(ws.readyState===WebSocket.OPEN)ws.send(JSON.stringify({id:message.id,error:e.message}));}
 };
 ws.onclose=()=>{clearInterval(pingTimer);if(socket===ws)socket=null;status('Disconnected; waiting for JARVIS');};
 ws.onerror=()=>status('JARVIS bridge is unavailable');
}
chrome.alarms.create('reconnect',{periodInMinutes:0.5});
chrome.alarms.onAlarm.addListener(a=>{if(a.name==='reconnect')connect();});
chrome.runtime.onStartup.addListener(connect);chrome.runtime.onInstalled.addListener(connect);
chrome.runtime.onMessage.addListener((message,sender,reply)=>{
 if(message.action==='connect'){connect().then(()=>reply({ok:true}));return true;}
 if(message.action==='disconnect'){chrome.storage.local.remove('token').then(()=>{if(socket)socket.close();reply({ok:true});});return true;}
});
function facts(tab,index){return {id:tab.id,tab_id:String(tab.id),index,window_id:tab.windowId,title:tab.title||'',url:tab.url||'',active:!!tab.active};}
async function listTabs(){
 const tabs=await chrome.tabs.query({});observedTabs=tabs.map(t=>t.id);
 const focused=await chrome.windows.getLastFocused();
 return tabs.map((tab,index)=>({...facts(tab,index),focused_window:tab.windowId===focused.id,selected:tab.active&&tab.windowId===focused.id}));
}
async function activeTab(){
 const [tab]=await chrome.tabs.query({active:true,lastFocusedWindow:true});
 if(!tab)throw Error('No active browser tab');return tab;
}
function matches(tab,query){const text=String(query||'').trim().toLocaleLowerCase();return (tab.title||'').toLocaleLowerCase().includes(text)||(tab.url||'').toLocaleLowerCase().includes(text);}
async function resolveTab(p,requireTarget=false,allowIndex=false){
 let tab;
 const hasId=p.tab_id!==undefined&&p.tab_id!==null&&String(p.tab_id)!=='';
 const query=String(p.tab_query||'').trim();
 if(hasId){
  const raw=String(p.tab_id);if(!/^\d+$/.test(raw))throw Error('Invalid tab_id; use the exact ID from list_tabs');
  try{tab=await chrome.tabs.get(Number(raw));}catch{throw Error('Target tab no longer exists. Refresh list_tabs; no other tab was used.');}
 }else if(query||p.expected_url){
  const tabs=await chrome.tabs.query({});
  const found=tabs.filter(t=>(!query||matches(t,query))&&(!p.expected_url||t.url===p.expected_url));
  if(found.length>1)throw Error('Ambiguous tab target: multiple tabs match. Use list_tabs and an exact tab_id with its title or URL.');
  if(!found.length)throw Error('No tab matches the requested target. Refresh list_tabs.');
  tab=found[0];
 }else if(allowIndex&&p.tab_index!==undefined){
  const index=Number(p.tab_index);
  if(!Number.isInteger(index)||index<0||index>=observedTabs.length)throw Error('Unknown tab index. Call list_tabs first and prefer tab_id.');
  try{tab=await chrome.tabs.get(observedTabs[index]);}catch{throw Error('Observed tab no longer exists; refresh list_tabs.');}
 }else if(p.current_tab===true||!requireTarget){tab=await activeTab();}
 else throw Error('Specify the target tab_id and tab_query/expected_url, a unique tab_query, or current_tab=true for an explicitly current-tab request.');
 if(p.current_tab===true&&(hasId||query||p.expected_url)){const current=await activeTab();if(current.id!==tab.id)throw Error('The requested target is not the current tab; refresh list_tabs.');}
 if(query&&!matches(tab,query))throw Error('Tab ID does not match the requested title or URL; no action was taken.');
 if(p.expected_url&&tab.url!==p.expected_url)throw Error('Tab URL changed since observation; no action was taken. Refresh list_tabs.');
 if(requireTarget&&!allowIndex&&hasId&&!query&&!p.expected_url&&p.current_tab!==true)throw Error('For a named tab, include tab_query or expected_url with tab_id to verify the target.');
 return tab;
}
async function closedTabs(){
 if(!await chrome.permissions.contains({permissions:['sessions']}))throw Error('Allow tab restoration from the JARVIS extension popup first.');
 return (await chrome.sessions.getRecentlyClosed({maxResults:25})).filter(s=>s.tab).map(s=>({session_id:s.tab.sessionId,title:s.tab.title||'',url:s.tab.url||'',last_modified:s.lastModified}));
}
function url(value){const text=String(value||'').trim();const result=new URL(text.includes('://')?text:`https://${text}`);if(!['http:','https:'].includes(result.protocol))throw Error('Only HTTP/HTTPS page navigation is supported');return result.href;}
async function perform(command,p){
 if(command==='list_tabs')return listTabs();
 if(command==='list_closed_tabs')return closedTabs();
 if(command==='restore_tab'){
  const rows=await closedTabs();let found;
  if(p.session_id)found=rows.filter(t=>t.session_id===p.session_id);
  else if(p.tab_query)found=rows.filter(t=>matches(t,p.tab_query));
  else found=rows.slice(0,1);
  if(!found.length)throw Error('No recently closed tab matches; no unrelated tab was restored.');
  if(found.length>1)throw Error('Multiple closed tabs match; use list_closed_tabs and an exact session_id.');
  const restored=await chrome.sessions.restore(found[0].session_id);
  if(!restored.tab)throw Error('Chrome did not return the restored tab');
  return {restored:true,...facts(restored.tab),tabs:await listTabs()};
 }
 if(command==='switch_tab'){
  const tab=await resolveTab(p,true,true);await chrome.tabs.update(tab.id,{active:true});await chrome.windows.update(tab.windowId,{focused:true});
  return {...facts(await chrome.tabs.get(tab.id)),selected:true};
 }
 if(command==='new_tab'){const tab=await chrome.tabs.create({url:p.url?url(p.url):'about:blank'});return {...facts(tab),url:tab.pendingUrl||tab.url,tabs:await listTabs()};}
 const tab=await resolveTab(p,command==='close_tab',false);
 if(command==='close_tab'){
  const closed=facts(tab);await chrome.tabs.remove(tab.id);
  const remaining=await listTabs();
  if(remaining.some(t=>t.tab_id===String(tab.id)))throw Error('Chrome did not close the requested tab');
  return {closed:true,...closed,tabs:remaining};
 }
 if(command==='go_to'||command==='search'){
  const target=command==='search'?`https://www.google.com/search?q=${encodeURIComponent(p.query||'')}`:url(p.url);
  await chrome.tabs.update(tab.id,{url:target});
  for(let attempt=0;attempt<50;attempt++){await new Promise(resolve=>setTimeout(resolve,200));const state=await chrome.tabs.get(tab.id);if(state.status==='complete'&&!state.pendingUrl)return {url:state.url,title:state.title,tab_id:String(tab.id),verified:true};}
  return {navigation_requested:target,tab_id:String(tab.id),verified:false};
 }
 if(command==='get_url')return {url:tab.url,title:tab.title,tab_id:String(tab.id)};
 if(command==='back'){await chrome.tabs.goBack(tab.id);return {requested:'back'};}
 if(command==='forward'){await chrome.tabs.goForward(tab.id);return {requested:'forward'};}
 if(command==='reload'){await chrome.tabs.reload(tab.id);return {requested:'reload'};}
 if(!/^https?:/.test(tab.url||''))throw Error('Chrome blocks extension access to internal/protected pages. Select a normal website.');
 const result=await chrome.scripting.executeScript({target:{tabId:tab.id},func:pageCommand,args:[command,p]});
 if(!result[0])throw Error('No page response');if(result[0].result?.error)throw Error(result[0].result.error);return result[0].result;
}
function pageCommand(command,p){
 const visible=e=>e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
 const label=e=>e.type==='password'?'Password field':e.getAttribute('aria-label')||e.labels?.[0]?.innerText||e.getAttribute('placeholder')||e.innerText||e.value||'';
 function find(){
  if(p.selector){const el=document.querySelector(p.selector);if(el&&visible(el))return el;throw Error('Selector did not match a visible element');}
  const text=String(p.description||p.text||'').trim().toLocaleLowerCase();if(!text)throw Error('Name the visible label or provide a selector');
  const all=[...document.querySelectorAll('button,a,input,textarea,select,[role="button"],[role="link"],[contenteditable="true"]')].filter(visible);
  return all.find(e=>label(e).trim().toLocaleLowerCase()===text)||all.find(e=>label(e).toLocaleLowerCase().includes(text));
 }
 try{
  if(command==='get_text')return {title:document.title,url:location.href,text:document.body.innerText.slice(0,14000),elements:[...document.querySelectorAll('button,a,input,textarea,select')].filter(visible).slice(0,60).map(e=>({tag:e.tagName,label:label(e).slice(0,100)}))};
  if(command==='scroll'){scrollBy(0,(p.direction==='up'?-1:1)*Number(p.amount||500));return {scrollY};}
  if(command==='fill_form'){
   let count=0;for(const [selector,value] of Object.entries(p.fields||{})){const el=document.querySelector(selector);if(!el||!visible(el))throw Error('Field not found: '+selector);setValue(el,String(value));count++;}return {fields_filled:count};
  }
  const el=find();if(!el)throw Error('No visible element matched the label');el.scrollIntoView({block:'center'});el.focus();
  if(command==='click'||command==='smart_click'){el.click();return {click_dispatched:label(el).slice(0,100),verify_with:'get_text'};}
  if(command==='type'||command==='smart_type'){if(el.type==='password')throw Error('Enter passwords directly in Chrome');setValue(el,p.clear_first===false?String(el.value||'')+String(p.text||''):String(p.text||''));return {typed:true};}
  if(command==='press'){const key=p.key||'Enter';el.dispatchEvent(new KeyboardEvent('keydown',{key,bubbles:true}));el.dispatchEvent(new KeyboardEvent('keyup',{key,bubbles:true}));return {key_event_dispatched:key,verified:false};}
  throw Error('Unsupported page command');
 }catch(e){return {error:e.message};}
 function setValue(el,value){
  if(el.type==='password')throw Error('Enter passwords directly in Chrome');
  if(el.isContentEditable)el.textContent=value;
  else {const proto=el instanceof HTMLTextAreaElement?HTMLTextAreaElement.prototype:el instanceof HTMLSelectElement?HTMLSelectElement.prototype:HTMLInputElement.prototype;const setter=Object.getOwnPropertyDescriptor(proto,'value')?.set;if(!setter)throw Error('Element is not an editable field');setter.call(el,value);}
  el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));
 }
}
connect();
