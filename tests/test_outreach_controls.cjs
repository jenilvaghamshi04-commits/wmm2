const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const {JSDOM,VirtualConsole}=require('jsdom');
const root=path.resolve(__dirname,'../dist');let html=fs.readFileSync(path.join(root,'index.html'),'utf8');
html=html.replace(/<script src="\/([^"?]+)(?:\?[^"]*)?"\s*><\/script>/g,(_,f)=>'<script>'+fs.readFileSync(path.join(root,f),'utf8').replace(/<\/script/gi,'<\\/script')+'</script>');
const errors=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(String(e)));
const dom=new JSDOM(html,{url:'https://qa.example/outreach-controls',runScripts:'dangerously',virtualConsole:vc,beforeParse(w){w.scrollTo=()=>{};w.matchMedia=()=>({matches:false,addEventListener(){}});w.fetch=async()=>{throw Error('No network allowed')};w.HTMLDialogElement.prototype.close=function(){this.open=false}}});
const w=dom.window,d=w.document;
setTimeout(()=>{try{
 w.eval(`renderOutreachSafety({accounts:[{id:1,authorized:true}],settings:{auto_yes_enabled:false,auto_followup_enabled:false},outreach_safety:{day:'2026-10-25',team_reserved:2,account_reserved:{'1':2}}});view('connections')`);
 assert.equal(w.location.pathname,'/settings');assert.equal(d.querySelector('[data-view="safety"]'),null);
 assert.equal(d.querySelector('#safety'),null);assert.equal(d.querySelector('#permissionForm'),null);
 assert.match(d.querySelector('#sendLimitSummary').textContent,/10 unique recipients/);
 assert.equal(d.querySelector('#applyReviewedSending').disabled,true);
 assert.equal(errors.length,0,errors.join('\n'));console.log('Removed page/form verified; Settings retains caps and reviewed sending. No network or messages.');
 }finally{w.close()}},20);
