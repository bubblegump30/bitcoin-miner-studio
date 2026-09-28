const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const script=fs.readFileSync(path.join(__dirname,'../ui/script.js'),'utf8');
const code=script.split('// BEGIN OPTIONAL POOL PRESETS')[1].split('// END OPTIONAL POOL PRESETS')[0];
function fixture(){
  const elements={};
  const element=()=>({value:'',checked:false,disabled:false,textContent:'',children:[],events:{},attributes:{},
    appendChild(child){this.children.push(child)},addEventListener(name,fn){this.events[name]=fn},
    setAttribute(name,value){this.attributes[name]=value},focus(){this.focused=true}});
  for(const id of ['poolPresetSelect','poolPresetReviewed','poolPresetReviewedLabel','poolPresetApply','poolPresetPreview',
    'poolUrl','poolProfileFee','poolFeeHelp','poolProfileResult','poolWorker','poolPassword','poolBackup1',
    'poolBackup2','poolBackup3','poolFailoverPolicy','poolPrimaryRecovery','poolFailoverEnabled','poolProfileValidation',
    'poolProfileSelect','poolProfileName','poolProfileNotes','coinbaseAddress'])elements[id]=element();
  elements.poolUrl.value='stratum+tcp://old.example:3333';elements.poolProfileFee.value='7';
  elements.poolProfileName.value='Existing profile';
  for(const id of ['poolWorker','poolPassword','poolBackup1','poolBackup2','poolBackup3',
    'poolFailoverPolicy','poolPrimaryRecovery','poolProfileSelect','poolProfileName','poolProfileNotes','coinbaseAddress'])elements[id].value=`existing-${id}`;
  elements.poolFailoverEnabled.checked=true;
  const forbidden=()=>{throw Error('Unexpected API, persistence, or network call')};
  const context=vm.createContext({$:s=>elements[s.slice(1)],document:{createElement:element},
    URL,callApi:forbidden,fetch:forbidden,XMLHttpRequest:forbidden,localStorage:{setItem:forbidden}});
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
    const protectedIds=Object.keys(e).filter(k=>!k.startsWith('poolPreset')&&!['poolUrl','poolProfileFee','poolFeeHelp','poolProfileResult'].includes(k));
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
  assert.deepEqual(e.poolPresetSelect.children.map(x=>x.value),['braiins','btc-pow-lab','ckpool-solo']);
  const rows=JSON.parse(vm.runInContext('JSON.stringify(POOL_PRESETS)',c));
  for(const row of rows){
    assert.ok(row.sources.every(s=>s.startsWith('https://')));assert.match(row.reviewed,/^2026-09-2[78]$/);
    assert.ok(!('pool_worker' in row));assert.ok(!('pool_password' in row));
  }
});
test('hybrid solo preset changes only endpoint and leaves generic fee estimate untouched',()=>{
  const {elements:e,context:c}=fixture();
  const protectedIds=Object.keys(e).filter(k=>!k.startsWith('poolPreset')&&!['poolUrl','poolFeeHelp','poolProfileResult'].includes(k));
  const before=protectedIds.map(k=>JSON.stringify(e[k]));
  e.poolPresetSelect.value='btc-pow-lab';c.previewPoolPreset();
  assert.match(e.poolPresetPreview.textContent,/unchanged.*cannot represent hybrid payouts/);
  assert.match(e.poolPresetPreview.textContent,/Automatic Community payout broadcasting is currently disabled/);
  assert.match(e.poolPresetReviewedLabel.textContent,/only the primary endpoint/);
  assert.equal(e.poolUrl.value,'stratum+tcp://old.example:3333');
  e.poolPresetReviewed.checked=true;c.applyPoolPreset();
  assert.equal(e.poolUrl.value,'stratum+tcp://stratum.btcpowlab-pool.com:3333');
  assert.equal(e.poolProfileFee.value,'7');
  assert.match(e.poolFeeHelp.textContent,/does not model finder or Community rewards/);
  assert.deepEqual(protectedIds.map(k=>JSON.stringify(e[k])),before);
  assert.equal(e.poolPresetApply.disabled,true);assert.equal(e.poolPresetReviewed.checked,false);
});
test('Custom selection preserves applied and manually edited values',()=>{
  const {elements:e,context:c}=fixture();
  e.poolPresetSelect.value='braiins';c.previewPoolPreset();e.poolPresetReviewed.checked=true;c.applyPoolPreset();
  e.poolWorker.value='my.worker';e.poolPresetSelect.value='';e.poolPresetSelect.events.change();
  assert.equal(e.poolUrl.value,'stratum+tcp://stratum.braiins.com:3333');
  assert.equal(e.poolProfileFee.value,'2.5');assert.equal(e.poolWorker.value,'my.worker');
  assert.match(e.poolPresetPreview.textContent,/Current endpoint, fee and all other edits are kept/);
});
test('profile validation pinpoints missing and malformed fields without exposing password',()=>{
  const {elements:e,context:c}=fixture();
  e.poolProfileName.value='';e.poolUrl.value='stratum+tcp://user:secret@pool.example:3333';
  e.poolBackup1.value='stratum+tcp://backup.example';e.poolBackup2.value='';e.poolBackup3.value='';e.poolWorker.value='';e.poolProfileFee.value='101';
  const errors=c.validateProfileEditor();c.showProfileValidation(errors);
  assert.equal(errors.length,5);assert.equal(e.poolProfileName.focused,true);
  assert.equal(e.poolUrl.attributes['aria-invalid'],'true');
  assert.doesNotMatch(e.poolProfileValidation.textContent,/secret/);
  e.poolProfileName.value='Ready';e.poolUrl.value='stratum+tcp://pool.example:3333';
  e.poolBackup1.value='';e.poolWorker.value='account.worker';e.poolProfileFee.value='2.5';
  assert.equal(c.validateProfileEditor().length,0);c.showProfileValidation([]);
  assert.equal(e.poolProfileValidation.hidden,true);
});
