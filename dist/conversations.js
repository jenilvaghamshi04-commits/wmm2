/* Conversation views use existing records and the existing reviewed send queue. */
(function(root){
  function build(history,leads=[],queue=[],contacts=[]){
    const model=root.WMMMessageModel,byLead=new Map(leads.map(l=>[l.key,l])),groups=new Map();
    for(const d of history){if((d.kind||'dm')!=='dm')continue;const k='dm:'+String(d.target);if(!groups.has(k))groups.set(k,[]);groups.get(k).push(d)}
    return [...groups].map(([key,rows])=>{
      const summary=model.conversation({kind:'dm',user_id:key.slice(3)},rows);
      if(!summary.sent.length)return null;
      const original=summary.firstMessage?.status==='Sent'?summary.firstMessage:summary.sent.at(-1),lead=byLead.get(key)||{},replied=model.hasReplied(lead);
      const pending=queue.filter(q=>(q.kind||'dm')==='dm'&&String(q.target)===String(original.target)&&['Queued','Sending','Needs attention'].includes(q.status));
      const contact=contacts.find(c=>c.id===original.id)||{};
      const activity=[summary.latest?.at,lead.last_activity_at,lead.latest_reply?.at].filter(Boolean).sort((a,b)=>Date.parse(b)-Date.parse(a))[0];
      return {key,summary,original,lead,replied,pending,activity,contact,name:contact.name||lead.name||original.recipient_name||original.target,username:contact.username||lead.username||original.username||'',canFollowup:!replied&&!['Replied','Meeting','Proposal','Client'].includes(lead.stage)&&summary.canFollowup&&!pending.length,canReply:replied&&!summary.pending&&!pending.length};
    }).filter(Boolean).sort((a,b)=>Date.parse(b.activity)-Date.parse(a.activity));
  }
  function payload(row,mode,text,token,requestId,choices={}){
    if(!row||!['follow-up','reply'].includes(mode))throw Error('Choose a saved conversation.');
    if(mode==='follow-up'&&!row.canFollowup)throw Error(row.replied?'A reply arrived. Open this conversation in Replies.':'A follow-up is unavailable while this conversation needs review or has a queued message.');
    if(mode==='reply'&&!row.canReply)throw Error('Review the delivery or queued message before replying.');
    if(!text.trim())throw Error('Write a message before previewing.');
    return {request_id:requestId,action:mode,payload:{delivery_id:row.original.delivery_id,request_id:requestId,message:text.trim(),token_symbol:token,template_choices:choices}};
  }
  root.WMMInboxModel={build,payload};
})(typeof window==='object'?window:globalThis);

