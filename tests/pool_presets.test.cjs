const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const script=fs.readFileSync(path.join(__dirname,'../ui/script.js'),'utf8');
const code=script.split('// BEGIN OPTIONAL POOL PRESETS')[1].split('// END OPTIONAL POOL PRESETS')[0];
function fixture(){
  const elements={};
  const element=()=>({value:'',checked:false,disabled:false,textContent:'',children:[],events:{},
    appendChild(child){this.children.push(child)},addEventListener(name,fn){this.events[name]=fn}});
  for(const id of ['poolPresetSelect','poolPresetReviewed','poolPresetApply','poolPresetPreview',
    'poolUrl','poolProfileFee','poolProfileResult','poolWorker','poolPassword','poolBackup1',
    'poolBackup2','poolBackup3','poolFailoverPolicy','poolPrimaryRecovery','poolFailoverEnabled',
    'poolProfileSelect','poolProfileName','poolProfileNotes','coinbaseAddress'])elements[id]=element();
  elements.poolUrl.value='stratum+tcp://old.example:3333';elements.poolProfileFee.value='7';
  for(const id of ['poolWorker','poolPassword','poolBackup1','poolBackup2','poolBackup3',
    'poolFailoverPolicy','poolPrimaryRecovery','poolProfileSelect','poolProfileName','poolProfileNotes','coinbaseAddress'])elements[id].value=`existing-${id}`;
  elements.poolFailoverEnabled.checked=true;
  const forbidden=()=>{throw Error('Unexpected API, persistence, or network call')};
  const context=vm.createContext({$:s=>elements[s.slice(1)],document:{createElement:element},
    callApi:forbidden,fetch:forbidden,XMLHttpRequest:forbidden,localStorage:{setItem:forbidden}});
  vm.runInContext(code,context);context.initPoolPresets();
  return {elements,context,snapshot:()=>JSON.stringify(elements)};
}
test('custom is default; selection previews without changing editor fields',()=>{
  const {elements:e,context:c}=fixture();assert.equal(e.poolPresetSelect.value,'');
  c.previewPoolPreset();assert.equal(e.poolPresetApply.disabled,true);
  e.poolPresetSelect.value='braiins';c.previewPoolPreset();
  assert.equal(e.poolUrl.value,'stratum+tcp://old.example:3333');assert.equal(e.poolProfileFee.value,'7');
  assert.match(e.poolPresetPreview.textContent,/account required/);assert.equal(e.poolPresetReviewed.checked,false);
  c.applyPoolPreset();assert.equal(e.poolProfileFee.value,'7');
});
test('each preset changes only URL and fee; preserves identities, credentials, backups and policy',()=>{
  for(const [id,url,fee] of [['braiins','stratum+tcp://stratum.braiins.com:3333','2.5'],
    ['ckpool-solo','stratum+tcp://stratum.ckpool.org:3333','2']]){
    const {elements:e,context:c}=fixture();
    const protectedIds=Object.keys(e).filter(k=>!k.startsWith('poolPreset')&&!['poolUrl','poolProfileFee','poolProfileResult'].includes(k));
    const before=protectedIds.map(k=>JSON.stringify(e[k]));
    e.poolPresetSelect.value=id;c.previewPoolPreset();e.poolPresetReviewed.checked=true;c.applyPoolPreset();
    assert.equal(e.poolUrl.value,url);assert.equal(e.poolProfileFee.value,fee);
    assert.deepEqual(protectedIds.map(k=>JSON.stringify(e[k])),before);
    assert.equal(e.poolPresetReviewed.checked,false);assert.equal(e.poolPresetApply.disabled,true);
  }
});
test('manual edits and profile resets invalidate consent; unknown entries cannot apply',()=>{
  const {elements:e,context:c}=fixture();e.poolPresetSelect.value='braiins';
  c.previewPoolPreset();e.poolPresetReviewed.checked=true;e.poolPresetReviewed.events.change();
  assert.equal(e.poolPresetApply.disabled,false);e.poolUrl.value='custom';e.poolUrl.events.input();
  assert.equal(e.poolPresetApply.disabled,true);assert.equal(e.poolPresetReviewed.checked,false);
  e.poolPresetReviewed.checked=true;c.resetPoolPreset();assert.equal(e.poolPresetSelect.value,'');
  e.poolPresetSelect.value='unknown';e.poolPresetReviewed.checked=true;c.applyPoolPreset();
  assert.equal(e.poolUrl.value,'custom');assert.equal(e.poolProfileFee.value,'7');
});
test('catalog has no default identity or credential fields and only documented entries',()=>{
  const {elements:e,context:c}=fixture();
  assert.deepEqual(e.poolPresetSelect.children.map(x=>x.value),['braiins','ckpool-solo']);
  const rows=JSON.parse(vm.runInContext('JSON.stringify(POOL_PRESETS)',c));
  for(const row of rows){
    assert.ok(row.sources.every(s=>s.startsWith('https://')));assert.equal(row.reviewed,'2026-09-27');
    assert.ok(!('pool_worker' in row));assert.ok(!('pool_password' in row));
  }
});
