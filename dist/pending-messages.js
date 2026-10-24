/* Read the original backend queue; never create or resend messages on this page. */
(function(root){
  const active=new Set(['Queued','Scheduled','Waiting for sign-in','Sending','Needs attention','Missed']);
  function build(queue=[],schedules=[]){
    const rows=queue.map(q=>({...q,source:'backend',id:q.queue_id,due_at:q.next_attempt_at||null}));
    const ids=new Set(queue.map(q=>q.queue_id));
    for(const s of schedules){if(s.backend_queue_id&&ids.has(s.backend_queue_id))continue;rows.push({...s,source:'schedule',id:s.schedule_id,due_at:s.scheduled_at,kind:'dm'})}
    const groups=new Map();
    for(const row of rows){const key=row.batch_id?'batch:'+row.batch_id:'single:'+row.source+':'+row.id;if(!groups.has(key))groups.set(key,[]);groups.get(key).push(row)}
    return [...groups].map(([key,items])=>{
      items.sort((a,b)=>(Date.parse(a.due_at||a.created_at)||0)-(Date.parse(b.due_at||b.created_at)||0));
      const pending=items.filter(q=>active.has(q.status));
      return {key,rows:items,pending,total:items.length,sent:items.filter(q=>q.status==='Sent').length,account_id:items[0].account_id,batch:!!items[0].batch_id,delay_seconds:Math.max(0,...items.map(q=>Number(q.delay_seconds)||0)),due_at:Math.min(...pending.map(q=>Date.parse(q.due_at)||Infinity))};
    }).filter(g=>g.pending.length).sort((a,b)=>a.due_at-b.due_at);
  }
  function countdown(row,now=Date.now()){
    if(row.status==='Sent')return 'Sent';if(row.status==='Cancelled')return 'Cancelled';
    if(row.status==='Sending')return 'Sending now';
    if(row.status==='Waiting for sign-in')return 'Sign-in required';
    if(['Needs attention','Missed'].includes(row.status))return 'Paused · review';
    const due=Date.parse(row.due_at);if(!Number.isFinite(due))return 'Waiting for queue';
    const seconds=Math.ceil((due-now)/1000);if(seconds<=0)return 'Due · waiting for queue';
    const h=Math.floor(seconds/3600),m=Math.floor(seconds%3600/60),s=seconds%60;
    return (h?h+'h ':'')+(m||h?m+'m ':'')+s+'s';
  }
  function issues(groups,accounts=[],clientErrors=[]){
    const result=[],seen=new Set(),add=item=>{const key=[item.account_id,item.recipient,item.message].join('|');if(!seen.has(key)){seen.add(key);result.push(item)}};
    for(const g of groups){
      const account=accounts.find(a=>String(a.id)===String(g.account_id));
      if(account&&!account.authorized)add({account_id:g.account_id,title:'Original account disconnected',message:'Connect the original Telegram account in Settings. Pending messages will not switch to another sender.'});
      for(const row of g.rows)if((row.error&&!['Cancelled','Sent'].includes(row.status))||['Needs attention','Missed','Failed','Uncertain'].includes(row.status))add({account_id:g.account_id,recipient:row.name||row.target,title:row.status,message:row.error||'Delivery needs review. Check Telegram and the sending queue before trying again.'});
    }
    for(const a of accounts){
      if(a.error||a.health?.last_error)add({account_id:a.id,title:'Account error',message:a.error||a.health.last_error});
      if(a.blocked_until&&Date.parse(a.blocked_until)>Date.now())add({account_id:a.id,title:'Telegram waiting period',message:'Sending is paused until '+new Date(a.blocked_until).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',timeZoneName:'short'})+'.'});
    }
    for(const error of clientErrors)add(error);
    return result;
  }
  root.WMMPendingMessages={build,countdown,active,issues};
})(typeof window==='object'?window:globalThis);

let pendingLastSync=null;
function pendingPerson(row){const p=people.find(p=>p.id===row.contact_id)||people.find(p=>String(p.user_id)===String(row.target));return {name:row.name||p?.name||row.target||'Recipient',username:p?.username||''}}
function renderPendingQueue(){
  const model=WMMPendingMessages,groups=model.build(queuedSends,scheduledSends),all=groups.flatMap(g=>g.pending);
  $('#pendingTotal').textContent=all.length;$('#pendingWaiting').textContent=all.filter(r=>['Queued','Scheduled','Waiting for sign-in'].includes(r.status)).length;$('#pendingSending').textContent=all.filter(r=>r.status==='Sending').length;$('#pendingAttention').textContent=all.filter(r=>['Needs attention','Missed'].includes(r.status)).length;
  $('[data-pending-count]').textContent=all.length;
  const problems=model.issues(groups,accounts,workspaceActionErrors);
  $('#pendingIssuePanel').hidden=!problems.length;$('#pendingIssueCount').textContent=problems.length;
  $('#pendingIssues').innerHTML=problems.map(p=>`<article class="pending-issue"><b>${esc(p.title||'Request error')}${p.account_id?' · Account '+esc(p.account_id):''}${p.recipient?' · '+esc(p.recipient):''}</b><p>${esc(p.message)}</p>${p.path?`<small>${esc(p.path)}${p.status?' · HTTP '+esc(p.status):''}</small>`:''}</article>`).join('');
  const filter=$('#pendingAccount'),prior=filter.value,ids=[...new Set(groups.map(g=>String(g.account_id)))].sort(),signature=ids.join(',');
  if(filter.dataset.options!==signature){filter.innerHTML='<option value="">All sending accounts</option>'+ids.map(id=>`<option value="${esc(id)}">Account ${esc(id)}</option>`).join('');filter.value=ids.includes(prior)?prior:'';filter.dataset.options=signature}
  const search=$('#pendingSearch').value.trim().toLowerCase();
  const visible=groups.filter(g=>(!filter.value||String(g.account_id)===filter.value)&&(!search||g.rows.some(r=>{const p=pendingPerson(r);return [p.name,p.username,r.target,r.batch_id].some(v=>String(v||'').toLowerCase().includes(search))})));
  const open=new Set($$('#pendingMessageRecords details[open]').map(d=>d.dataset.pendingPreview));
  $('#pendingMessageRecords').innerHTML=visible.length?visible.map(g=>{
    const account=accounts.find(a=>String(a.id)===String(g.account_id));
    return `<article class="card pending-batch"><div class="pending-batch-head"><div><h2>${g.batch?'Message batch':'Scheduled / individual message'} · Account ${esc(g.account_id)}</h2><p>${g.total} message${g.total===1?'':'s'} · <b>${g.pending.length} pending</b> · ${g.sent} sent${g.delay_seconds?' · minimum '+g.delay_seconds/60+' minutes apart':''}</p></div><span class="conversation-badge">${esc(account?.label||'Account '+g.account_id)}</span></div>${account&&!account.authorized?'<p class="pending-account-note">Waiting for the original Telegram account to connect. No other account will be used.</p>':''}<div class="tablewrap"><table class="pending-table"><thead><tr><th>#</th><th>Recipient</th><th>Planned time · IST</th><th>Countdown</th><th>Status</th><th>Message / action</th></tr></thead><tbody>${g.rows.map((row,i)=>{
      const person=pendingPerson(row),canCancel=row.source==='backend'?row.status==='Queued':['Scheduled','Waiting for sign-in','Needs attention','Missed'].includes(row.status);
      return `<tr class="${row.status==='Sent'?'pending-complete':''}"><td>${i+1}</td><td><b>${esc(person.name)}</b><div class="hint">${esc(person.username?'@'+person.username.replace(/^@/,''):'User ID '+row.target)}</div></td><td>${row.due_at?esc(conversationTime(row.due_at)):row.status==='Sent'?'Sent':'Waiting for queue'}</td><td data-pending-clock data-due="${esc(row.due_at||'')}" data-state="${esc(row.status)}">${esc(model.countdown(row))}</td><td><span class="pending-status" data-state="${esc(row.status)}">${esc(row.status)}</span>${row.error?`<p class="hint pending-error">${esc(row.error)}</p>`:''}</td><td><details data-pending-preview="${esc(row.source+':'+row.id)}" ${open.has(row.source+':'+row.id)?'open':''}><summary>Preview message</summary><div class="messagecopy pending-message">${esc(row.message)}</div></details>${canCancel?`<button data-pending-cancel="${esc(row.id)}" data-pending-source="${row.source}">Cancel this message</button>`:''}</td></tr>`;
    }).join('')}</tbody></table></div></article>`;
  }).join(''):`<div class="card conversation-empty"><h2>${search||filter.value?'No matching batches':'No pending messages'}</h2><p>Select recipients in TG Groups admins and confirm your batch. Each queued recipient and planned send time will appear here.</p><button id="pendingGoToGroups">Open TG Groups admins</button></div>`;
  $('#pendingUpdated').textContent=pendingLastSync?'Last refreshed '+conversationTime(pendingLastSync):'Waiting for server records…';
  $('#pendingQueueLimit').hidden=queuedSends.length<250;
  $('#pendingGoToGroups')?.addEventListener('click',()=>view('groups'));
  $$('[data-pending-cancel]').forEach(b=>b.onclick=()=>action(b,async()=>{await rawApi(b.dataset.pendingSource==='schedule'?'/scheduled-sends/cancel':'/send-queue/cancel',b.dataset.pendingSource==='schedule'?{schedule_id:b.dataset.pendingCancel}:{id:b.dataset.pendingCancel});await refresh(false);toast('Pending message cancelled.')}));
}
function updatePendingCountdowns(){if(!$('#pending').classList.contains('active'))return;$$('[data-pending-clock]').forEach(n=>{n.textContent=WMMPendingMessages.countdown({due_at:n.dataset.due,status:n.dataset.state})})}
document.addEventListener('DOMContentLoaded',()=>{
  $('#pendingRefresh').onclick=e=>action(e.currentTarget,()=>refresh(false));$('#pendingAccount').onchange=renderPendingQueue;$('#pendingSearch').oninput=renderPendingQueue;
  setInterval(updatePendingCountdowns,1000);
});
