// Reviewed admin selection; messages are queued only by the confirmation button.
let tgAdminSelected=new Set(),tgAdminBatchPlan=null;
function closeTgAdminComposer(){document.getElementById('tgAdminBatchDialog').hidden=true}
function tgSavedOptionPool(){
 const options=savedTemplateVariants.template||[],pool=[...new Set(options.map(t=>t.trim()).filter(Boolean))],used=templateRotationUsed.template||[];
 let available=pool.filter(t=>!used.includes(t));if(!available.length)available=pool.slice();
 if((!used.length||pool.every(t=>used.includes(t)))&&available.length>1)available=available.filter(t=>t!==templateRotationLast.template);
 return {options,pool,available};
}
function renderTgSavedOptions(preserve=false){
 const select=document.getElementById('tgBatchFormat'),previous=select.value,{options,available}=tgSavedOptionPool();
 select.innerHTML='<option value="random">Random saved options · no repeats</option>'+options.map((t,i)=>t.trim()?`<option value="option:${i}" ${available.includes(t.trim())?'':'disabled'}>Option ${i+1}${tgAdminRecipients().length>1?' first · then shuffled':''}${available.includes(t.trim())?'':' · already used'}</option>`:'').join('');
 if(preserve&&previous.startsWith('option:')&&available.includes(options[Number(previous.split(':')[1])]?.trim()))select.value=previous;
 document.getElementById('tgBatchOptionHint').textContent='Choose a saved option or use random. For a batch, a chosen option goes first; the rest follow the shuffled cycle. Every option is used before repeating. Username and token are filled automatically.';
}
function tgAdminSource(){return newGroupAdminSnapshots()}
function tgAdminContact(admin,group){const list=people.filter(p=>(p.kind||'dm')==='dm'&&!p.is_bot&&String(p.user_id)===String(admin.user_id));return list.find(p=>p.group_id===group.group_id)||list[0]}
function tgAdminState(contact){
 if(!contact)return 'Load this real admin first';
 const target=String(contact.user_id);
 const pending=queuedSends.find(q=>q.kind==='dm'&&String(q.target)===target&&['Queued','Sending'].includes(q.status));if(pending)return pending.status;
 const sent=deliveries.find(d=>d.kind==='dm'&&String(d.target)===target&&['Sent','Sending','Uncertain'].includes(d.status));return sent?(sent.status==='Sent'?'Message sent':sent.status==='Uncertain'?'Check uncertain delivery':'Sending'):'';
}
function adminBatchCheckbox(admin,group,demo){
 const contact=demo?null:tgAdminContact(admin,group),reason=demo?'Demo preview only':tgAdminState(contact),uid=String(admin.user_id||'');
 return `<label class="tg-admin-select"><input type="checkbox" aria-label="Select ${esc(admin.name)}" ${demo||reason?'disabled':''} ${!demo&&tgAdminSelected.has(uid)?'checked':''} ${demo?'':`data-tg-admin-select="${esc(uid)}"`}><b>${esc(admin.name)}</b></label>${reason?`<small class="hint tg-admin-send-state">${esc(reason)}</small>`:''}`;
}
function tgAdminRecipients(){const byUser=new Map();for(const g of tgAdminSource())for(const a of g.admins){const p=tgAdminContact(a,g);if(p&&!tgAdminState(p))byUser.set(String(a.user_id),p)}return [...tgAdminSelected].map(id=>byUser.get(id)).filter(Boolean)}
function tgBatchGap(){const a=accounts.find(a=>a.id===Number(document.getElementById('tgBulkSender').value));return Math.max(Number(document.getElementById('tgBulkDelay').value)||120,Number(a?.pacing?.delay_seconds)||120)}
function renderAdminBatchBar(){
 const bar=document.getElementById('tgAdminBulkBar');if(!bar)return;
 const recipients=tgAdminRecipients();tgAdminSelected=new Set(recipients.map(p=>String(p.user_id)));bar.hidden=!recipients.length;
 document.getElementById('tgBulkCount').textContent=recipients.length+' selected';
 const select=document.getElementById('tgBulkSender'),before=select.value;select.innerHTML=visibleAccounts().map(a=>`<option value="${a.id}">Account ${a.id} — ${esc(a.label)}${a.authorized?'':' (not connected)'}</option>`).join('');if(visibleAccounts().some(a=>String(a.id)===before))select.value=before;
 const a=accounts.find(a=>a.id===Number(select.value));const globalGap=Number(a?.pacing?.delay_seconds)||120;
 document.getElementById('tgBulkDelay').querySelectorAll('option').forEach(o=>o.disabled=Number(o.value)<globalGap);
 if(Number(document.getElementById('tgBulkDelay').value)<globalGap)document.getElementById('tgBulkDelay').value=String(globalGap);
 const paused=a?.blocked_until&&new Date(a.blocked_until)>new Date();
 document.getElementById('tgBulkHint').textContent=!live?'Connect your gateway first.':!serverFeatures.admin_bulk_sends?'Deploy the latest gateway on Render to enable reviewed admin batches.':!a?.authorized?'Connect the selected account in Settings first.':paused?'This account is paused until '+new Date(a.blocked_until).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',hour12:true,timeZoneName:'short'})+'.':`Messages send one at a time, at least ${tgBatchGap()/60} minutes apart. Review before queueing. Daily limits and Telegram pauses stay in place.`;
 document.getElementById('tgBulkOpen').disabled=!live||!serverFeatures.admin_bulk_sends||!a?.authorized||!!paused;
 if(!recipients.length)closeTgAdminComposer();
 if(!document.getElementById('tgAdminBatchDialog').hidden){document.getElementById('tgBatchSummary').textContent=recipients.length+(recipients.length===1?' admin':' admins')+' · Account '+Number(select.value)+' · minimum '+tgBatchGap()/60+' minutes between messages';document.getElementById('tgBatchConfirm').textContent='Send '+recipients.length+(recipients.length===1?' message':' messages')}
 if(!live){tgAdminSelected.clear();tgAdminBatchPlan=null;closeTgAdminComposer()}
}
function tgBatchReady(){
 if(!live||!serverFeatures.admin_bulk_sends)throw Error('Connect the latest gateway on Render to send admin batches.');
 const id=Number(document.getElementById('tgBulkSender').value),a=accounts.find(a=>a.id===id);
 if(!a?.authorized)throw Error('Connect the selected account first.');
 if(a.blocked_until&&new Date(a.blocked_until)>new Date())throw Error('This account is paused until '+new Date(a.blocked_until).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',hour12:true,timeZoneName:'short'})+'.');
 const recipients=tgAdminRecipients();if(!recipients.length||recipients.length>15)throw Error('Select between 1 and 15 real admins.');return {id,recipients};
}
function invalidateTgBatchPreview(){tgAdminBatchPlan=null;document.getElementById('tgBatchPreviews').hidden=true;document.getElementById('tgBatchConfirm').disabled=true;document.getElementById('tgBatchState').textContent='Review the messages before queueing.'}
async function openTgAdminBatch(){
 await refreshTemplateCatalog();
 const {id,recipients}=tgBatchReady();invalidateTgBatchPreview();
 document.getElementById('tgBatchSummary').textContent=recipients.length+(recipients.length===1?' admin':' admins')+' · Account '+id+' · minimum '+tgBatchGap()/60+' minutes between messages';
 document.getElementById('tgBatchToken').value=document.getElementById('composeToken').value;
 document.getElementById('tgBatchExchange').innerHTML=exchangeOptions();
 renderTgSavedOptions();
 document.getElementById('tgBatchMessage').value=savedTemplate||WMMMessageModel.introduction;
 document.getElementById('tgBatchMessage').hidden=document.getElementById('tgBatchFormat').value==='random';
 document.getElementById('tgBatchConfirm').textContent='Send '+recipients.length+(recipients.length===1?' message':' messages');document.getElementById('tgAdminBatchDialog').hidden=false;document.getElementById('tgAdminBatchDialog').scrollIntoView?.({behavior:'smooth',block:'nearest'});
}
function buildTgAdminBatchPreview(){
 const {id,recipients}=tgBatchReady(),mode=document.getElementById('tgBatchFormat').value,random=mode!=='custom',text=document.getElementById('tgBatchMessage').value.trim(),symbol=WMMMessageModel.normalizeToken(document.getElementById('tgBatchToken').value),exchange=document.getElementById('tgBatchExchange').value;
 if(!symbol||!exchange)throw Error('Enter the token and choose the exchange before previewing.');
 const forced=mode.startsWith('option:')?savedTemplateVariants.template?.[Number(mode.split(':')[1])]?.trim():null;
 if(mode.startsWith('option:')&&(!forced||!tgSavedOptionPool().available.includes(forced)))throw Error('This option is already used or has changed. Choose an available saved option.');
 const signature=JSON.stringify([id,recipients.map(p=>p.id),mode,text,symbol,exchange,tgBatchGap(),savedTemplateVariants.template,templateRotationUsed.template,templateRotationLast.template]);
 if(!tgAdminBatchPlan||tgAdminBatchPlan.signature!==signature){
  const used=JSON.parse(JSON.stringify(templateRotationUsed)),last={...templateRotationLast};
  const messages=recipients.map((p,index)=>{let message=text,choices={};if(random){const option=forced&&index===0?{text:forced}:pickSavedTemplate('template',used,last);message=option.text;choices={template:message};const pool=[...new Set((savedTemplateVariants.template||[]).map(t=>t.trim()).filter(Boolean))];if(pool.every(t=>(used.template||[]).includes(t)))used.template=[];used.template=[...(used.template||[]),message];last.template=message}if(!message)throw Error('Save an initial message option in Message templates first.');validateMessageToken(message,symbol);return {id:p.id,message,template_choices:choices}});
  tgAdminBatchPlan={signature,body:{request_id:uniqueRequest(),account_id:id,messages,token_symbol:symbol,exchange,delay_seconds:Number(document.getElementById('tgBulkDelay').value)}};
 }
 const root=document.getElementById('tgBatchPreviews');root.innerHTML=tgAdminBatchPlan.body.messages.map((item,index)=>{const p=recipients[index];return `<details open><summary>${esc(p.name)}${p.username?' · @'+esc(p.username):''}</summary><div class="messagecopy">${esc(WMMMessageModel.personalize(item.message,p,symbol,exchange))}</div></details>`}).join('');root.hidden=false;
 document.getElementById('tgBatchConfirm').disabled=false;document.getElementById('tgBatchState').textContent='Review all '+recipients.length+' messages. Queueing saves them on your server; you can then close this tab.';
}
function initializeAdminBatch(){
 document.getElementById('tgGroupRecords').onchange=event=>{const input=event.target;if(!input.matches('[data-tg-admin-select]'))return;const uid=input.dataset.tgAdminSelect;if(input.checked){if(tgAdminSelected.size>=15){input.checked=false;toast('Select up to 15 admins per batch.');return}tgAdminSelected.add(uid)}else tgAdminSelected.delete(uid);invalidateTgBatchPreview();renderGroupAdmins()};
 document.getElementById('tgBulkClear').onclick=()=>{tgAdminSelected.clear();invalidateTgBatchPreview();renderGroupAdmins()};
 document.getElementById('tgBulkSender').onchange=()=>{invalidateTgBatchPreview();renderAdminBatchBar()};document.getElementById('tgBulkDelay').onchange=()=>{invalidateTgBatchPreview();renderAdminBatchBar()};
 document.getElementById('tgBulkOpen').onclick=()=>action(document.getElementById('tgBulkOpen'),()=>openTgAdminBatch());
 document.getElementById('tgBatchCancel').onclick=()=>{if(!busy)closeTgAdminComposer()};
 document.getElementById('tgBatchFormat').onchange=invalidateTgBatchPreview;
 for(const id of ['tgBatchToken','tgBatchExchange','tgBatchMessage'])document.getElementById(id).oninput=invalidateTgBatchPreview;
 document.getElementById('tgBatchReview').onclick=()=>action(document.getElementById('tgBatchReview'),async()=>{await refreshTemplateCatalog();renderTgSavedOptions(true);buildTgAdminBatchPreview()});
 document.getElementById('tgBatchConfirm').onclick=()=>action(document.getElementById('tgBatchConfirm'),async()=>{
  const {id}=tgBatchReady();if(!tgAdminBatchPlan||tgAdminBatchPlan.body.account_id!==id)throw Error('Review the messages first.');
  document.getElementById('tgBatchState').textContent='Saving your reviewed batch…';
  try{const result=await rawApi('/groups/admins/send-batch',tgAdminBatchPlan.body);tgAdminSelected.clear();tgAdminBatchPlan=null;closeTgAdminComposer();try{await refresh(false)}catch{}renderGroupAdmins();view('pending');toast(result.count+' messages queued · Account '+result.account_id+' · at least '+result.delay_seconds/60+' minutes apart. You can close this tab.');}
  catch(error){if(isTemplateConflict(error)){await refreshTemplateCatalog();renderTgSavedOptions(true);invalidateTgBatchPreview();buildTgAdminBatchPreview();document.getElementById('tgBatchState').textContent='Saved options updated. Review the new previews, then queue again.';toast('Saved options updated. Review the new previews, then queue again.');return}document.getElementById('tgBatchState').textContent=error.name==='AbortError'?'Connection timed out. Check the queue in Settings before changing this preview. Retrying this unchanged batch uses the same request ID.':error.message;try{await refresh(false)}catch{}throw error}
 });
}
