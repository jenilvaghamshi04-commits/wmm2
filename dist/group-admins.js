/* Joined groups, saved admin snapshots, and progressive account setup. */
let groupAdminSnapshots=[],joinedGroupChoices=[],joinedGroupAccount=null,joinedGroupPrincipal=null,accountSlotCount=1;
let groupAdminOpenKey,groupPageDelay=120,groupPageDelayDirty=false;
function visibleAccounts(){return accounts.filter(a=>a.id<=accountSlotCount||a.authorized||a.api_configured)}
function renderAccountSelectors(){
 const visible=visibleAccounts();
 for(const id of ['loginAccount','tgGroupAccount']){
  const node=document.getElementById(id),previous=node.value;
  node.innerHTML=visible.map(a=>`<option value="${a.id}">Account ${a.id} — ${esc(a.label)}${a.authorized?' ✓':''}</option>`).join('');
  if(visible.some(a=>String(a.id)===previous))node.value=previous;
 }
 document.querySelectorAll('[data-add-account]').forEach(b=>{b.hidden=visible.length>=3;b.disabled=!live;b.onclick=()=>action(b,async()=>{
  if(!serverFeatures.progressive_accounts)throw Error('Deploy the latest gateway on Render to add account slots.');
  const result=await api('/accounts/add',{});await refresh(false);document.getElementById('loginAccount').value=String(result.account_id);clearLogin();renderLogin();view('connections');toast('Account '+result.account_id+' added. Enter its API details and connect it.');
 })});
}
function applyAccountSetup(status){
 accountSlotCount=Math.max(1,Math.min(3,Number(status.account_slots)||Math.max(1,...accounts.filter(a=>a.authorized||a.api_configured).map(a=>a.id))));
 groupPageDelay=Number(status.settings?.send_delay_seconds)||120;renderGroupDelay();
 renderAccountSelectors();
}
function legacyGroupAdminSnapshots(){
 const groups=new Map();
 for(const p of people){
  if(p.kind==='group'||!p.scan_account||!p.group_id||p.is_bot)continue;
  const id=p.group_id+':'+p.scan_account;
  if(!groups.has(id)){const chat=people.find(c=>c.kind==='group'&&c.group_id===p.group_id);groups.set(id,{key:'legacy:'+id,group_id:p.group_id,name:p.group,username:p.group_username||chat?.username||'',account_id:p.scan_account,kind:'group',scraped_at:p.scanned_at||'',admins:[],legacy:true})}
  const g=groups.get(id);g.admins.push({name:p.name,username:p.username,user_id:p.user_id,role:p.admin_role||(p.role==='Owner'?'Owner':'Admin'),title:p.title||'',scraped_at:p.scanned_at||''});if((p.scanned_at||'')>g.scraped_at)g.scraped_at=p.scanned_at;
 }
 return [...groups.values()];
}
function groupAdminKey(group){return String(group.key||String(group.group_id||group.name)+':'+group.account_id)}
function groupAdminCards(groups,demo=false){return groups.map((g,index)=>`<details class="card tg-group-card" name="tg-admin-groups" data-group-key="${esc(groupAdminKey(g))}"${demo?' data-demo="true"':''}${groupAdminOpenKey===groupAdminKey(g)||groupAdminOpenKey===undefined&&index===0?' open':''}><summary class="tg-group-heading"><div><p class="eyebrow">${demo?'DEMO · '+(g.kind==='channel'?'CHANNEL':'GROUP'):(g.kind==='channel'?'CHANNEL':'GROUP')+' · ACCOUNT '+esc(g.account_id)}</p><h2>${esc(g.name)}</h2></div><span class="pill">${demo?'Demo · ':''}${g.admins.length} ${g.admins.length===1?'admin':'admins'}</span><svg class="tg-group-chevron" aria-hidden="true" viewBox="0 0 24 24"><path d="m6 9 6 6 6-6"/></svg></summary><div class="tg-group-body"><dl class="tg-group-details"><div><dt>Group / Channel Name</dt><dd>${esc(g.name)}</dd></div><div><dt>Group Username</dt><dd>${g.username?'@'+esc(g.username):'No public username available'}</dd></div></dl><div class="tablewrap"><table><thead><tr><th>Admin Full Name</th><th>Admin @Username</th><th>User ID</th><th>Role</th><th>Tag / Title (CEO etc)</th><th>Scraped At</th></tr></thead><tbody>${g.admins.length?g.admins.map(a=>`<tr><td>${adminBatchCheckbox(a,g,demo)}</td><td>${a.username?'@'+esc(a.username):'<span class="hint">Not available</span>'}</td><td class="tg-user-id">${esc(a.user_id)}</td><td><span class="roletag">${esc(a.role)}</span></td><td>${a.title?esc(a.title):'<span class="hint">No title</span>'}</td><td>${a.scraped_at?esc(new Date(a.scraped_at).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',hour12:true,timeZoneName:'short'})):'Not recorded'}</td></tr>`).join(''):'<tr><td colspan="6" class="tg-empty">No non-bot admin records were visible to this account.</td></tr>'}</tbody></table></div><p class="hint tg-group-footer">${demo?'Sample timestamp':'Saved'} ${g.scraped_at?esc(new Date(g.scraped_at).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',hour12:true,timeZoneName:'short'})):'previously'}${g.legacy?' · Earlier scan':''}${g.archive?' · '+esc(groupArchiveLabel(g.archive)):''}</p></div></details>`).join('')}
function newGroupAdminSnapshots(){return groupAdminSnapshots.filter(g=>g.collection_source==='automatic_join')}
function renderGroupWatch(){
 const root=document.getElementById('tgWatchAccounts');if(!root)return;
 root.innerHTML=visibleAccounts().map(a=>{const w=a.group_watch||{},paused=a.blocked_until&&new Date(a.blocked_until)>new Date();
 const state=!a.authorized?'Connect this account':paused?'Paused by Telegram':!serverFeatures.new_group_watch?'Gateway update required':w.error||(!w.ready?'Recording existing groups…':'Watching for new groups');
 return `<div class="tg-watch-account"><b>Account ${a.id} · ${esc(a.label)}</b><span class="hint">${esc(state)}</span>${w.ready?`<small class="hint">Started ${esc(new Date(w.started_at).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',hour12:true,timeZoneName:'short'}))} · ${Number(w.saved)||0} collected · ${Number(w.pending)||0} pending${w.unavailable?' · '+Number(w.unavailable)+' unavailable':''}</small>`:''}</div>`}).join('');
}
function renderGroupAdmins(){
 const root=document.getElementById('tgGroupRecords');if(!root)return;renderAdminBatchBar();renderGroupWatch();renderDailyProgress();
 const expanded=root.querySelector?.('details[data-group-key][open]');
 if(expanded)groupAdminOpenKey=expanded.dataset.groupKey;else if(root.querySelector?.('details[data-group-key]'))groupAdminOpenKey=null;
 renderGroupDelay();
 const q=document.getElementById('tgAdminSearch').value.trim().toLowerCase();
 const source=newGroupAdminSnapshots();
 const groups=source.slice().sort((a,b)=>(b.scraped_at||'').localeCompare(a.scraped_at||'')).filter(g=>[g.name,g.username,...g.admins.flatMap(a=>[a.name,a.username,a.user_id,a.role,a.title])].join(' ').toLowerCase().includes(q));
 document.getElementById('tgGroupCount').textContent=source.length+' saved '+(source.length===1?'group':'groups');
 document.getElementById('tgGroupGatewayHint').textContent=!live?'Connect your gateway and Telegram account to start watching new groups.':!serverFeatures.new_group_watch?'Deploy gateway v3.14 on Render to enable automatic collection.':'Checks run every 5 minutes while the gateway is running. New groups are read one at a time, at least 2 minutes apart. Refresh saved data to see the latest results.';
 if(groupAdminOpenKey!==null&&groupAdminOpenKey!==undefined&&!groups.some(g=>groupAdminKey(g)===groupAdminOpenKey))groupAdminOpenKey=groups[0]?groupAdminKey(groups[0]):undefined;
 root.innerHTML=groups.length?groupAdminCards(groups):'<div class="card tg-empty"><h2>'+ (q?'No matching new groups':'Waiting for your next group')+'</h2><p class="hint">'+(q?'Try another group, admin name or username.':'After monitoring starts, join a new group in Telegram. Its visible admins and titles will appear here automatically. Earlier groups are excluded.')+'</p></div>';
}
function resetJoinedGroupPicker(){joinedGroupChoices=[];joinedGroupAccount=null;joinedGroupPrincipal=null;document.getElementById('tgJoinedGroup').innerHTML='<option value="">Load new groups first…</option>';document.getElementById('tgJoinedGroup').disabled=true;document.getElementById('getGroupAdmins').disabled=true;document.getElementById('tgGroupsStatus').textContent=''}
function groupReadReady(){
 if(!live)throw Error('Connect your gateway first.');
 if(!serverFeatures.group_admin_directory)throw Error('Deploy the latest gateway on Render to use joined groups.');
 const id=Number(document.getElementById('tgGroupAccount').value),account=accounts.find(a=>a.id===id);
 if(!account?.authorized)throw Error('Connect Account '+id+' in Settings first.');
 if(account.blocked_until&&new Date(account.blocked_until)>new Date())throw Error('This account is paused until '+new Date(account.blocked_until).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',hour12:true,timeZoneName:'short'})+'. Saved admin records are still available.');
 return id;
}
document.addEventListener('DOMContentLoaded',()=>{
 initializeAdminBatch();
 document.getElementById('tgPageDelay').onchange=()=>{groupPageDelayDirty=true};
 document.getElementById('tgSaveDelay').onclick=()=>action(document.getElementById('tgSaveDelay'),async()=>{
  if(!live||!serverFeatures.send_pacing)throw Error('Connect your gateway to save the message delay.');
  const seconds=Number(document.getElementById('tgPageDelay').value);
  await api('/sending-pace',{delay_seconds:seconds});groupPageDelayDirty=false;await refresh(false);renderGroupDelay();toast('Message delay saved: '+seconds/60+' minutes.');
 });
 document.getElementById('tgAdminSearch').oninput=renderGroupAdmins;
 document.getElementById('tgGroupAccount').onchange=()=>{resetJoinedGroupPicker();document.getElementById('tgGroupsStatus').textContent='Click Refresh new groups for the selected account.'};
 document.getElementById('addNewGroupData').onclick=()=>action(document.getElementById('addNewGroupData'),async()=>{document.getElementById('tgNewGroupPicker').hidden=false;await loadNewJoinedGroups()});
 document.getElementById('tgJoinedGroup').onchange=()=>{document.getElementById('getGroupAdmins').disabled=!document.getElementById('tgJoinedGroup').value};
 document.getElementById('loadJoinedGroups').onclick=()=>action(document.getElementById('loadJoinedGroups'),loadNewJoinedGroups);
 document.getElementById('getGroupAdmins').onclick=()=>action(document.getElementById('getGroupAdmins'),async()=>{
  const id=groupReadReady(),groupId=document.getElementById('tgJoinedGroup').value;
  if(joinedGroupAccount!==id||!joinedGroupChoices.some(g=>g.group_id===groupId))throw Error('Load joined groups for the selected account first.');
  if(!serverFeatures.new_group_picker_archive)throw Error('Deploy gateway v3.15 on Render to collect and archive new groups.');
  document.getElementById('tgGroupsStatus').textContent='Saving visible admins, then archiving this group…';
  try{const result=await api('/groups/new/admins',{account_id:id,group_id:groupId,watch_principal:joinedGroupPrincipal});await refresh(false);resetJoinedGroupPicker();document.getElementById('tgGroupsStatus').textContent=result.count+' visible admins saved for '+result.group+'. '+groupArchiveLabel(result.archive);toast('Admin data saved. '+groupArchiveLabel(result.archive));
  }catch(error){document.getElementById('tgGroupsStatus').textContent=error.message;try{await refresh(false)}catch{}throw error}
 });
 document.getElementById('refreshGroupAdminData').onclick=()=>action(document.getElementById('refreshGroupAdminData'),()=>refresh(false));
 renderAccountSelectors();renderGroupAdmins();
});
async function loadNewJoinedGroups(){
 const id=groupReadReady();resetJoinedGroupPicker();
 if(!serverFeatures.new_group_picker_archive)throw Error('Deploy gateway v3.15 on Render to use Add new group data.');
 document.getElementById('tgGroupsStatus').textContent='Checking new joined groups for Account '+id+'…';
 try{const result=await api('/groups/new',{account_id:id});joinedGroupChoices=result.groups;joinedGroupAccount=id;joinedGroupPrincipal=result.watch_principal;
  const node=document.getElementById('tgJoinedGroup');node.innerHTML='<option value="">Choose a new joined group…</option>'+joinedGroupChoices.map(g=>`<option value="${esc(g.group_id)}">${esc(g.name)}${g.username?' · @'+esc(g.username):''}${g.status==='Unavailable'?' · previous read unavailable':''}</option>`).join('');node.disabled=!joinedGroupChoices.length;
  document.getElementById('tgGroupsStatus').textContent=joinedGroupChoices.length?joinedGroupChoices.length+' new joined groups available. Choose one, then Get admins & archive.':'No new unsaved groups found. Earlier groups are excluded; already collected groups appear below.';
 }catch(error){document.getElementById('tgGroupsStatus').textContent=error.message;throw error}
}
function groupArchiveLabel(archive){return !archive?'':archive.status==='Archived'?'Archived in Telegram.':archive.status==='Pending'?'Archive pending · admin data is saved.':archive.error||'Archive: '+archive.status}

function renderGroupDelay(){
 const select=document.getElementById('tgPageDelay');if(!select)return;
 if(!groupPageDelayDirty)select.value=String(groupPageDelay);
 document.getElementById('tgSaveDelay').disabled=!live||!serverFeatures.send_pacing;
 document.getElementById('tgPageDelayHint').textContent='Current minimum: '+groupPageDelay/60+' minutes per account. A longer delay selected for a queued batch stays in place.';
}

function renderDailyProgress(){
 const root=document.getElementById('tgDailyProgress');if(!root)return;
 root.innerHTML=visibleAccounts().map(a=>{
  const ready=a.daily_progress,paused=a.blocked_until&&new Date(a.blocked_until)>new Date();
  const rows=['dm','group'].map(kind=>{const q=ready?.[kind]||{...(a.usage?.[kind]||{}),sent:null,queued:queuedSends.filter(j=>j.account_id===a.id&&j.kind===kind&&j.status==='Queued').length};
   const limit=Number(q.limit)||(kind==='dm'?15:30),used=Number(q.used)||0,queued=Number(q.queued)||0,remaining=Math.max(0,Number(q.remaining)||0),pct=Math.min(100,used/limit*100),reserve=Math.min(100-pct,queued/limit*100);
   return `<div class="tg-progress-row"><div class="tg-progress-label"><b>${kind==='dm'?'New DM contacts':'Group messages'}</b><span>${limit} daily limit</span></div><div class="tg-progress-track" role="progressbar" aria-label="Account ${a.id} ${kind==='dm'?'new DM contacts':'group messages'} allowance used or reserved" aria-valuemin="0" aria-valuemax="${limit}" aria-valuenow="${Math.min(limit,used+(ready?queued:0))}"><span class="tg-progress-used" style="width:${pct}%"></span>${ready?`<span class="tg-progress-queued" style="width:${reserve}%"></span>`:''}</div><dl class="tg-progress-counts"><div><dt>${ready?'Sent':'Slots used'}</dt><dd>${ready?Number(q.sent)||0:used}</dd></div><div><dt>Queued</dt><dd>${queued}</dd></div><div><dt>Remaining</dt><dd>${remaining}</dd></div></dl>${q.other_used?`<small class="hint">${Number(q.other_used)} additional attempts use allowance; check delivery status.</small>`:''}${kind==='dm'&&q.queued_messages>queued?`<small class="hint">${q.queued_messages-queued} queued repeat DMs use no new-contact slots.</small>`:''}</div>`;
  }).join('');
  return `<article class="card tg-progress-card"><div class="tg-progress-heading"><b>Account ${a.id} · ${esc(a.label)}</b><span class="pill">${!a.authorized?'Not connected':paused?'Paused':'Connected'}</span></div>${rows}<p class="hint tg-progress-foot">${ready?'Remaining excludes queued allowance. Resets at midnight IST.':'Deploy gateway v3.16 for confirmed sent totals and queued reservations.'}</p></article>`;
 }).join('');
}
