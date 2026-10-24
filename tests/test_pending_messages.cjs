const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const ctx=vm.createContext({document:{addEventListener(){}},Date,Set,Map});vm.runInContext(fs.readFileSync('dist/pending-messages.js','utf8'),ctx);const model=ctx.WMMPendingMessages;
const now=Date.parse('2026-10-24T10:00:00Z');
const rows=Array.from({length:10},(_,i)=>({queue_id:'q'+i,batch_id:'batch-10',account_id:1,target:String(i+1),name:'Person '+(i+1),status:'Queued',created_at:new Date(now).toISOString(),next_attempt_at:new Date(now+i*120000).toISOString(),delay_seconds:120,message:'Reviewed message '+i}));
let groups=model.build(rows);assert.equal(groups.length,1);assert.equal(groups[0].total,10);assert.equal(groups[0].pending.length,10);assert.equal(new Set(groups[0].rows.map(r=>r.due_at)).size,10);assert.equal(model.countdown(groups[0].rows[1],now),'2m 0s');assert.equal(model.countdown(groups[0].rows[0],now),'Due · waiting for queue');
rows[0].status='Sent';rows[0].next_attempt_at='';groups=model.build(rows);assert.equal(groups[0].pending.length,9);assert.equal(groups[0].sent,1);assert.equal(model.countdown(groups[0].rows[0],now),'Sent');
rows[1].status='Needs attention';rows[1].error='Telegram requires a 60 second wait';groups=model.build(rows);assert.equal(model.countdown(groups[0].rows.find(r=>r.queue_id==='q1'),now),'Paused · review');
let issues=model.issues(groups,[{id:1,authorized:false,error:'Connection unavailable'}]);assert.ok(issues.some(i=>i.title==='Original account disconnected'));assert.ok(issues.some(i=>i.message.includes('60 second wait')));assert.ok(issues.some(i=>i.message==='Connection unavailable'));
const withSchedule=model.build(rows,[{schedule_id:'s1',backend_queue_id:'q2',status:'Queued',account_id:1,target:'3',scheduled_at:new Date(now).toISOString()}]);assert.equal(withSchedule.flatMap(g=>g.rows).length,10,'backend-linked schedules are not counted twice');
assert.equal(model.build(rows.map(r=>({...r,status:'Sent'}))).length,0,'completed batches leave the pending page');
assert.equal(model.countdown({status:'Queued',due_at:null},now),'Waiting for queue');assert.equal(model.countdown({status:'Waiting for sign-in'},now),'Sign-in required');
const routes=require('../dist/page-routes.js');assert.equal(routes.resolve('/pending-messages'),'pending');
console.log('Ten-recipient timing, progress, truthful countdowns, issue reporting and schedule deduplication passed.');

assert.equal(model.issues([{rows:[{status:'Cancelled',error:'Cancelled by you.'}],account_id:1}],[{id:1,authorized:true}]).length,0,'intentional cancellations are not errors');
