(function(root){
  const introduction="Hey @username! Hope you're doing well.\n\nI'm Mark from Wallstreet Market Maker (WMM).\n\nI recently came across $TOKEN and thought it would be worth connecting.\n\nWe work with crypto projects to improve trading liquidity, maintain healthier order books, and manage liquidity across exchanges.\n\nI believe there could be a good opportunity for us to work together.\n\nAre you the right person to discuss this with?";
  const followup="Hey, just following up on my previous message. Is improving liquidity and order-book depth something your team is currently exploring?\nHappy to share how WMM could help. If someone else handles this, could you point me their way?";
  const exchanges={"bingx": "BingX", "bitget": "Bitget", "bitunix": "Bitunix", "blofin": "BloFin", "gateio": "Gate.io", "htx": "HTX", "lbank": "LBank", "lovelylegends": "Lovely Legends", "mexc": "MEXC", "okx": "OKX", "poloniex": "Poloniex", "toobit": "Toobit", "weex": "WEEX", "xt": "XT.com"};
  const yesPitch="Nice to meet you @username,\nThis is mark from WMM\n\nI saw the @TOKEN chart on {{exchange}}, candlesticks look broken, we provide a professional trading team for market making, {{exchange}} trading fees are quite high but we make it good in the same daily fee spending budget\n\nWe make the chart most compatible with trading views and other trading signals tools to activate more real traders.";
  const yesDemo="We can give you a free demo also\nIf you have time we can jump on call and discuss further";
  function type(contact){return contact.kind||'dm'}
  function timestamp(value){const n=Date.parse(value);return Number.isFinite(n)?n:0}
  function latestFirst(rows,getTime=row=>row.at){return rows.slice().sort((a,b)=>timestamp(getTime(b))-timestamp(getTime(a)))}
  function latestContacts(contacts,history,leads=[]){
    const leadTimes=new Map(leads.map(l=>[l.key,timestamp(l.last_activity_at)]));
    const latest=new Map();
    for(const d of history){const key=(d.kind||'dm')+':'+String(d.target),time=timestamp(d.at);latest.set(key,Math.max(latest.get(key)||0,time))}
    return contacts.map(contact=>{const kind=type(contact),target=kind==='group'?contact.group_id:contact.user_id;return {contact,time:Math.max(timestamp(contact.scanned_at),latest.get(kind+':'+String(target))||0,leadTimes.get(kind+':'+String(target))||0)}}).sort((a,b)=>b.time-a.time).map(row=>row.contact);
  }
  function latestAccounts(accounts,contacts,history,resets){
    return accounts.map(account=>{const times=[account.health?.last_sent_at,account.health?.last_error_at,...contacts.filter(c=>c.scan_account===account.id).map(c=>c.scanned_at),...history.filter(d=>d.account_id===account.id).map(d=>d.at),...resets.filter(r=>r.account_id===account.id).map(r=>r.at)];return {account,time:times.reduce((n,t)=>Math.max(n,timestamp(t)),0)}}).sort((a,b)=>b.time-a.time).map(row=>row.account);
  }
  function summarize(rows){
    rows=latestFirst(rows);
    const sent=rows.filter(d=>d.status==='Sent'),pending=rows.some(d=>d.status==='Sending'||d.status==='Uncertain');
    return {rows,sent,latest:rows[0]||null,lastSent:sent[0]||null,firstMessage:sent.filter(d=>!d.followup_of).at(-1)||rows.at(-1)||null,lastFollowup:sent.find(d=>d.followup_of&&!d.conversation_reply)||null,followups:sent.filter(d=>!!d.followup_of&&!d.conversation_reply).length,canSend:sent.length===0&&!pending,canFollowup:sent.length>0&&!pending,pending};
  }
  function conversation(contact,history){
    const k=type(contact),target=String(k==='group'?contact.group_id:contact.user_id);
    return summarize(history.filter(d=>(d.kind||'dm')===k&&(d.id===contact.id||(target!=='undefined'&&String(d.target)===target))));
  }
  function conversations(history,leads=[]){
    const leadTimes=new Map(leads.map(l=>[l.key,l.last_activity_at]));
    const grouped=new Map();
    for(const d of history){const key=(d.kind||'dm')+':'+(d.target??d.id);if(!grouped.has(key))grouped.set(key,[]);grouped.get(key).push(d)}
    return latestFirst([...grouped.entries()].map(([key,rows])=>{const s=summarize(rows),activity=leadTimes.get(key);s.activity_at=timestamp(activity)>timestamp(s.latest.at)?activity:s.latest.at;return s}),s=>s.activity_at);
  }
  function hasReplied(lead){return !!lead&&(lead.reply_status==='Replied'||lead.stage==='Replied'||!!lead.latest_reply||(lead.replies||[]).length>0)}
  function followupEligible(summary,lead){return !!lead&&!hasReplied(lead)&&lead.kind==='dm'&&lead.stage!=='Client'&&summary.canFollowup}
  function normalizeToken(value){return String(value||'').trim().replace(/^\$+/,'')}
  function requiresToken(text){return /[$@]TOKEN\b|\{\{token\}\}/.test(text||'')}
  function personalize(text,contact,tokenSymbol='',exchange=''){
    const symbol=normalizeToken(tokenSymbol),handle=contact.username?'@'+String(contact.username).replace(/^@+/,''):(contact.name||'there');
    return String(text||'').replaceAll('@{{username}}',handle).replaceAll('{{username}}',handle).replaceAll('@username',handle).replaceAll('{{name}}',contact.name||'').replaceAll('{{role}}',contact.role||'').replaceAll('{{group}}',contact.group||'').replaceAll('{{token}}',symbol?'$'+symbol:'$TOKEN').replace(/[$@]TOKEN\b/g,symbol?'$'+symbol:'$TOKEN').replaceAll('{{exchange}}',exchanges[exchange]||exchange||'{{exchange}}');
  }
  function status(summary){const d=summary.latest;if(!d)return 'Not sent';if(d.status==='Sending')return 'Sending';if(d.status==='Uncertain')return 'Delivery needs review';if(d.conversation_reply)return d.status==='Sent'?'Reply sent':'Reply '+d.status.toLowerCase();if(d.followup_of)return d.status==='Sent'?'Follow-up sent':'Follow-up '+d.status.toLowerCase();return d.status==='Sent'?'Message sent':d.status}
  function deliveryStates(summary){
    function state(isFollowup){
      const rows=summary.rows.filter(d=>!d.conversation_reply&&!!d.followup_of===isFollowup),confirmed=rows.some(d=>d.status==='Sent'),latest=rows[0];
      return {label:confirmed?'Sent':'Not sent',sent:confirmed,detail:latest&&latest.status!=='Sent'?latest.status==='Uncertain'?'Delivery uncertain · check Telegram':latest.status==='Sending'?'Sending · awaiting confirmation':latest.status+(latest.error?' · '+latest.error:''):''};
    }
    return {message:state(false),followup:state(true)};
  }
  root.WMMMessageModel={exchanges,yesPitch,yesDemo,type,conversation,conversations,personalize,status,deliveryStates,introduction,followup,normalizeToken,requiresToken,latestFirst,latestContacts,latestAccounts,hasReplied,followupEligible};
})(typeof window==='undefined'?globalThis:window);
