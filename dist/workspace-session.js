/* Persistent expiring dashboard sessions. Telegram credentials and workspace records stay on the server. */
(function(root){
  const name='wmm.tg-admins.standalone.session.v1';
  const pages=new Set(['directory','groups','saved','sent','replies','pipeline','templates','connections']);
  const filterIds=['savedType','role','sentScope','sentStatus','replyMessageOrder','replyAccount','leadFilter','leadType'];
  function create(storage,legacy){
    function clear(){for(const target of [storage,legacy])try{target?.removeItem(name)}catch{}}
    function read(){
      try{
        let raw;try{raw=storage.getItem(name)}catch{}
        if(!raw)try{raw=legacy?.getItem(name)}catch{}
        const value=JSON.parse(raw||'null');
        if(!value)return null;
        const url=new URL(value.gateway);
        if((url.protocol!=='https:'&&!(url.protocol==='http:'&&['localhost','127.0.0.1','[::1]'].includes(url.hostname)))||url.username||url.password||!value.token||typeof value.token!=='string'||!Number.isFinite(Date.parse(value.expiresAt))||Date.parse(value.expiresAt)<=Date.now()){clear();return null}
        return {gateway:value.gateway,token:value.token,expiresAt:value.expiresAt,page:pages.has(value.page)?value.page:(['replies','health','activity'].includes(value.page)?'saved':'directory'),filters:Object.fromEntries(filterIds.filter(id=>typeof value.filters?.[id]==='string'&&value.filters[id].length<64).map(id=>[id,value.filters[id]]))};
      }catch{clear();return null}
    }
    function save(session){let stored=false;for(const target of [storage,legacy])try{if(target){target.setItem(name,JSON.stringify(session));stored=true}}catch{}return stored&&!!read()}
    function page(value){const session=read();if(session&&pages.has(value))save({...session,page:value})}
    function filter(id,value){const session=read();if(session&&filterIds.includes(id))save({...session,filters:{...session.filters,[id]:value}})}
    return {read,save,page,filter,clear};
  }
  const api={create};if(typeof module==='object'&&module.exports)module.exports=api;else root.WMMWorkspaceSession=api;
})(typeof window==='object'?window:globalThis);
