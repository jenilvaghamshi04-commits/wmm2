let telegramQrTimer=null,telegramQrSlot=null,telegramQrGeneration=0;
function clearTelegramQr(){telegramQrGeneration++;clearTimeout(telegramQrTimer);telegramQrTimer=null;telegramQrSlot=null;document.getElementById('telegramQrPanel').hidden=true;document.getElementById('telegramQrImage').removeAttribute('src')}
async function showTelegramQrState(result,id){
  const status=document.getElementById('telegramQrStatus'),image=document.getElementById('telegramQrImage');
  if(result.status==='authorized'){clearTelegramQr();await refresh(false);toast('Account '+id+' connected with Telegram.');return}
  if(result.status==='password'){clearTelegramQr();await refresh(false);toast('QR accepted. Enter your Telegram two-step password below.');return}
  if(result.status!=='waiting'){image.removeAttribute('src');image.hidden=true;status.textContent=result.error||'QR code expired. Generate a new QR code.';return}
  if(result.image){image.src=result.image;image.hidden=false}
  status.textContent='Waiting for approval on your phone · Account '+id+'. Expires '+new Date(result.expires_at).toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour12:true,timeZoneName:'short'})+'.';
  const cycle=telegramQrGeneration;
  telegramQrTimer=setTimeout(async()=>{
    if(cycle!==telegramQrGeneration||telegramQrSlot!==id||slot()!==id||!live)return;
    try{const next=await api('/login/qr/status',{account_id:id});if(cycle===telegramQrGeneration&&telegramQrSlot===id)await showTelegramQrState(next,id)}
    catch(error){if(cycle===telegramQrGeneration&&telegramQrSlot===id){image.removeAttribute('src');image.hidden=true;status.textContent=error.message+' Click Connect with QR code to resume.'}}
  },1500);
}
document.addEventListener('DOMContentLoaded',()=>{
  document.getElementById('startQrLogin').onclick=()=>action(document.getElementById('startQrLogin'),async()=>{
    if(!live)throw Error('Connect your gateway first.');
    if(!serverFeatures.qr_login)throw Error('QR login needs the latest backend. In Render, select Manual Deploy → Deploy latest commit, then refresh this page.');
    clearTelegramQr();const id=slot(),cycle=telegramQrGeneration,result=await api('/login/qr',{account_id:id});if(cycle!==telegramQrGeneration||slot()!==id)return;telegramQrSlot=id;
    document.getElementById('telegramQrPanel').hidden=false;await showTelegramQrState(result,id);
  });
  document.getElementById('cancelQrLogin').onclick=()=>action(document.getElementById('cancelQrLogin'),async()=>{const id=telegramQrSlot;if(id)await api('/login/qr/cancel',{account_id:id});clearTelegramQr();await refresh(false)});
  document.getElementById('loginAccount').addEventListener('change',clearTelegramQr);
  document.getElementById('dashboardLogout').addEventListener('click',clearTelegramQr);
});
