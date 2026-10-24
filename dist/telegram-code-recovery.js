/* Code delivery is chosen by Telegram. Resend only when Telegram offers a next method. */
function renderTelegramCodeRecovery(){
  const account=accounts.find(a=>a.id===slot()),panel=document.getElementById('telegramCodeRecovery');
  if(!panel)return;
  const pending=account&&!account.authorized&&account.login_step==='code';
  panel.hidden=!pending;if(!pending)return;
  const button=document.getElementById('resendLoginCode'),hint=document.getElementById('telegramCodeDelivery');
  const wait=Math.max(0,Math.ceil((Date.parse(account.code_resend_at||'')-Date.now())/1000))||0;
  const available=!!(serverFeatures.login_code_recovery&&account.code_resend_available);
  button.disabled=!available||wait>0;
  button.textContent=available?(wait?'Try next method in '+wait+'s':'Code didn’t arrive · try '+(account.code_next_delivery||'next method')):'No alternate code method available';
  const destination=account.code_delivery==='Telegram app'?'Open the verified Telegram service chat on a device already signed in.':account.code_delivery==='SMS'?'Check SMS on the phone number you entered.':account.code_delivery==='email'?'Check the email Telegram has associated with this login.':'Check the delivery method Telegram provided, or connect with QR.';
  hint.textContent=(account.code_delivery?'Delivery: '+account.code_delivery+'. ':'')+destination+(!available?' Telegram has not offered an alternate delivery method. Use QR login, or wait for this pending code to expire.':'');
}
document.addEventListener('DOMContentLoaded',()=>{
  const original=renderLogin;renderLogin=function(){original();renderTelegramCodeRecovery()};renderTelegramCodeRecovery();
  document.getElementById('resendLoginCode').onclick=()=>action(document.getElementById('resendLoginCode'),async()=>{
    const id=slot();try{const result=await api('/login/resend',{account_id:id});if(result.authorized){await refresh(false);toast('Account '+id+' is already connected.');return}if(slot()===id){document.getElementById('loginCode').value='';document.getElementById('password').value=''}await refresh(false);toast('Code requested via '+(result.code_delivery||'Telegram’s next method')+'. Check that destination.')}
    catch(error){try{await refresh(false)}catch{}throw error}
  });
  setInterval(()=>{if(live)renderTelegramCodeRecovery()},1000);
});
