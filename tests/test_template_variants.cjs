const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes=new Map();function node(id){if(!nodes.has(id))nodes.set(id,{value:'',textContent:'',innerHTML:'',querySelectorAll:()=>[],querySelector:()=>null});return nodes.get(id)}
const fields=[['initial','template','introduction'],['followup','followup_template','followup'],['yesPitch','yes_pitch_template','yesPitch'],['yesDemo','yes_demo_template','yesDemo']];
const ctx=vm.createContext({document:{addEventListener(){},getElementById:node,querySelector:()=>({textContent:''})},templateFields:fields,WMMMessageModel:{introduction:'Legacy introduction',followup:'Legacy followup',yesPitch:'Legacy pitch',yesDemo:'Legacy invitation',noReply:'Legacy no'},savedTemplate:'Initial',savedFollowupTemplate:'Follow',savedYesPitch:'Pitch',savedYesDemo:'Invite',savedNoReply:'No',Math});
vm.runInContext(fs.readFileSync('dist/template-variants.js','utf8'),ctx);const m=ctx.WMMTemplateVariants;
assert.equal(m.pick(['one','','three','','five'],()=>0).text,'one');assert.equal(m.pick(['one','','three','','five'],()=>0.5).text,'three');assert.equal(m.pick(['one','','three','','five'],()=>0.999).index,4);assert.throws(()=>m.pick([' ','','','','']),/at least one/);assert.equal(m.normalize(undefined,'Legacy')[0],'Legacy');assert.equal(m.normalize(['one']).length,5);
ctx.cfg={template:'Initial',followup_template:'Follow',yes_pitch_template:'Pitch',yes_demo_template:'Invite',no_reply_template:'No',template_variants:{template:['one','two','three','four','five']}};
vm.runInContext('hydrateTemplateVariants(cfg);loadVariantEditors();',ctx);assert.equal(node('initialTemplateEditor').value,'one');
node('initialTemplateEditor').value='Edited one';vm.runInContext("updateVariantDraft('initial')",ctx);const drafts=vm.runInContext('readVariantDrafts()',ctx);assert.equal(drafts.template[0],'Edited one');assert.equal(drafts.template[4],'five');assert.equal(drafts.followup_template[0],'Follow');
vm.runInContext("getInitialBatchPlan(['a','b'])",ctx);const original=vm.runInContext('initialBatchPlan',ctx);vm.runInContext('hydrateTemplateVariants(cfg)',ctx);assert.equal(vm.runInContext('initialBatchPlan',ctx),original);assert.equal(vm.runInContext("getInitialBatchPlan(['a','b'])",ctx),original.messages);
ctx.cfg.template_variants.template[4]='changed';vm.runInContext('hydrateTemplateVariants(cfg)',ctx);assert.equal(vm.runInContext('initialBatchPlan',ctx),null);
assert.throws(()=>vm.runInContext("savedTemplateVariants.template=['','','','',''];chooseContactInitial()",ctx),/Add and save/);
console.log('10 template variant UI checks passed: random boundaries, empty slots, defaults, independent drafts and stable preview plans.');
ctx.cfg.template_variants.template=['one','two','three','four','five'];ctx.cfg.template_rotation={template:{used:[],last:''}};
vm.runInContext('hydrateTemplateVariants(cfg)',ctx);
const batch=vm.runInContext("[...getInitialBatchPlan(['a','b','c','d','e','f','g','h','i','j']).values()].map(x=>x.text)",ctx);
assert.equal(new Set(batch.slice(0,5)).size,5);assert.equal(new Set(batch.slice(5)).size,5);assert.notEqual(batch[4],batch[5]);
vm.runInContext("recordTemplateChoices({template:'one'})",ctx);for(let i=0;i<20;i++)assert.notEqual(vm.runInContext("pickSavedTemplate('template').text",ctx),'one');
console.log('4 rotation UI checks passed: unique cycles, cycle boundary and used-option exclusion.');
