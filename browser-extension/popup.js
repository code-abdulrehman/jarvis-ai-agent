const $ = id => document.getElementById(id);
chrome.storage.local.get(['profileName','bridgePort','connectionStatus']).then(v=>{
  $('name').value=v.profileName||'';$('port').value=v.bridgePort||8766;$('status').textContent=v.connectionStatus||'Not connected';
});
$('pair').onclick=async()=>{
 try{
  const allowed=await chrome.permissions.request({origins:['http://*/*','https://*/*']});
  if(!allowed)throw Error('Website access was not granted. Nothing was paired.');
  const port=Number($('port').value);if(!Number.isInteger(port)||port<1024||port>65535)throw Error('Enter a valid bridge port.');
  const saved=await chrome.storage.local.get('profileId');const profileId=saved.profileId||crypto.randomUUID();
  const name=$('name').value.trim()||'Chrome profile';
  const response=await fetch(`http://127.0.0.1:${port}/pair`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:$('code').value.trim(),profileId,name})});
  const data=await response.json();if(!response.ok)throw Error(data.detail||'Pairing failed');
  await chrome.storage.local.set({profileId,profileName:name,bridgePort:port,token:data.token,connectionStatus:'Connecting'});
  $('code').value='';await chrome.runtime.sendMessage({action:'connect'});$('status').textContent='Paired. Connection status appears in JARVIS Workspace.';
 }catch(e){$('status').textContent=e.message;}
};
$('disconnect').onclick=async()=>{await chrome.runtime.sendMessage({action:'disconnect'});$('status').textContent='Disconnected. Pair again to reconnect.';};
