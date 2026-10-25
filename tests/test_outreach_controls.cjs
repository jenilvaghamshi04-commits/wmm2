const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const {JSDOM,VirtualConsole}=require('jsdom');
const root=path.resolve(__dirname,'../dist');let html=fs.readFileSync(path.join(root,'index.html'),'utf8');
html=html.replace(/<script src="\/([^"?]+)(?:\?[^"]*)?"\s*><\/script>/g,(_,f)=>'<script>'+fs.readFileSync(path.join(root,f),'utf8').replace(/<\/script/gi,'<\\/script')+'</script>');
const errors=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(String(e)));
const dom=new JSDOM(html,{url:'https://qa.example/outreach-controls',runScripts:'dangerously',virtualConsole:vc,beforeParse(w){w.scrollTo=()=>{};w.matchMedia=()=>({matches:false,addEventListener(){}});w.fetch=async()=>{throw Error('No network allowed')};w.HTMLDialogElement.prototype.close=function(){this.open=false}}});
const w=dom.window,d=w.document;
setTimeout(()=>{try{
 w.eval(`renderOutreachSafety({accounts:[{id:1,label:'Account 1',authorized:true,error:'Spam restriction'},{id:2,label:'Account 2',authorized:true}],settings:{auto_yes_enabled:false,auto_followup_enabled:false},outreach_safety:{day:'2026-10-25',per_account_limit:10,team_limit:30,team_reserved:2,account_reserved:{'1':2},permissions:[],contacts:[{target:'123',name:'<img src=x onerror=bad()>',username:'test'}]}});view('safety')`);
 assert.equal(w.location.pathname,'/outreach-controls');assert(d.querySelector('#safety').classList.contains('active'));
 assert.match(d.querySelector('#outreachSummary').textContent,/10/);assert.match(d.querySelector('#permissionRecords').textContent,/New outreach is blocked/);
 assert.equal(d.querySelector('#permissionStatus').value,'Unknown');assert.equal(d.querySelector('#permissionConfirmed').checked,false);
 assert.equal(d.querySelector('#permissionPerson img'),null);assert.equal(d.querySelector('#outreachMode').disabled,true);
 assert.match(d.querySelector('#outreachAccounts').textContent,/Spam restriction/);
 assert.equal(errors.length,0,errors.join('\n'));console.log('Outreach controls UI passed: route, account caps, restriction visibility, unknown default and escaped contact text. No network or messages.');
 }finally{w.close()}},20);
