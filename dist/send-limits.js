/* Daily limits and restriction protection; no permission form or permission gate. */
let outreachState=null;
window.renderOutreachSafety=function(data){
 outreachState=data;
 const s=data.outreach_safety;if(!s)return;
 const el=document.getElementById('sendLimitSummary');
 if(el)el.textContent='Daily cap: 10 unique recipients/account, 30/team · IST. Reserved today: '+s.team_reserved+'/30. Duplicate and restriction checks remain active.';
 const button=document.getElementById('applyReviewedSending');
 if(button)button.disabled=!data.settings?.auto_yes_enabled&&!data.settings?.auto_followup_enabled;
};
document.getElementById('applyReviewedSending').onclick=()=>action(document.getElementById('applyReviewedSending'),async()=>{await rawApi('/outreach-reviewed-mode',{});await refresh(false);toast('Reviewed sending applied. Automatic promotional sequences paused.');});
for(const id of ['globalAutoReplies','globalAutoFollowup']){const el=document.getElementById(id);if(el){el.disabled=true;el.title='Reviewed sending requires unattended promotional sequences to stay disabled.'}}
