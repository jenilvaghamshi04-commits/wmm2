/* Permission records are factual notes, not Telegram clearance or a ban guarantee. */
let outreachState=null;
window.renderOutreachSafety=function(data){
 outreachState=data;
 const s=data.outreach_safety;if(!s)return;
 const e=document.getElementById('outreachSummary');if(!e)return;
 const mode=!data.settings?.auto_yes_enabled&&!data.settings?.auto_followup_enabled;
 e.innerHTML=`<p class="notice"><b>Risk controls · ${esc(s.day)} · IST</b><br>Up to 10 unique recipients per account and 30 for the team. Counts reserve attempts conservatively, including uncertain submissions and follow-ups. These are internal caps, not Telegram allowances.</p><p class="hint">${mode?'Reviewed mode active: unattended promotional sequences are disabled.':'Action required: activate reviewed mode before sending.'}</p><div class="stats">${data.accounts.map(a=>`<article class="stat"><div class="statlabel">${esc(a.label||'Account '+a.id)}</div><strong>${Number(s.account_reserved[String(a.id)]||0)} / 10</strong><small>${a.error?'Needs review':a.blocked_until&&Date.parse(a.blocked_until)>Date.now()?'Paused':'No recorded restriction · not verified clearance'}</small></article>`).join('')}</div><p class="hint">Team reserved: ${Number(s.team_reserved)} / 30. Midnight IST reset; no manual reset. Original-account history stays locked.</p>`;
 document.getElementById('outreachAccounts').innerHTML=data.accounts.map(a=>`<article class="queue-item"><b>${esc(a.label||'Account '+a.id)}</b><p>${esc(a.error||'No account error recorded. This does not confirm unrestricted messaging.')}</p>${a.blocked_until?`<p class="hint">Recorded pause: ${esc(new Date(a.blocked_until).toLocaleString('en-IN',{timeZone:'Asia/Kolkata'}))} IST. An elapsed pause does not establish spam clearance.</p>`:''}</article>`).join('');
 document.getElementById('outreachMode').disabled=mode;
 const account=document.getElementById('permissionAccount'), prior=account.value;account.innerHTML=data.accounts.map(a=>`<option value="${a.id}">${esc(a.label||'Account '+a.id)}</option>`).join('');if(prior)account.value=prior;
 renderPermissionList();
 const note=document.getElementById('outreachGlobal');if(note)note.textContent='Outreach controls: permission required · 10/account · 30/team · restriction stops. No ban guarantee.';
};
function renderPermissionList(){
 const s=outreachState?.outreach_safety;if(!s)return;
 const query=document.getElementById('permissionSearch').value.trim().toLowerCase();
 const rows=s.contacts.filter(c=>(c.name+' '+c.username+' '+c.target).toLowerCase().includes(query));
 const select=document.getElementById('permissionPerson'),old=select.value;
 select.innerHTML='<option value="">Choose a saved person…</option>'+rows.map(c=>`<option value="${esc(c.target)}">${esc(c.name)} ${esc(c.username?'@'+c.username.replace(/^@/,''):'· '+c.target)}</option>`).join('');
 if(rows.some(c=>c.target===old))select.value=old;
 document.getElementById('permissionRecords').innerHTML=s.permissions.length?s.permissions.map(p=>{const c=s.contacts.find(c=>c.target===p.target);return `<article class="queue-item"><b>${esc(c?.name||p.target)} · ${esc(p.status)} · Account ${p.account_id}</b><p class="messagecopy">${esc(p.evidence)}</p><p class="hint">Updated ${esc(new Date(p.updated_at).toLocaleString('en-IN',{timeZone:'Asia/Kolkata'}))} IST</p></article>`}).join(''):'<p class="hint">No permissions recorded. New outreach is blocked until genuine permission is saved. No contacts are marked eligible automatically.</p>';
}
document.getElementById('permissionSearch').oninput=renderPermissionList;
document.getElementById('permissionPerson').onchange=()=>{
 const p=outreachState?.outreach_safety?.permissions.find(p=>p.target===document.getElementById('permissionPerson').value);
 document.getElementById('permissionStatus').value=p?.status||'Unknown';document.getElementById('permissionEvidence').value=p?.evidence||'';document.getElementById('permissionConfirmed').checked=false;if(p)document.getElementById('permissionAccount').value=p.account_id;
};
document.getElementById('permissionForm').onsubmit=e=>{e.preventDefault();action(document.getElementById('permissionSave'),async()=>{
 await rawApi('/outreach-permissions',{target:document.getElementById('permissionPerson').value,account_id:Number(document.getElementById('permissionAccount').value),status:document.getElementById('permissionStatus').value,evidence:document.getElementById('permissionEvidence').value,confirmed:document.getElementById('permissionConfirmed').checked});
 await refresh(false);toast('Permission record saved. This is not Telegram clearance.');
})};
document.getElementById('outreachMode').onclick=()=>action(document.getElementById('outreachMode'),async()=>{await rawApi('/outreach-reviewed-mode',{});await refresh(false);toast('Reviewed mode active. Automatic promotional sequences paused.');});

for(const id of ['globalAutoReplies','globalAutoFollowup']){const el=document.getElementById(id);if(el){el.disabled=true;el.title='Unattended promotional sequences are disabled by Outreach controls.'}}