let conversationDraft=null,conversationRows=[];
const conversationTime=value=>value?new Date(value).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',dateStyle:'medium',timeStyle:'short'})+' IST':'Not checked';
function conversationHistory(row){
  const events=[...row.summary.rows.map(d=>({at:d.at,out:true,text:d.message||'Message text unavailable',status:WMMMessageModel.status({latest:d}),sender:d.sender_label||'Account '+d.account_id})),...(row.lead.replies||[]).map(r=>({at:r.at,out:false,text:r.body,status:'Received',sender:row.name}))];
  return events.sort((a,b)=>Date.parse(a.at)-Date.parse(b.at)).map(e=>`<div class="conversation-bubble ${e.out?'outgoing':'incoming'}"><div class="conversation-bubble-meta">${esc(e.sender)} · ${esc(e.status)} · ${esc(conversationTime(e.at))}</div><div class="messagecopy">${esc(e.text)}</div></div>`).join('');
}
function conversationCard(row){
  const d=row.original,states=WMMMessageModel.deliveryStates(row.summary),last=row.summary.lastSent;
  const info=row.replied?`<div class="conversation-incoming"><b>Latest reply · ${esc(conversationTime(row.lead.latest_reply?.at))}</b><p class="messagecopy">${esc(row.lead.latest_reply?.body||'Reply received')}</p></div>`:`<p class="hint">${row.lead.sync_error?esc(row.lead.sync_error):row.lead.sync_complete?'Reply history checked · '+esc(conversationTime(row.lead.sync_checked_at)):'Reply check pending · replies are checked in the background'}</p>`;
  return `<article class="card conversation-card"><div class="conversation-card-top"><div><h2>${esc(row.name)}</h2><p>${esc(row.username?'@'+row.username.replace(/^@/,''):'User ID '+d.target)}</p></div><span class="conversation-badge ${row.replied?'has-reply':''}">${row.replied?'Replied':'Awaiting reply'}</span></div><div class="conversation-meta"><span>${esc(d.sender_label||'Account '+d.account_id)}</span><span>${esc(d.token_symbol?'$'+d.token_symbol:'No token saved')}</span><span>${esc(WMMMessageModel.exchanges[d.exchange]||d.exchange||'No exchange saved')}</span>${row.lead.group?`<span>${esc(row.lead.group)}</span>`:''}</div><div class="conversation-delivery"><span>Message: <b>${esc(states.message.label)}</b></span><span>Follow-up: <b>${esc(states.followup.label)}</b>${row.summary.followups?' · '+row.summary.followups:''}</span></div><p class="hint">First sent ${esc(conversationTime(d.at))} · Last sent ${esc(conversationTime(last.at))}</p><p class="conversation-last messagecopy">${esc(last.message||'Message text unavailable')}</p>${info}${row.pending.length?`<p class="conversation-warning">${esc(row.pending[0].status)} · ${esc(row.pending[0].error||'A message is already queued for this person.')}</p>`:''}${row.summary.pending?'<p class="conversation-warning">An earlier delivery needs review in Telegram before another send.</p>':''}<details><summary>Conversation history · ${row.summary.rows.length+(row.lead.replies||[]).length} messages</summary><div class="conversation-history">${conversationHistory(row)}</div></details><div class="conversation-actions"><button class="primary" data-conversation-open="${esc(row.key)}" ${!(row.replied?row.canReply:row.canFollowup)?'disabled':''}>${row.replied?'Reply':'Send follow-up'}</button><button data-conversation-check="${esc(row.key)}">Check replies</button>${row.replied&&row.lead.needs_attention?`<button data-conversation-read="${esc(row.key)}">Mark read</button>`:''}</div></article>`;
}
function renderConversations(){
  conversationRows=WMMInboxModel.build(deliveries,leads,queuedSends,people);
  for(const page of ['sent','replies']){
    const rows=conversationRows.filter(r=>r.replied===(page==='replies'));
    const search=$('#'+page+'ConversationSearch').value.trim().toLowerCase(),account=$('#'+page+'ConversationAccount').value;
    const select=$('#'+page+'ConversationAccount'),ids=[...new Set(rows.map(r=>String(r.original.account_id)))].sort();
    select.innerHTML='<option value="">All sending accounts</option>'+ids.map(id=>`<option value="${esc(id)}">Account ${esc(id)}</option>`).join('');select.value=ids.includes(account)?account:'';
    const filtered=rows.filter(r=>(!select.value||String(r.original.account_id)===select.value)&&(!search||[r.name,r.username,r.original.target,r.original.sender_label,r.lead.group,r.original.token_symbol,r.original.exchange].some(v=>String(v||'').toLowerCase().includes(search))));
    $('#'+page+'ConversationCount').textContent=rows.length+' '+(page==='sent'?'awaiting reply':'replied');
    $('#'+page+'ConversationRecords').innerHTML=filtered.length?filtered.map(conversationCard).join(''):`<div class="card conversation-empty"><h2>${search||select.value?'No matching conversations':page==='sent'?'No messages awaiting reply':'No replies yet'}</h2><p>${page==='sent'?'People appear here after a confirmed message. Replied contacts move to Replies.':'Incoming replies from people you contacted appear here automatically.'}</p></div>`;
    const badge=$('[data-conversation-count="'+page+'"]');if(badge)badge.textContent=rows.length;
  }
  $$('[data-conversation-open]').forEach(b=>b.onclick=()=>action(b,()=>openConversationComposer(b.dataset.conversationOpen)));
  $$('[data-conversation-check]').forEach(b=>b.onclick=()=>action(b,()=>checkConversationReplies(b.dataset.conversationCheck)));
  $$('[data-conversation-read]').forEach(b=>b.onclick=()=>action(b,async()=>{await rawApi('/leads/update',{key:b.dataset.conversationRead,acknowledge:true});await refresh(false)}));
  if(conversationDraft){const row=conversationRows.find(r=>r.key===conversationDraft.key);if(conversationDraft.mode==='follow-up'&&row?.replied){$('#conversationComposerStatus').textContent='A reply arrived. Follow-up stopped. Close this preview and open Replies.';$('#conversationQueueMessage').disabled=true}}
}
async function checkConversationReplies(key){
  const result=await rawApi('/replies/sync',key?{key}:{});await refresh(false);
  const failures=(result.results||[]).filter(r=>!r.ok);toast(failures.length?failures[0].error:result.checked?'Reply checks refreshed.':'Reply checks are up to date or waiting for Telegram’s retry interval.');
}
function conversationOptions(mode){
  const choices=[{value:'custom',label:'Write a custom '+(mode==='reply'?'reply':'follow-up')}];
  if(mode==='follow-up')choices.unshift({value:'random',label:'Next saved follow-up · shuffled cycle'});
  for(const [key,label] of mode==='reply'?[['yes_pitch_template','Yes reply · pitch'],['yes_demo_template','Yes reply · call invitation']]:[['followup_template','Follow-up']]){
    const available=mode==='follow-up'?new Set((()=>{const pool=[...new Set((savedTemplateVariants[key]||[]).map(t=>t.trim()).filter(Boolean))],seen=templateRotationUsed[key]||[];let remaining=pool.filter(t=>!seen.includes(t));const reset=!remaining.length;if(reset)remaining=pool;if((!seen.length||reset)&&remaining.length>1)remaining=remaining.filter(t=>t!==templateRotationLast[key]);return remaining})()):null;
    (savedTemplateVariants[key]||[]).forEach((text,index)=>{if(text.trim())choices.push({value:key+':'+index,label:label+' · option '+(index+1),disabled:!!available&&!available.has(text.trim())})});
  }
  return choices;
}
function invalidateConversationPreview(){
  if(!conversationDraft||conversationDraft.uncertain)return;
  conversationDraft.plan=null;conversationDraft.requestId=uniqueRequest();$('#conversationMessagePreview').hidden=true;$('#conversationQueueMessage').disabled=true;$('#conversationComposerStatus').textContent='Preview your exact message before queueing.';
}
function selectConversationTemplate(){
  const d=conversationDraft;if(!d||d.uncertain)return;
  const value=$('#conversationMessageOption').value;d.choice=null;
  if(value==='random'){const picked=pickSavedTemplate('followup_template');$('#conversationMessageText').value=picked.text;d.choice={followup_template:picked.text}}
  else if(value!=='custom'){const [key,index]=value.split(':'),text=savedTemplateVariants[key]?.[Number(index)]||'';$('#conversationMessageText').value=text;if(d.mode==='follow-up')d.choice={[key]:text}}
  invalidateConversationPreview();
}
async function openConversationComposer(key){
  if(conversationDraft?.uncertain){$('#conversationComposer').showModal();throw Error('Review or safely retry the previous queue request before opening another message.')}
  await refresh(false);const row=conversationRows.find(r=>r.key===key);if(!row)throw Error('Conversation is no longer available.');
  const mode=row.replied?'reply':'follow-up';if(!(row.replied?row.canReply:row.canFollowup))throw Error('This conversation has a pending delivery or needs review.');
  if(mode==='follow-up')await refreshTemplateCatalog();
  conversationDraft={key,mode,choice:null,plan:null,requestId:uniqueRequest(),uncertain:false};
  $('#conversationComposerTitle').textContent=(mode==='reply'?'Reply to ':'Follow up with ')+row.name;
  $('#conversationComposerSender').textContent='Sending from '+(row.original.sender_label||'Account '+row.original.account_id)+' · '+(WMMMessageModel.exchanges[row.original.exchange]||row.original.exchange||'No exchange saved')+' · Original sender is locked';
  $('#conversationComposerHistory').innerHTML=conversationHistory(row);
  $('#conversationMessageToken').value=row.original.token_symbol||'';$('#conversationMessageText').value='';
  $('#conversationMessageOption').innerHTML=conversationOptions(mode).map(o=>`<option value="${esc(o.value)}" ${o.disabled?'disabled':''}>${esc(o.label)}</option>`).join('');
  setConversationInputsDisabled(false);$('#conversationQueueMessage').textContent='Queue '+(mode==='reply'?'reply':'follow-up');
  try{selectConversationTemplate()}catch(error){$('#conversationMessageOption').value='custom';invalidateConversationPreview();toast(error.message)}
  $('#conversationComposer').showModal();
}
function setConversationInputsDisabled(disabled){for(const id of ['conversationMessageOption','conversationMessageToken','conversationMessageText','conversationPreviewMessage'])$('#'+id).disabled=disabled}
function previewConversationMessage(){
  const d=conversationDraft,row=conversationRows.find(r=>r.key===d?.key);if(!d||d.uncertain)return;
  const text=$('#conversationMessageText').value.trim(),symbol=validateMessageToken(text,$('#conversationMessageToken').value);
  if(text.includes('{{exchange}}')&&!row.original.exchange)throw Error('This conversation has no saved exchange. Enter its exchange name directly in the message.');
  const choices=d.choice&&Object.values(d.choice)[0]===text?d.choice:{};
  d.plan=WMMInboxModel.payload(row,d.mode,text,symbol,d.requestId,choices);
  $('#conversationMessagePreview').textContent=WMMMessageModel.personalize(text,{...row.contact,name:row.name,username:row.username,group:row.contact.group||row.lead.group},symbol,row.original.exchange);$('#conversationMessagePreview').hidden=false;
  $('#conversationQueueMessage').disabled=false;$('#conversationComposerStatus').textContent='Only this reviewed message will be queued, from the original Telegram account.';
}
async function queueConversationMessage(){
  const d=conversationDraft;if(!d?.plan)throw Error('Preview your message first.');
  if(!d.uncertain){await refresh(false);const row=conversationRows.find(r=>r.key===d.key);WMMInboxModel.payload(row,d.mode,d.plan.payload.message,d.plan.payload.token_symbol,d.requestId,d.plan.payload.template_choices)}
  setConversationInputsDisabled(true);$('#conversationQueueMessage').disabled=true;
  let result;
  try{
    result=await rawApi('/send-queue',d.plan);
    if(!['Queued','Sending','Sent'].includes(result.status))throw Object.assign(Error('Queue status: '+result.status+'. Review Settings → Sending queue before another attempt.'),{status:409});
  }catch(error){
    if(!error.status||error.status>=500){d.uncertain=true;$('#conversationComposerStatus').textContent='The queue response was interrupted. Retry this same request safely; do not create another message.';$('#conversationQueueMessage').textContent='Retry same queue request';$('#conversationQueueMessage').disabled=false}
    else{d.uncertain=false;setConversationInputsDisabled(false);invalidateConversationPreview();$('#conversationComposerStatus').textContent=error.message}
    throw error;
  }
  if(d.plan.payload.template_choices)recordTemplateChoices(d.plan.payload.template_choices);
  $('#conversationComposer').close();conversationDraft=null;
  try{await refresh(false)}catch{}
  toast(result.status==='Sent'?'Message sent.':'Message queued from the original account. Follow its status in Sending queue.');
}
document.addEventListener('DOMContentLoaded',()=>{
  for(const page of ['sent','replies']){for(const suffix of ['Search','Account'])$('#'+page+'Conversation'+suffix).addEventListener(suffix==='Search'?'input':'change',renderConversations);$('#'+page+'ConversationRefresh').onclick=e=>action(e.currentTarget,()=>checkConversationReplies())}
  $('#conversationMessageOption').onchange=()=>{try{selectConversationTemplate()}catch(error){toast(error.message)}};
  for(const id of ['conversationMessageText','conversationMessageToken'])$('#'+id).oninput=invalidateConversationPreview;
  $('#conversationPreviewMessage').onclick=e=>action(e.currentTarget,previewConversationMessage);
  $('#conversationQueueMessage').onclick=async e=>{const button=e.currentTarget;await action(button,queueConversationMessage);const row=conversationRows.find(r=>r.key===conversationDraft?.key);button.disabled=!conversationDraft?.plan||(!conversationDraft.uncertain&&!(conversationDraft.mode==='reply'?row?.canReply:row?.canFollowup))};
  $('#conversationCloseComposer').onclick=()=>$('#conversationComposer').close();
});
