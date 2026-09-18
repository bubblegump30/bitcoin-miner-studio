
const $ = (sel, root=document) => root.querySelector(sel);
const $$ = (sel, root=document) => [...root.querySelectorAll(sel)];
let bootstrap = null;
let securityTrusted = false;
let securityChecked = false;
let lastState = null;
let history = [];
let apiReady = false;
let apiInitialized = false;
let bridgeRetryTimer = null;
let bridgeRetryCount = 0;
let refreshTimer = null;
let refreshInFlight = false;
let performancePlusEnabled = false;
let stateRenderCount = 0;
let lastLogSignature = '';
let lastAsicSignature = '';
let analyticsRangeSeconds=3600;
let analyticsLastFetch=0;
let analyticsInFlight=false;
let lastAnalytics=null;
let currentUiTheme='purple';
let miningAssistantState=null;
let profitabilityState=null;
let hardwareCompatibilityState=null;
let poolProfilesState=null;
let trayState=null;
let benchmarkLabState=null;
let miningAcademyState=null;
let academyCurrentLessonId="fundamentals";
let academyFilter="all";
let pendingAcademyLesson="";
let workspaceState=null;
let architectureState=null;
let currentView='dashboard';
let commandPaletteIndex=0;
const VIEW_META={
  dashboard:{label:'Dashboard',icon:'⌂',group:'Workspace',keywords:'home overview command center'},
  benchmark:{label:'Benchmark Lab',icon:'◇',group:'Workspace',keywords:'benchmark sha256d performance score'},
  academy:{label:'Mining Academy',icon:'◎',group:'Workspace',keywords:'learn lessons quiz hash difficulty merkle nonce'},
  assistant:{label:'Mining Assistant',icon:'✦',group:'Workspace',keywords:'guide readiness can i mine'},
  profitability:{label:'Profitability & Power',icon:'₿',group:'Workspace',keywords:'power electricity economics profit'},
  hardware:{label:'Hardware Compatibility',icon:'▦',group:'Workspace',keywords:'asic hardware compatibility devices'},
  asic:{label:'ASIC Control',icon:'◈',group:'Operations',keywords:'fleet hardware miner device'},
  pool:{label:'Pool PowerTools',icon:'⌁',group:'Operations',keywords:'stratum pool failover profile'},
  core:{label:'Bitcoin Core',icon:'Ⓑ',group:'Operations',keywords:'node rpc template regtest solo'},
  monitoring:{label:'Monitoring',icon:'⌁',group:'Operations',keywords:'analytics history charts telemetry local'},
  tray:{label:'Tray & Background',icon:'▣',group:'Operations',keywords:'windows background notifications'},
  logs:{label:'Logs',icon:'▤',group:'Operations',keywords:'activity events log'},
  diagnostics:{label:'Diagnostics & Support',icon:'⊕',group:'System',keywords:'health support bundle architecture services'},
  minerxp:{label:'Miner XP',icon:'★',group:'System',keywords:'hash hunt xp game achievements'},
  release:{label:'Update & Release',icon:'⇧',group:'System',keywords:'update package staging release preflight'},
  security:{label:'Purple Dragon',icon:'◆',group:'System',keywords:'security trust signature provenance integrity'}
};
const UI_THEME_NAMES={
  purple:'Purple',graphite:'Graphite',obsidian:'Obsidian',frost:'Frost',
  sapphire:'Sapphire',crimson:'Crimson',emerald:'Emerald',cyan:'Cyan',
  amber:'Amber',rose:'Rose'
};
const UI_THEME_STORAGE='bms-ui-theme-v1';

function normalizeUiTheme(value){
  const key=String(value||'').trim().toLowerCase();
  return Object.prototype.hasOwnProperty.call(UI_THEME_NAMES,key)?key:'purple';
}
function cssVar(name,fallback=''){
  const value=getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value||fallback;
}
function cssRgb(name,fallback='150,84,255'){
  return cssVar(name,fallback);
}
function applyUiTheme(theme,{remember=true}={}){
  const normalized=normalizeUiTheme(theme);
  currentUiTheme=normalized;
  document.documentElement.dataset.theme=normalized;
  if(remember){try{localStorage.setItem(UI_THEME_STORAGE,normalized)}catch{}}
  const label=UI_THEME_NAMES[normalized]||'Purple';
  const current=$('#themeCurrent');if(current)current.textContent=label.toUpperCase();
  const activeName=$('#themeActiveName');if(activeName)activeName.textContent=label;
  $$('.theme-option').forEach(button=>{
    const active=button.dataset.themeValue===normalized;
    button.classList.toggle('active',active);
    button.setAttribute('aria-pressed',active?'true':'false');
  });
  if(lastState)drawCharts();
  if(lastAnalytics)renderAnalytics(lastAnalytics);
  return normalized;
}
(function applyEarlyStoredTheme(){
  let stored='purple';
  try{stored=localStorage.getItem(UI_THEME_STORAGE)||'purple'}catch{}
  document.documentElement.dataset.theme=normalizeUiTheme(stored);
  currentUiTheme=normalizeUiTheme(stored);
})();


function bridgeAvailable(method=null){
  const api=window.pywebview?.api;
  return !!api && (!method || typeof api[method]==='function');
}

function setBridgeUiState(ready){
  apiReady=!!ready;
  document.documentElement.dataset.pythonApi=ready?'ready':'waiting';
  $$('.requires-python-api').forEach(el=>{el.disabled=!ready;});
}

function applyPerformancePlus(enabled){
  performancePlusEnabled=!!enabled;
  document.documentElement.classList.toggle('performance-plus',performancePlusEnabled);
  const button=$('#performancePlusToggle');
  const state=$('#performancePlusState');
  if(button)button.classList.toggle('active',performancePlusEnabled);
  if(state)state.textContent=performancePlusEnabled?'ON':'OFF';
  if(refreshTimer){
    clearTimeout(refreshTimer);
    refreshTimer=null;
    if(apiInitialized)scheduleStateRefresh(currentRefreshDelay());
  }
}

function currentRefreshDelay(){
  if(document.hidden)return performancePlusEnabled?10000:5000;
  return performancePlusEnabled?3000:1500;
}

function lightweightSignature(value){
  try{return JSON.stringify(value)}catch{return String(Date.now())}
}

function scheduleBridgeRetry(){
  if(apiInitialized || bridgeRetryTimer)return;
  const delay=Math.min(1500,500+Math.floor(bridgeRetryCount/10)*250);
  bridgeRetryTimer=setTimeout(()=>{
    bridgeRetryTimer=null;
    bridgeRetryCount+=1;
    if(bridgeAvailable('get_bootstrap')){
      init();
      return;
    }
    const box=$('#coreSetupResult');
    if(box && bridgeRetryCount%4===0){
      box.textContent=`Connecting to Bitcoin Miner Studio backend... retry ${bridgeRetryCount}`;
    }
    scheduleBridgeRetry();
  },delay);
}

function showToast(message){
  const toast=$('#toast'); if(!toast)return;toast.textContent=message; toast.classList.add('show');
  clearTimeout(window.__toastTimer); window.__toastTimer=setTimeout(()=>toast.classList.remove('show'),2200);
}

function viewLabel(name){return VIEW_META[name]?.label||String(name||'').replaceAll('_',' ')}

function renderWorkspaceBar(state=workspaceState){
  state=state||{};workspaceState=state;
  const current=$('#workspaceCurrent');if(current)current.textContent=viewLabel(currentView);
  const recents=$('#workspaceRecents');
  if(recents){
    const rows=(state.recent_views||[]).filter(view=>VIEW_META[view]&&view!==currentView).slice(0,5);
    recents.innerHTML=rows.map(view=>`<button class="workspace-recent-chip" type="button" data-workspace-recent="${escapeHtml(view)}">${escapeHtml(viewLabel(view))}</button>`).join('');
  }
  const shell=$('.app-shell');
  const compact=!!state.sidebar_compact;
  if(shell)shell.classList.toggle('sidebar-compact',compact);
  const toggle=$('#sidebarCompactToggle');if(toggle){toggle.textContent=compact?'⇥':'⇤';toggle.setAttribute('aria-pressed',compact?'true':'false')}
}

function applyWorkspaceState(state,{restoreView=false}={}){
  workspaceState=state||workspaceState||{last_view:'dashboard',recent_views:['dashboard'],sidebar_compact:false,command_usage:{}};
  renderWorkspaceBar(workspaceState);
  if(restoreView){
    const target=VIEW_META[workspaceState.last_view]?workspaceState.last_view:'dashboard';
    setView(target,{persist:false});
  }
}

async function persistWorkspaceView(name){
  if(!apiInitialized||!bridgeAvailable('record_workspace_view'))return;
  try{
    const r=await callApi('record_workspace_view',name);
    if(r?.ok&&r.workspace)applyWorkspaceState(r.workspace);
  }catch(e){console.debug('Workspace view persistence:',e)}
}

function setView(name,{persist=true}={}){
  if(!VIEW_META[name]||!$(`#view-${name}`))name='dashboard';
  const changed=currentView!==name;
  currentView=name;
  $$('.nav-item').forEach(b=>b.classList.toggle('active',b.dataset.view===name));
  $$('.view').forEach(v=>v.classList.toggle('active',v.id===`view-${name}`));
  $('.sidebar')?.classList.remove('open');
  const current=$('#workspaceCurrent');if(current)current.textContent=viewLabel(name);
  document.title=`${viewLabel(name)} — Bitcoin Miner Studio v2.0.2`;
  if(workspaceState){
    const recent=[name,...(workspaceState.recent_views||[]).filter(x=>x!==name)].slice(0,8);
    workspaceState={...workspaceState,last_view:name,recent_views:recent};
    renderWorkspaceBar(workspaceState);
  }
  if(changed&&persist)persistWorkspaceView(name);
  if(name==='monitoring' && apiInitialized)refreshAnalytics(true);
  if(name==='release' && apiInitialized){refreshUpdateReleaseCenter(false);refreshReleaseCandidate();}
  if(name==='diagnostics' && apiInitialized)refreshDiagnosticsCenter(false);
  if(name==='assistant' && apiInitialized)refreshMiningAssistant(false);
  if(name==='profitability' && apiInitialized)refreshProfitabilityState();
  if(name==='hardware' && apiInitialized)refreshHardwareCompatibility(false);
  if(name==='pool' && apiInitialized)refreshPoolProfiles(false);
  if(name==='tray' && apiInitialized)refreshTrayState(false);
  if(name==='benchmark' && apiInitialized)refreshBenchmarkLab(false);
  if(name==='academy' && apiInitialized)refreshMiningAcademy(false);
}

function renderArchitecture(arch,workspace=null){
  if(!arch)return;architectureState=arch;
  const overall=String(arch.overall||'STARTING').toUpperCase();
  const issues=Number(arch.degraded||0)+Number(arch.errors||0);
  const chip=$('#architectureTopChip');
  if(chip){
    chip.classList.remove('healthy','attention','degraded');
    chip.classList.add(overall==='HEALTHY'?'healthy':(overall==='ATTENTION'?'attention':'degraded'));
  }
  if($('#architectureTopState'))$('#architectureTopState').textContent=overall;
  if($('#workspaceArchitecture'))$('#workspaceArchitecture').textContent=`${arch.architecture||'BMS-ARCH-2'} · ${overall}`;
  if($('#v2ArchOverall'))$('#v2ArchOverall').textContent=overall;
  if($('#v2ArchServices'))$('#v2ArchServices').textContent=Number(arch.registered||0);
  if($('#v2ArchRunning'))$('#v2ArchRunning').textContent=Number(arch.running||0);
  if($('#v2ArchIssues'))$('#v2ArchIssues').textContent=issues;
  if($('#architectureServiceMeta'))$('#architectureServiceMeta').textContent=arch.architecture||'BMS-ARCH-2';
  if($('#architectureServiceOverall'))$('#architectureServiceOverall').textContent=overall;
  if($('#architectureServiceCount'))$('#architectureServiceCount').textContent=Number(arch.registered||0);
  if($('#architectureServiceRunning'))$('#architectureServiceRunning').textContent=Number(arch.running||0);
  if($('#architectureServiceIssues'))$('#architectureServiceIssues').textContent=issues;
  const grid=$('#architectureServiceGrid');
  if(grid){
    const rows=Array.isArray(arch.services)?arch.services:[];
    grid.innerHTML=rows.length?rows.map(row=>`<article class="architecture-service-row" data-state="${escapeHtml(row.state||'idle')}"><header><i></i><strong>${escapeHtml(row.label||row.id||'Service')}</strong></header><small>${escapeHtml(String(row.state||'idle').toUpperCase())} · ${escapeHtml(row.category||'system')}</small><p title="${escapeHtml(row.message||'')}">${escapeHtml(row.message||'Ready')}</p></article>`).join(''):'<div class="empty-state">No registered services.</div>';
  }
  if(workspace)applyWorkspaceState(workspace);
}

function toggleSidebarCompact(){
  const next=!$('.app-shell')?.classList.contains('sidebar-compact');
  const optimistic={...(workspaceState||{}),sidebar_compact:next};
  applyWorkspaceState(optimistic);
  if(apiInitialized&&bridgeAvailable('set_workspace_preferences')){
    callApi('set_workspace_preferences',next,null).then(r=>{if(r?.ok&&r.workspace)applyWorkspaceState(r.workspace)}).catch(e=>showToast(`Workspace preference: ${e.message}`));
  }
}

function commandDefinitions(){
  const usage=workspaceState?.command_usage||{};
  const views=Object.entries(VIEW_META).map(([id,meta])=>({
    id:`view:${id}`,label:meta.label,description:`Open ${meta.group} workspace`,icon:meta.icon,type:'WORKSPACE',
    keywords:`${meta.keywords||''} ${meta.group}`.toLowerCase(),score:Number(usage[`view:${id}`]||0),
    run:()=>setView(id)
  }));
  const actions=[
    {id:'action:refresh',label:'Refresh Current State',description:'Refresh live application state now',icon:'↻',type:'ACTION',keywords:'reload refresh state',run:()=>$('#refreshBtn')?.click()},
    {id:'action:verify-security',label:'Verify Purple Dragon Build',description:'Run offline publisher signature and file-integrity verification',icon:'◆',type:'ACTION',keywords:'security trust signature verify',run:async()=>{setView('security');const r=await callApi('verify_security_now');if(r?.security)renderSecurity(r.security);showToast(r?.ok?'Build verified':'Build verification failed')}},
    {id:'action:diagnostics',label:'Run Quick Diagnostics',description:'Open Diagnostics and run a read-only Quick Scan',icon:'⊕',type:'ACTION',keywords:'health support scan diagnostic',run:()=>{setView('diagnostics');runDiagnosticsUi('quick')}},
    {id:'action:preflight',label:'Run Release Preflight',description:'Open Update & Release Center and evaluate release gates',icon:'⇧',type:'ACTION',keywords:'release stable readiness preflight',run:()=>{setView('release');$('#rcPreflight')?.click()}},
    {id:'action:performance',label:'Toggle Performance+',description:'Switch reduced-overhead UI mode',icon:'⚡',type:'ACTION',keywords:'performance gpu overhead',run:()=>$('#performancePlusToggle')?.click()},
    {id:'action:compact',label:'Toggle Compact Sidebar',description:'Switch between full and icon-focused navigation',icon:'⇤',type:'ACTION',keywords:'sidebar navigation compact',run:()=>toggleSidebarCompact()}
  ].map(cmd=>({...cmd,score:Number(usage[cmd.id]||0)}));
  return [...views,...actions];
}

function filteredCommands(query=''){
  const q=String(query||'').trim().toLowerCase();
  return commandDefinitions().filter(cmd=>!q||`${cmd.label} ${cmd.description} ${cmd.keywords}`.toLowerCase().includes(q))
    .sort((a,b)=>(b.score-a.score)||a.label.localeCompare(b.label));
}

function renderCommandPalette(query=''){
  const root=$('#commandPaletteResults');if(!root)return;
  const rows=filteredCommands(query);
  commandPaletteIndex=Math.max(0,Math.min(commandPaletteIndex,Math.max(0,rows.length-1)));
  root.innerHTML=rows.length?rows.map((cmd,index)=>`<button class="command-item ${index===commandPaletteIndex?'active':''}" type="button" data-command-id="${escapeHtml(cmd.id)}"><span class="command-item-icon">${escapeHtml(cmd.icon)}</span><span class="command-item-copy"><strong>${escapeHtml(cmd.label)}</strong><small>${escapeHtml(cmd.description)}</small></span><span class="command-item-type">${escapeHtml(cmd.type)}</span></button>`).join(''):'<div class="empty-state">No matching commands.</div>';
  if($('#commandPaletteCount'))$('#commandPaletteCount').textContent=`${rows.length} command${rows.length===1?'':'s'}`;
  root.querySelector('.command-item.active')?.scrollIntoView({block:'nearest'});
}

function openCommandPalette(initial=''){
  const palette=$('#commandPalette'),input=$('#commandPaletteInput');if(!palette||!input)return;
  palette.hidden=false;commandPaletteIndex=0;input.value=String(initial||'');renderCommandPalette(input.value);
  requestAnimationFrame(()=>{input.focus();input.select()});
}
function closeCommandPalette(){const palette=$('#commandPalette');if(palette)palette.hidden=true}
async function runPaletteCommand(id){
  const cmd=commandDefinitions().find(row=>row.id===id);if(!cmd)return;
  closeCommandPalette();
  try{
    if(apiInitialized&&bridgeAvailable('record_workspace_command')){
      callApi('record_workspace_command',id).then(r=>{if(r?.ok&&r.workspace)workspaceState=r.workspace}).catch(()=>{});
    }
    await cmd.run();
  }catch(e){showToast(e.message||String(e))}
}

$$('.nav-item').forEach(b=>{b.title=viewLabel(b.dataset.view);b.addEventListener('click',()=>setView(b.dataset.view))});
$$('[data-view-jump]').forEach(b=>b.addEventListener('click',()=>setView(b.dataset.viewJump)));
$('#mobileMenu')?.addEventListener('click',()=>$('.sidebar')?.classList.toggle('open'));
$('#sidebarCompactToggle')?.addEventListener('click',toggleSidebarCompact);
$('#workspaceCommandButton')?.addEventListener('click',()=>openCommandPalette());
$('#workspaceRecents')?.addEventListener('click',e=>{const b=e.target.closest('[data-workspace-recent]');if(b)setView(b.dataset.workspaceRecent)});
$('#searchInput')?.addEventListener('focus',e=>{openCommandPalette(e.target.value);e.target.blur()});
$('#searchInput')?.addEventListener('click',()=>openCommandPalette());
$('#commandPaletteInput')?.addEventListener('input',e=>{commandPaletteIndex=0;renderCommandPalette(e.target.value)});
$('#commandPaletteResults')?.addEventListener('click',e=>{const b=e.target.closest('[data-command-id]');if(b)runPaletteCommand(b.dataset.commandId)});
$('#commandPalette')?.addEventListener('click',e=>{if(e.target===$('#commandPalette'))closeCommandPalette()});
document.addEventListener('keydown',e=>{
  if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();openCommandPalette();return}
  const palette=$('#commandPalette');
  if(palette&&!palette.hidden){
    if(e.key==='Escape'){e.preventDefault();closeCommandPalette();return}
    if(e.key==='ArrowDown'||e.key==='ArrowUp'){
      e.preventDefault();const rows=filteredCommands($('#commandPaletteInput')?.value||'');
      if(rows.length){commandPaletteIndex=(commandPaletteIndex+(e.key==='ArrowDown'?1:-1)+rows.length)%rows.length;renderCommandPalette($('#commandPaletteInput')?.value||'')}
      return;
    }
    if(e.key==='Enter'){
      e.preventDefault();const rows=filteredCommands($('#commandPaletteInput')?.value||'');if(rows[commandPaletteIndex])runPaletteCommand(rows[commandPaletteIndex].id);return;
    }
  }
});


/* --------------------------------------------------------------------------
   v0.6.1 — Miner XP & Hash Hunt
   Cosmetic-only local progression. No Bitcoin Core / ASIC / mining API calls.
   -------------------------------------------------------------------------- */
const HASH_HUNT_STORAGE='bitcoin-miner-studio.hash-hunt.v1';

const HASH_HUNT_DIFFICULTIES={
  casual:{label:'CASUAL',targetByte:128,requiredShares:6,attemptXp:1,shareXp:6,blockXp:60,unlockLevel:1},
  standard:{label:'STANDARD',targetByte:64,requiredShares:8,attemptXp:1,shareXp:10,blockXp:120,unlockLevel:1},
  hard:{label:'HARD',targetByte:32,requiredShares:10,attemptXp:2,shareXp:20,blockXp:240,unlockLevel:1},
  dragon:{label:'PURPLE DRAGON',targetByte:16,requiredShares:12,attemptXp:3,shareXp:35,blockXp:420,unlockLevel:7}
};

const HASH_HUNT_ACHIEVEMENTS=[
  {id:'first-share',icon:'◇',name:'First Share',desc:'Discover your first Hash Hunt valid share.',xp:25},
  {id:'streak-five',icon:'⚡',name:'Hot Streak',desc:'Reach a 5× valid-share streak.',xp:40},
  {id:'fifty-attempts',icon:'▥',name:'Hash Apprentice',desc:'Run 50 simulated hash attempts.',xp:50},
  {id:'first-block',icon:'₿',name:'Block Builder',desc:'Complete and claim your first mini-game block.',xp:100},
  {id:'dragon-share',icon:'◆',name:'Purple Dragon Share',desc:'Find a valid share on Purple Dragon difficulty.',xp:125},
  {id:'five-blocks',icon:'★',name:'Hash Hunter',desc:'Claim five Hash Hunt block bonuses.',xp:200}
];

const MINER_UNLOCKS=[
  {level:3,icon:'◇',name:'Bronze Hash Badge',desc:'Achievement cards gain a rank highlight.'},
  {level:5,icon:'✦',name:'Holographic Rank Glow',desc:'Miner Rank cards gain a subtle holographic glow.'},
  {level:7,icon:'◆',name:'Purple Dragon Difficulty',desc:'Unlock the 1 / 16 Hash Hunt target.'},
  {level:10,icon:'◈',name:"Dragon's Lair Accent",desc:'Unlock a stronger Purple Dragon game-panel accent.'},
  {level:15,icon:'₿',name:'Satoshi Elite Coin',desc:'Unlock the elite Miner Rank coin glow.'}
];

function defaultHashHuntState(){
  return{
    version:1,xp:0,attempts:0,totalShares:0,streak:0,bestStreak:0,blocks:0,
    sharesInBlock:0,difficulty:'standard',slots:[],claimReady:false,
    achievements:[],lastHash:'',lastValid:false,lastMessage:'',lastTitle:'Ready for a hash attempt.'
  };
}

function loadHashHuntState(){
  try{
    const raw=localStorage.getItem(HASH_HUNT_STORAGE);
    if(!raw)return defaultHashHuntState();
    const parsed=JSON.parse(raw);
    const state={...defaultHashHuntState(),...parsed};
    if(!HASH_HUNT_DIFFICULTIES[state.difficulty])state.difficulty='standard';
    state.xp=Math.max(0,Math.floor(Number(state.xp||0)));
    state.attempts=Math.max(0,Math.floor(Number(state.attempts||0)));
    state.totalShares=Math.max(0,Math.floor(Number(state.totalShares||0)));
    state.streak=Math.max(0,Math.floor(Number(state.streak||0)));
    state.bestStreak=Math.max(state.streak,Math.floor(Number(state.bestStreak||0)));
    state.blocks=Math.max(0,Math.floor(Number(state.blocks||0)));
    state.sharesInBlock=Math.max(0,Math.floor(Number(state.sharesInBlock||0)));
    state.slots=Array.isArray(state.slots)?state.slots.map(x=>String(x).slice(0,4).toUpperCase()):[];
    state.achievements=Array.isArray(state.achievements)?[...new Set(state.achievements.map(String))]:[];
    return state;
  }catch{
    return defaultHashHuntState();
  }
}

let hashHuntState=loadHashHuntState();
let hashHuntBusy=false;

function saveHashHuntState(){
  try{localStorage.setItem(HASH_HUNT_STORAGE,JSON.stringify(hashHuntState))}catch{}
}

function minerNextThreshold(level){
  level=Math.max(1,Math.floor(Number(level||1)));
  return 25*level*(level+1);
}
function minerLevelFloor(level){
  level=Math.max(1,Math.floor(Number(level||1)));
  return level<=1?0:25*(level-1)*level;
}
function minerLevelFromXp(xp){
  xp=Math.max(0,Math.floor(Number(xp||0)));
  let level=1;
  while(level<50 && xp>=minerNextThreshold(level))level+=1;
  return level;
}
function minerRankTitle(level){
  if(level>=20)return'Satoshi Elite';
  if(level>=15)return'Hash Legend';
  if(level>=10)return'Solo Vanguard';
  if(level>=7)return'Purple Dragon Miner';
  if(level>=5)return'Block Builder';
  if(level>=3)return'Share Scout';
  return'Hash Rookie';
}
function hashHuntDifficulty(){
  return HASH_HUNT_DIFFICULTIES[hashHuntState.difficulty]||HASH_HUNT_DIFFICULTIES.standard;
}
function awardHashXp(amount){
  hashHuntState.xp=Math.max(0,Math.floor(Number(hashHuntState.xp||0)+Number(amount||0)));
}
function unlockHashAchievement(id){
  if(hashHuntState.achievements.includes(id))return false;
  const item=HASH_HUNT_ACHIEVEMENTS.find(x=>x.id===id);
  if(!item)return false;
  hashHuntState.achievements.push(id);
  awardHashXp(item.xp);
  return true;
}
function checkHashAchievements(){
  const unlocked=[];
  if(hashHuntState.totalShares>=1 && unlockHashAchievement('first-share'))unlocked.push('First Share');
  if(hashHuntState.bestStreak>=5 && unlockHashAchievement('streak-five'))unlocked.push('Hot Streak');
  if(hashHuntState.attempts>=50 && unlockHashAchievement('fifty-attempts'))unlocked.push('Hash Apprentice');
  if(hashHuntState.blocks>=1 && unlockHashAchievement('first-block'))unlocked.push('Block Builder');
  if(hashHuntState.blocks>=5 && unlockHashAchievement('five-blocks'))unlocked.push('Hash Hunter');
  return unlocked;
}

async function hashHuntDoubleSha256(){
  const random=new Uint8Array(24);
  if(window.crypto?.getRandomValues)crypto.getRandomValues(random);
  else for(let i=0;i<random.length;i++)random[i]=Math.floor(Math.random()*256);
  const context=new TextEncoder().encode(
    `BMS-HASH-HUNT|${Date.now()}|${performance.now()}|${hashHuntState.attempts}|${hashHuntState.xp}`
  );
  const payload=new Uint8Array(random.length+context.length);
  payload.set(random,0);payload.set(context,random.length);

  if(window.crypto?.subtle){
    const first=await crypto.subtle.digest('SHA-256',payload);
    const second=await crypto.subtle.digest('SHA-256',first);
    return [...new Uint8Array(second)].map(b=>b.toString(16).padStart(2,'0')).join('');
  }
  // WebView2 supports SubtleCrypto; this fallback remains cosmetic if an
  // unusual renderer disables it.
  let out='';
  for(let i=0;i<32;i++)out+=Math.floor(Math.random()*256).toString(16).padStart(2,'0');
  return out;
}

function renderHashHunt(){
  const state=hashHuntState;
  const difficulty=hashHuntDifficulty();
  const level=minerLevelFromXp(state.xp);
  const floor=minerLevelFloor(level);
  const next=minerNextThreshold(level);
  const levelSpan=Math.max(1,next-floor);
  const levelProgress=Math.max(0,Math.min(100,((state.xp-floor)/levelSpan)*100));
  const remaining=Math.max(0,next-state.xp);

  $('#minerXpLevel').textContent=`Level ${level}`;
  $('#minerXpTitle').textContent=minerRankTitle(level);
  $('#minerXpTotal').textContent=`${state.xp.toLocaleString()} / ${next.toLocaleString()} XP`;
  $('#minerXpRemaining').textContent=`${remaining.toLocaleString()} XP to next level`;
  $('#minerXpBar').style.width=`${levelProgress}%`;

  $('#dashboardMinerLevel').textContent=`Level ${level}`;
  $('#dashboardMinerTitle').textContent=minerRankTitle(level);
  $('#dashboardMinerXp').textContent=`${state.xp.toLocaleString()} / ${next.toLocaleString()} XP`;
  $('#dashboardMinerNext').textContent=`${remaining.toLocaleString()} XP to next level`;
  $('#dashboardMinerXpBar').style.width=`${levelProgress}%`;

  document.documentElement.classList.toggle('miner-rank-glow',level>=5);
  document.documentElement.classList.toggle('miner-dragon-lair',level>=10);
  document.documentElement.classList.toggle('miner-satoshi-elite',level>=15);

  const dragonOption=$('#hashHuntDragonOption');
  dragonOption.disabled=level<7;
  dragonOption.textContent=level<7
    ?`Purple Dragon · 1 / 16 · unlock Level 7`
    :'Purple Dragon · 1 / 16 target';

  if(state.difficulty==='dragon' && level<7){
    state.difficulty='standard';
    state.sharesInBlock=0;state.slots=[];state.claimReady=false;
    saveHashHuntState();
  }

  const active=hashHuntDifficulty();
  $('#hashHuntDifficulty').value=state.difficulty;
  $('#hashHuntModeBadge').textContent=active.label;
  $('#hashHuntShareXp').textContent=`+${active.shareXp} XP`;
  $('#hashHuntBlockXp').textContent=`+${active.blockXp} XP`;
  $('#hashHuntShares').textContent=`${state.sharesInBlock} / ${active.requiredShares}`;
  $('#hashHuntStreak').textContent=`${state.streak}×`;
  $('#hashHuntAttempts').textContent=Number(state.attempts).toLocaleString();
  $('#hashHuntBestStreak').textContent=`${state.bestStreak}×`;
  $('#hashHuntBlocks').textContent=Number(state.blocks).toLocaleString();
  $('#hashHuntTotalShares').textContent=Number(state.totalShares).toLocaleString();

  const progress=Math.max(0,Math.min(100,(state.sharesInBlock/active.requiredShares)*100));
  $('#hashHuntProgressText').textContent=`${Math.round(progress)}%`;
  $('#hashHuntProgressBar').style.width=`${progress}%`;

  const slots=$('#hashHuntSlots');slots.innerHTML='';
  for(let i=0;i<active.requiredShares;i++){
    const item=document.createElement('span');
    item.className=`hash-slot ${state.slots[i]?'filled':''}`;
    item.textContent=state.slots[i]||'----';
    slots.appendChild(item);
  }

  $('#hashHuntConsoleTitle').textContent=state.lastTitle||'Ready for a hash attempt.';
  $('#hashHuntConsoleText').textContent=state.lastMessage||'Press Run Hash Attempt to start the mini-game.';
  $('#hashHuntLastHash').textContent=state.lastHash||'—';

  $('#hashHuntRun').disabled=hashHuntBusy||state.claimReady;
  $('#hashHuntClaim').disabled=hashHuntBusy||!state.claimReady;
  $('#hashHuntClaim').textContent=`₿ Claim Block Bonus +${active.blockXp} XP`;

  const achievementRoot=$('#hashAchievementList');achievementRoot.innerHTML='';
  HASH_HUNT_ACHIEVEMENTS.forEach(item=>{
    const unlocked=state.achievements.includes(item.id);
    const row=document.createElement('div');
    row.className=`miner-achievement ${unlocked?'unlocked':''}`;
    row.innerHTML=`<span class="miner-achievement-icon">${item.icon}</span><div><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.desc)}</small></div><b>${unlocked?'UNLOCKED':`+${item.xp} XP`}</b>`;
    achievementRoot.appendChild(row);
  });
  $('#hashAchievementCount').textContent=`${state.achievements.length} / ${HASH_HUNT_ACHIEVEMENTS.length} unlocked`;

  const unlockRoot=$('#minerUnlockList');unlockRoot.innerHTML='';
  MINER_UNLOCKS.forEach(item=>{
    const unlocked=level>=item.level;
    const row=document.createElement('div');
    row.className=`miner-unlock ${unlocked?'unlocked':''}`;
    row.innerHTML=`<span class="miner-unlock-icon">${item.icon}</span><div><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.desc)}</small></div><b>${unlocked?'ACTIVE':`LEVEL ${item.level}`}</b>`;
    unlockRoot.appendChild(row);
  });
}

async function runHashHuntAttempt(){
  if(hashHuntBusy||hashHuntState.claimReady)return;
  hashHuntBusy=true;
  renderHashHunt();

  const beforeLevel=minerLevelFromXp(hashHuntState.xp);
  const difficulty=hashHuntDifficulty();
  $('#hashHuntConsoleTitle').textContent='Hashing simulated work…';
  $('#hashHuntConsoleText').textContent='Running one local double-SHA256 mini-game attempt.';
  $('#hashHuntLastHash').textContent='…';

  try{
    const hex=await hashHuntDoubleSha256();
    const firstByte=parseInt(hex.slice(0,2),16);
    const valid=firstByte<difficulty.targetByte;

    hashHuntState.attempts+=1;
    awardHashXp(difficulty.attemptXp);
    hashHuntState.lastHash=hex;
    hashHuntState.lastValid=valid;

    let earned=difficulty.attemptXp;
    let unlocked=[];

    if(valid){
      hashHuntState.totalShares+=1;
      hashHuntState.streak+=1;
      hashHuntState.bestStreak=Math.max(hashHuntState.bestStreak,hashHuntState.streak);
      hashHuntState.sharesInBlock=Math.min(
        difficulty.requiredShares,
        hashHuntState.sharesInBlock+1
      );
      hashHuntState.slots.push(hex.slice(0,4).toUpperCase());

      const streakBonus=Math.min(20,Math.max(0,hashHuntState.streak-1)*2);
      const shareEarn=difficulty.shareXp+streakBonus;
      awardHashXp(shareEarn);
      earned+=shareEarn;

      if(hashHuntState.difficulty==='dragon' && unlockHashAchievement('dragon-share')){
        unlocked.push('Purple Dragon Share');
      }

      if(hashHuntState.sharesInBlock>=difficulty.requiredShares){
        hashHuntState.claimReady=true;
        hashHuntState.lastTitle='Mini-game block meter complete!';
        hashHuntState.lastMessage=`Valid share found. +${earned} XP. Claim the +${difficulty.blockXp} XP cosmetic block bonus to start the next meter.`;
      }else{
        hashHuntState.lastTitle=`Valid mini-game share! ${hashHuntState.streak}× streak`;
        hashHuntState.lastMessage=`Hash ${hex.slice(0,12).toUpperCase()}… passed the ${difficulty.label} mini-game target. +${earned} XP.`;
      }
    }else{
      hashHuntState.streak=0;
      hashHuntState.lastTitle='No mini-game share this round.';
      hashHuntState.lastMessage=`Hash ${hex.slice(0,12).toUpperCase()}… missed the ${difficulty.label} mini-game target. +${earned} attempt XP.`;
    }

    unlocked.push(...checkHashAchievements());
    const afterLevel=minerLevelFromXp(hashHuntState.xp);
    if(afterLevel>beforeLevel){
      hashHuntState.lastMessage+=` Miner Rank advanced to Level ${afterLevel}: ${minerRankTitle(afterLevel)}.`;
      showToast(`Miner Rank Level ${afterLevel} unlocked`);
    }else if(unlocked.length){
      showToast(`Achievement unlocked: ${unlocked.join(', ')}`);
    }

    saveHashHuntState();
  }finally{
    hashHuntBusy=false;
    renderHashHunt();
  }
}

function claimHashHuntBlock(){
  if(hashHuntBusy||!hashHuntState.claimReady)return;
  const beforeLevel=minerLevelFromXp(hashHuntState.xp);
  const difficulty=hashHuntDifficulty();
  awardHashXp(difficulty.blockXp);
  hashHuntState.blocks+=1;
  hashHuntState.sharesInBlock=0;
  hashHuntState.slots=[];
  hashHuntState.claimReady=false;
  hashHuntState.streak=0;
  const unlocked=checkHashAchievements();
  const afterLevel=minerLevelFromXp(hashHuntState.xp);
  hashHuntState.lastTitle='Cosmetic block bonus claimed.';
  hashHuntState.lastMessage=`+${difficulty.blockXp} Miner XP awarded. A fresh ${difficulty.label} block meter is ready.`;
  if(afterLevel>beforeLevel)hashHuntState.lastMessage+=` Miner Rank advanced to Level ${afterLevel}: ${minerRankTitle(afterLevel)}.`;
  saveHashHuntState();
  renderHashHunt();
  showToast(unlocked.length?`Block claimed · ${unlocked.join(', ')} unlocked`:`Block bonus +${difficulty.blockXp} XP`);
}

function resetHashHunt(){
  if(!confirm('Reset all local Miner XP, achievements, Hash Hunt stats, and cosmetic unlock progress?'))return;
  hashHuntState=defaultHashHuntState();
  saveHashHuntState();
  renderHashHunt();
  showToast('Miner XP progress reset');
}

function changeHashHuntDifficulty(value){
  const next=HASH_HUNT_DIFFICULTIES[value];
  if(!next)return;
  const level=minerLevelFromXp(hashHuntState.xp);
  if(level<next.unlockLevel){
    showToast(`Purple Dragon difficulty unlocks at Level ${next.unlockLevel}`);
    renderHashHunt();
    return;
  }
  if(value===hashHuntState.difficulty)return;

  if(hashHuntState.sharesInBlock>0||hashHuntState.claimReady){
    const ok=confirm('Changing Hash Hunt difficulty resets only the current mini-game block meter. Miner XP, achievements, attempts, and claimed blocks are kept.');
    if(!ok){renderHashHunt();return}
  }
  hashHuntState.difficulty=value;
  hashHuntState.sharesInBlock=0;
  hashHuntState.slots=[];
  hashHuntState.claimReady=false;
  hashHuntState.streak=0;
  hashHuntState.lastTitle=`${next.label} difficulty selected.`;
  hashHuntState.lastMessage='Current mini-game block meter was reset. Real mining remains unaffected.';
  saveHashHuntState();
  renderHashHunt();
}




/* --------------------------------------------------------------------------
   v1.7.0 — Mining Academy
   Local curriculum + deterministic educational labs. No live mining controls.
   -------------------------------------------------------------------------- */
function academyStatusLabel(value){return String(value||'not_started').replaceAll('_',' ').toUpperCase()}
function academyLessonById(id){return (miningAcademyState?.catalog||[]).find(x=>x.id===id)||null}
function academyQuizPassed(id){return !!miningAcademyState?.quizzes?.[id]?.passed}
function academyFilterMatches(lesson){return academyFilter==='all'||String(lesson.level||'')===academyFilter}
function academySelectLesson(id,{scroll=false}={}){
  const lesson=academyLessonById(id);if(!lesson)return;
  academyCurrentLessonId=lesson.id;pendingAcademyLesson='';
  const status=miningAcademyState?.lesson_status?.[lesson.id]||'not_started';
  if($('#academyLessonTrack'))$('#academyLessonTrack').textContent=`${String(lesson.track||'ACADEMY').toUpperCase()} · ${String(lesson.level||'').toUpperCase()}`;
  if($('#academyLessonTitle'))$('#academyLessonTitle').textContent=lesson.title||'Mining Academy';
  if($('#academyLessonSummary'))$('#academyLessonSummary').textContent=lesson.summary||'';
  if($('#academyLessonStatus')){$('#academyLessonStatus').textContent=academyStatusLabel(status);$('#academyLessonStatus').dataset.status=status}
  const objectives=$('#academyObjectives');if(objectives)objectives.innerHTML=(lesson.objectives||[]).map(x=>`<div><span>✓</span><p>${escapeHtml(x)}</p></div>`).join('');
  const sections=$('#academySections');if(sections)sections.innerHTML=(lesson.sections||[]).map(x=>`<section><h3>${escapeHtml(x.heading||'')}</h3><p>${escapeHtml(x.text||'')}</p></section>`).join('');
  const q=lesson.quiz||{};if($('#academyQuizQuestion'))$('#academyQuizQuestion').textContent=q.question||'No quiz available.';
  const choices=$('#academyQuizChoices');if(choices)choices.innerHTML=(q.choices||[]).map((choice,index)=>`<button type="button" data-academy-answer="${index}"><span>${String.fromCharCode(65+index)}</span><strong>${escapeHtml(choice)}</strong></button>`).join('');
  const prior=miningAcademyState?.quizzes?.[lesson.id];
  if($('#academyQuizState'))$('#academyQuizState').textContent=prior?.passed?`PASSED · ${prior.attempts||1} attempt${Number(prior.attempts||1)===1?'':'s'}`:(prior?`${prior.attempts||0} attempt${Number(prior.attempts||0)===1?'':'s'}`:'Not attempted');
  if($('#academyQuizResult'))$('#academyQuizResult').textContent=prior?.passed?'Knowledge check passed. You can still retry it.':'Select one answer. You can retry immediately.';
  if($('#academyStartLesson'))$('#academyStartLesson').disabled=!apiReady||status==='completed';
  if($('#academyCompleteLesson'))$('#academyCompleteLesson').disabled=!apiReady||status==='completed';
  $$('.academy-lesson-item').forEach(x=>x.classList.toggle('active',x.dataset.lessonId===lesson.id));
  if(scroll)$('#view-academy')?.scrollIntoView({behavior:'smooth',block:'start'});
}
function renderAcademyLessonList(){
  const root=$('#academyLessonList');if(!root||!miningAcademyState)return;
  const rows=(miningAcademyState.catalog||[]).filter(academyFilterMatches);
  root.innerHTML=rows.length?rows.map(lesson=>{const status=miningAcademyState.lesson_status?.[lesson.id]||'not_started';const passed=academyQuizPassed(lesson.id);return`<button class="academy-lesson-item ${lesson.id===academyCurrentLessonId?'active':''}" data-lesson-id="${escapeHtml(lesson.id)}"><span class="academy-lesson-index">${String((miningAcademyState.catalog||[]).indexOf(lesson)+1).padStart(2,'0')}</span><div><small>${escapeHtml(lesson.level||'')} · ${escapeHtml(lesson.track||'')}</small><strong>${escapeHtml(lesson.title||'')}</strong><em>${academyStatusLabel(status)}${passed?' · QUIZ ✓':''}</em></div></button>`}).join(''):'<div class="empty-state">No lessons match this filter.</div>';
  if($('#academyCatalogMeta'))$('#academyCatalogMeta').textContent=`${rows.length} lesson${rows.length===1?'':'s'}`;
}
function renderMiningAcademy(state){
  if(!state)return;miningAcademyState=state;
  const percent=Math.max(0,Math.min(100,Number(state.progress_percent||0)));
  if($('#academyRank'))$('#academyRank').textContent=String(state.rank||'New Miner').toUpperCase();
  if($('#academyHeroText'))$('#academyHeroText').textContent=state.next_rank?`${state.points||0} XP · next rank: ${state.next_rank.rank} at ${state.next_rank.points} XP`:`${state.points||0} XP · highest Academy rank achieved`;
  if($('#academyProgressBar'))$('#academyProgressBar').style.width=`${percent}%`;
  if($('#academyProgressText'))$('#academyProgressText').textContent=`${percent.toFixed(0)}%`;
  if($('#academyLessonsKpi'))$('#academyLessonsKpi').textContent=`${state.completed_lessons||0} / ${state.total_lessons||0}`;
  if($('#academyLabsKpi'))$('#academyLabsKpi').textContent=`${state.completed_labs||0} / ${state.total_labs||0}`;
  if($('#academyQuizKpi'))$('#academyQuizKpi').textContent=`${state.passed_quizzes||0} / ${state.total_quizzes||0}`;
  if($('#academyPointsKpi'))$('#academyPointsKpi').textContent=Number(state.points||0).toLocaleString();
  const target=pendingAcademyLesson||academyCurrentLessonId||state.last_lesson||(state.catalog?.[0]?.id);
  if(!academyLessonById(target))academyCurrentLessonId=state.last_lesson||state.catalog?.[0]?.id||'fundamentals';else academyCurrentLessonId=target;
  renderAcademyLessonList();academySelectLesson(academyCurrentLessonId);
  $$('.academy-lab-card').forEach(card=>{const map={academyHashLab:'hash',academyDifficultyLab:'difficulty',academyHeaderLab:'header',academyMerkleLab:'merkle',academyNonceLab:'nonce'};const id=map[card.id];card.classList.toggle('complete',!!id&&(state.labs_completed||[]).includes(id))});
}
async function refreshMiningAcademy(show=false){
  if(!apiReady||!bridgeAvailable('get_mining_academy_state'))return;
  try{const r=await callApi('get_mining_academy_state');if(!r?.ok)throw new Error(r?.error||'Could not load Mining Academy');renderMiningAcademy(r.academy);if(show)showToast('Mining Academy refreshed')}catch(e){console.error('Mining Academy:',e);if(show)showToast(e.message)}
}
async function academySetStatus(status){
  const box=$('#academyResult');try{const r=await callApi('set_academy_lesson_status',academyCurrentLessonId,status);if(!r?.ok)throw new Error(r?.error||'Could not save lesson progress');renderMiningAcademy(r.academy);if(box)box.textContent=r.result||'Academy progress saved.';showToast(status==='completed'?'Lesson completed':'Lesson marked in progress')}catch(e){if(box)box.textContent=`ERROR: ${e.message}`;showToast(e.message)}
}
function academyHeaderPayload(){return{version:Number($('#academyHeaderVersion')?.value||1),previousblockhash:$('#academyHeaderPrev')?.value.trim()||'',merkleroot:$('#academyHeaderMerkle')?.value.trim()||'',time:Number($('#academyHeaderTime')?.value||0),bits:$('#academyHeaderBits')?.value.trim()||'0x1d00ffff',nonce:Number($('#academyHeaderNonce')?.value||0)}}

function renderTrayState(state){
  if(!state)return;trayState=state;
  const settings=state.settings||{};const status=state.status||{};
  if($('#trayEnabled'))$('#trayEnabled').value=settings.tray_enabled===false?'off':'on';
  if($('#trayMinimize'))$('#trayMinimize').value=settings.tray_minimize_to_tray===false?'off':'on';
  if($('#trayClose'))$('#trayClose').value=settings.tray_close_to_tray?'on':'off';
  if($('#trayNotifications'))$('#trayNotifications').value=settings.tray_notifications_enabled===false?'off':'on';
  if($('#trayPollSeconds'))$('#trayPollSeconds').value=String(settings.tray_poll_seconds||10);
  const supported=!!state.supported,running=!!state.running;
  if($('#trayHeroTitle'))$('#trayHeroTitle').textContent=!supported?'WINDOWS TRAY UNAVAILABLE':(running?'TRAY MONITOR ACTIVE':(settings.tray_enabled===false?'TRAY DISABLED':'TRAY STARTING'));
  if($('#trayHeroDetail'))$('#trayHeroDetail').textContent=state.error||(!supported?'This feature requires Windows.':(running?'Local monitoring remains active when the Miner Studio window is hidden.':'The tray icon will start when the Windows window is shown.'));
  if($('#trayRunningState'))$('#trayRunningState').textContent=!supported?'N/A':(running?'RUNNING':(settings.tray_enabled===false?'DISABLED':'STOPPED'));
  if($('#trayWindowState'))$('#trayWindowState').textContent=state.hidden?'HIDDEN':'VISIBLE';
  if($('#trayNotificationState'))$('#trayNotificationState').textContent=settings.tray_notifications_enabled===false?'OFF':'ON';
  if($('#trayHealthState'))$('#trayHealthState').textContent=String(status.severity||'ok').toUpperCase();
  const orb=$('#trayStatusOrb');if(orb)orb.dataset.level=status.severity||'ok';
  if($('#trayStatusSummary'))$('#trayStatusSummary').textContent=status.summary||'Status unavailable';
  if($('#trayStatusDetail'))$('#trayStatusDetail').textContent=status.detail||'Local monitoring status unavailable.';
  if($('#trayPoolStatus'))$('#trayPoolStatus').textContent=status.pool_running?`Health ${Number(status.pool_health||0).toFixed(0)}%`:'Idle';
  if($('#trayCoreStatus'))$('#trayCoreStatus').textContent=status.core_connected?`Online${status.core_height?` · ${Number(status.core_height).toLocaleString()}`:''}`:'Offline';
  if($('#trayAsicStatus'))$('#trayAsicStatus').textContent=status.asic_total?`${status.asic_online||0}/${status.asic_total} online`:'None';
  if($('#traySecurityStatus'))$('#traySecurityStatus').textContent=status.security_checked?(status.security_verified?'TRUSTED':'LOCKED'):'Checking';
  if($('#trayLastNotification'))$('#trayLastNotification').textContent=state.last_notification_at?new Date(Number(state.last_notification_at)*1000).toLocaleTimeString():'None';
  const hide=$('#trayHideNow');if(hide)hide.disabled=!supported||!running;
  const test=$('#trayTestNotification');if(test)test.disabled=!supported||!running||settings.tray_notifications_enabled===false;
}
async function refreshTrayState(show=false){
  if(!bridgeAvailable('get_tray_state'))return;
  try{const r=await callApi('get_tray_state');if(!r?.ok)throw new Error(r?.error||'Could not read tray state');renderTrayState(r.tray);if(show)showToast('Windows tray status refreshed')}catch(e){if(show)showToast(e.message||String(e))}
}
function traySettingsPayload(){return{
  tray_enabled:$('#trayEnabled')?.value!=='off',
  tray_minimize_to_tray:$('#trayMinimize')?.value!=='off',
  tray_close_to_tray:$('#trayClose')?.value==='on',
  tray_notifications_enabled:$('#trayNotifications')?.value!=='off',
  tray_poll_seconds:Number($('#trayPollSeconds')?.value||10)
}}

async function waitForBridge(method,timeoutMs=15000){
  const started=Date.now();
  while(Date.now()-started<timeoutMs){
    const api=window.pywebview?.api;
    if(api && typeof api[method]==='function')return api;
    await new Promise(resolve=>setTimeout(resolve,150));
  }
  return null;
}

async function callApi(method,...args){
  let api=window.pywebview?.api;
  if(!api || typeof api[method]!=='function'){
    setBridgeUiState(false);
    scheduleBridgeRetry();
    api=await waitForBridge(method,15000);
    if(!api)throw new Error('Bitcoin Miner Studio backend connection timed out. The UI will keep retrying automatically.');
    setBridgeUiState(true);
  }
  return await api[method](...args);
}
function applyPoolConfigToForm(c,passwordValue){
  c=c||{};
  const backups=Array.isArray(c.pool_backup_urls)?c.pool_backup_urls:[];
  if(c.pool_url!==undefined)$('#poolUrl').value=c.pool_url||'';
  $('#poolBackup1').value=backups[0]||'';
  $('#poolBackup2').value=backups[1]||'';
  $('#poolBackup3').value=backups[2]||'';
  if(c.pool_worker!==undefined)$('#poolWorker').value=c.pool_worker||'';
  if(c.pool_failover_enabled!==undefined)$('#poolFailoverEnabled').checked=!!c.pool_failover_enabled;
  if(c.pool_failover_policy!==undefined&&$('#poolFailoverPolicy'))$('#poolFailoverPolicy').value=c.pool_failover_policy||'balanced';
  if(c.pool_primary_recovery_seconds!==undefined&&$('#poolPrimaryRecovery'))$('#poolPrimaryRecovery').value=Number(c.pool_primary_recovery_seconds||0);
  if(c.pool_job_timeout_seconds!==undefined)$('#poolJobTimeout').value=c.pool_job_timeout_seconds||120;
  if(c.mining_processes!==undefined)$('#miningProcesses').value=c.mining_processes||2;
  if(c.suggest_difficulty_enabled!==undefined)$('#suggestEnabled').checked=!!c.suggest_difficulty_enabled;
  if(c.suggest_difficulty!==undefined)$('#suggestDifficulty').value=c.suggest_difficulty||1;
  if(passwordValue!==undefined)$('#poolPassword').value=passwordValue||'';
  syncFailoverPolicyUi();
}
function poolPayload(){return {pool_url:$('#poolUrl').value.trim(),pool_backup_urls:[$('#poolBackup1').value.trim(),$('#poolBackup2').value.trim(),$('#poolBackup3').value.trim()].filter(Boolean),pool_failover_enabled:$('#poolFailoverEnabled').checked,pool_failover_policy:$('#poolFailoverPolicy')?.value||'balanced',pool_primary_recovery_seconds:Number($('#poolPrimaryRecovery')?.value||0),pool_job_timeout_seconds:Number($('#poolJobTimeout').value||120),pool_worker:$('#poolWorker').value.trim(),pool_password:$('#poolPassword').value,mining_processes:Number($('#miningProcesses').value||2),suggest_difficulty_enabled:$('#suggestEnabled').checked,suggest_difficulty:Number($('#suggestDifficulty').value||1)}}
function corePayload(){return {rpc_url:$('#rpcUrl').value.trim(),rpc_user:$('#rpcUser').value.trim(),rpc_password:$('#rpcPassword').value,core_auth_mode:$('#coreAuthMode').value,core_executable:$('#coreExecutable').value.trim(),core_data_dir:$('#coreDataDir').value.trim(),core_cookie_path:$('#coreCookiePath').value.trim(),core_network:$('#coreNetwork').value,core_auto_refresh:$('#coreAutoRefresh').checked,core_refresh_seconds:Number($('#coreRefreshSeconds').value||10),template_auto_refresh:$('#templateAutoRefresh').checked,template_refresh_seconds:Number($('#templateRefreshSeconds').value||15)}}
function coinbasePayload(){return {coinbase_payout_address:$('#coinbaseAddress').value.trim(),coinbase_tag:$('#coinbaseTag').value,coinbase_extranonce_size:Number($('#coinbaseExtranonce').value||8)}}
function soloPayload(){return {...coinbasePayload(),solo_batch_size:Number($('#soloBatchSize').value||20000),solo_extranonce_roll_hashes:Number($('#soloRollHashes').value||2000000),solo_auto_new_template:$('#soloAutoTemplate').checked}}
async function handleResult(promise, success){try{const r=await promise;if(!r?.ok)throw new Error(r?.error||'Action failed');if(success)showToast(success);return r}catch(e){showToast(e.message||String(e));throw e}}

function initFields(b){
  bootstrap=b; const c=b.config;
  $('#sideVersion').textContent=`v${b.version} · Architecture v2`;
  applyUiTheme(c.ui_theme||currentUiTheme);
  applyPoolConfigToForm(c);
  $('#poolPassword').placeholder=c.pool_password_stored?'Stored credential — leave blank to keep':'Password / x';
  $('#rpcUrl').value=c.rpc_url||''; $('#rpcUser').value=c.rpc_user||''; $('#coreAuthMode').value=c.core_auth_mode||'password'; $('#coreExecutable').value=c.core_executable||''; $('#coreDataDir').value=c.core_data_dir||''; $('#coreCookiePath').value=c.core_cookie_path||''; $('#coreNetwork').value=c.core_network||'main'; $('#rpcPassword').placeholder=c.rpc_password_stored?'Stored credential — leave blank to keep':'RPC password'; $('#coreAutoRefresh').checked=c.core_auto_refresh!==false; $('#coreRefreshSeconds').value=c.core_refresh_seconds||10; $('#templateAutoRefresh').checked=c.template_auto_refresh!==false; $('#templateRefreshSeconds').value=c.template_refresh_seconds||15;
 $('#coinbaseAddress').value=c.coinbase_payout_address||''; $('#coinbaseTag').value=c.coinbase_tag||'Bitcoin Miner Studio / Purple Dragon Foundation ltd'; $('#coinbaseExtranonce').value=c.coinbase_extranonce_size||8; $('#coinbaseNetwork').value=c.core_network||'main'; $('#soloBatchSize').value=c.solo_batch_size||20000; $('#soloRollHashes').value=c.solo_extranonce_roll_hashes||2000000; $('#soloAutoTemplate').checked=c.solo_auto_new_template!==false; applyPerformancePlus(c.performance_plus_enabled===true); if($('#analyticsEnabled')){$('#analyticsEnabled').value=c.analytics_enabled===false?'off':'on';$('#analyticsSampleSeconds').value=String(c.analytics_sample_seconds||10);$('#analyticsRetentionDays').value=String(c.analytics_retention_days||30)} if($('#trayEnabled')){$('#trayEnabled').value=c.tray_enabled===false?'off':'on';$('#trayMinimize').value=c.tray_minimize_to_tray===false?'off':'on';$('#trayClose').value=c.tray_close_to_tray?'on':'off';$('#trayNotifications').value=c.tray_notifications_enabled===false?'off':'on';$('#trayPollSeconds').value=String(c.tray_poll_seconds||10)} syncCoreAuthFields();
  $('#asicCidr').value=c.asic_subnet||''; $('#asicSoloBindIp').value=c.asic_solo_bind_ip||''; $('#asicSoloPort').value=c.asic_solo_port||3333; $('#asicSoloDifficulty').value=c.asic_solo_share_difficulty||65536;
  if($('#benchmarkWorkers'))$('#benchmarkWorkers').value=String(c.benchmark_processes||2);
  if($('#benchmarkDuration'))$('#benchmarkDuration').value=String(c.benchmark_duration_seconds||30);
  if($('#benchmarkScalingSeconds'))$('#benchmarkScalingSeconds').value=String(c.benchmark_scaling_seconds||8);
  const credentialBackend=$('#credentialBackend'); if(credentialBackend)credentialBackend.textContent=b.credential_backend||'Credential storage';
  if(b.architecture)renderArchitecture(b.architecture,b.workspace||null);
  applyWorkspaceState(b.workspace||workspaceState||{last_view:'dashboard',recent_views:['dashboard'],sidebar_compact:false,command_usage:{}},{restoreView:true});
}

function formatBytes(v){v=Number(v||0);if(v<1024)return`${v} B`;if(v<1048576)return`${(v/1024).toFixed(1)} KB`;if(v<1073741824)return`${(v/1048576).toFixed(1)} MB`;return`${(v/1073741824).toFixed(2)} GB`}
function formatAnalyticsTime(ts){if(!ts)return'—';try{return new Date(Number(ts)*1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'})}catch{return'—'}}
function drawNormalizedSeries(canvas,series){
  if(!canvas)return;
  const {ctx,width,height}=fitCanvas(canvas);ctx.clearRect(0,0,width,height);ctx.fillStyle=`rgba(${cssRgb('--deep-surface-rgb','7,6,11')},.42)`;ctx.fillRect(0,0,width,height);
  ctx.strokeStyle=`rgba(${cssRgb('--accent-light-rgb','211,165,255')},.065)`;ctx.lineWidth=1;for(let i=1;i<5;i++){const y=i*height/5;ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(width,y);ctx.stroke()}
  (series||[]).forEach(item=>{const values=(item.values||[]).map(Number);if(values.length<2)return;const max=Math.max(...values,1),min=Math.min(...values,0),span=Math.max(1e-12,max-min);ctx.beginPath();values.forEach((v,i)=>{const x=i/(values.length-1)*width;const y=height-12-((v-min)/span)*(height-24);i?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.strokeStyle=item.color;ctx.lineWidth=item.width||2;ctx.globalAlpha=item.alpha||1;ctx.stroke();ctx.globalAlpha=1});
}
function renderAnalyticsStatus(status){
  status=status||{};const running=!!status.running;const dot=$('#monitorRecorderDot');if(dot)dot.className=`monitor-dot ${running?'active':''}`;
  if($('#monitorRecorderState'))$('#monitorRecorderState').textContent=running?'Recording':'Paused';
  if($('#monitorRecorderDetail'))$('#monitorRecorderDetail').textContent=status.error?`Recorder error: ${status.error}`:`${status.sample_seconds||10}s sampling · ${status.retention_days||30} day retention · local SQLite`;
  if($('#monitorLastSample'))$('#monitorLastSample').textContent=formatAnalyticsTime(status.last_sample);
  if($('#monitorDbSize'))$('#monitorDbSize').textContent=formatBytes(status.database_size);
}
function renderAnalytics(data){
  if(!data?.ok)return;lastAnalytics=data;analyticsLastFetch=Date.now();renderAnalyticsStatus(data.status||{});const a=data.summary||{},series=data.series||[];
  $('#monitorSampleCount').textContent=Number(a.sample_count||0).toLocaleString();$('#monitorLastSample').textContent=formatAnalyticsTime(a.last_sample||data.status?.last_sample);
  $('#monPoolAvg').textContent=a.pool_avg_hashrate?formatHashrate(a.pool_avg_hashrate):'—';$('#monPoolPeak').textContent=`Peak ${a.pool_peak_hashrate?formatHashrate(a.pool_peak_hashrate):'—'}`;
  $('#monPoolAcceptance').textContent=(a.pool_acceptance||0)?`${Number(a.pool_acceptance).toFixed(2)}%`:'—';$('#monPoolShares').textContent=`${Number(a.pool_accepted_delta||0).toLocaleString()} accepted · ${Number(a.pool_rejected_delta||0).toLocaleString()} rejected · ${Number(a.pool_stale_delta||0).toLocaleString()} stale`;
  $('#monPoolLatency').textContent=a.pool_share_p95_ms?`${Number(a.pool_share_p95_ms).toFixed(1)} ms`:'—';$('#monPoolHealth').textContent=`Health ${a.pool_health_avg?Number(a.pool_health_avg).toFixed(0):'—'}/100`;
  $('#monSoloAvg').textContent=a.solo_avg_hashrate?formatHashrate(a.solo_avg_hashrate):'—';$('#monSoloPeak').textContent=`Peak ${a.solo_peak_hashrate?formatHashrate(a.solo_peak_hashrate):'—'}`;$('#monSoloBest').textContent=a.solo_best_difficulty?formatShareDifficulty(a.solo_best_difficulty):'—';
  $('#monCoreAvailability').textContent=series.length?`${Number(a.core_availability||0).toFixed(1)}%`:'—';$('#monCoreLatency').textContent=`RPC p95 ${a.core_rpc_p95_ms?`${Number(a.core_rpc_p95_ms).toFixed(1)} ms`:'—'}`;
  $('#monAsicHashrate').textContent=a.asic_avg_hashrate?formatHashrate(a.asic_avg_hashrate):'—';$('#monAsicHealth').textContent=`Health ${a.asic_avg_health?Number(a.asic_avg_health).toFixed(0):'—'}/100`;$('#monAsicTemp').textContent=a.asic_max_temp?`${Number(a.asic_max_temp).toFixed(1)} °C`:'—';
  requestAnimationFrame(()=>{
    drawNormalizedSeries($('#monitorHashrateChart'),[{values:series.map(x=>x.pool_hashrate||0),color:cssVar('--accent','#9654FF')},{values:series.map(x=>x.solo_hashrate||0),color:cssVar('--accent-light','#D3A5FF')}]);
    drawNormalizedSeries($('#monitorLatencyChart'),[{values:series.map(x=>x.pool_share_p95_ms||0),color:cssVar('--accent-soft','#B678FF')},{values:series.map(x=>x.core_rpc_latency_ms||0),color:cssVar('--accent-mid','#6425A8')},{values:series.map(x=>x.pool_health||0),color:cssVar('--text','#FAF7FF'),alpha:.75}]);
    drawNormalizedSeries($('#monitorAsicChart'),[{values:series.map(x=>x.asic_hashrate||0),color:cssVar('--accent','#9654FF')},{values:series.map(x=>x.asic_max_temp||0),color:cssVar('--accent-light','#D3A5FF')},{values:series.map(x=>x.asic_avg_health||0),color:cssVar('--text','#FAF7FF'),alpha:.75}]);
    drawNormalizedSeries($('#monitorCoreChart'),[{values:series.map(x=>x.core_rpc_latency_ms||0),color:cssVar('--accent-mid','#6425A8')},{values:series.map(x=>x.core_peers||0),color:cssVar('--accent-soft','#B678FF')}]);
  });
  const root=$('#monitorEventList');root.innerHTML='';(data.events||[]).forEach(e=>{const row=document.createElement('div');row.className=`monitor-event ${escapeHtml(e.severity||'info')}`;row.innerHTML=`<i></i><div><strong>${escapeHtml(e.source||'System')} · ${escapeHtml(e.kind||'event')}</strong><small>${escapeHtml(e.message||'')}</small></div><time>${formatAnalyticsTime(e.ts)}</time>`;root.appendChild(row)});if(!root.children.length)root.innerHTML='<div class="empty-state">No operational threshold events in this range.</div>';
}
async function refreshAnalytics(force=false){
  if(!apiReady||analyticsInFlight||!bridgeAvailable('get_analytics_dashboard'))return;if(!force&&Date.now()-analyticsLastFetch<4500)return;analyticsInFlight=true;
  try{const r=await callApi('get_analytics_dashboard',analyticsRangeSeconds);if(r?.ok)renderAnalytics(r);else if(r?.error)$('#analyticsResult').textContent=`ERROR: ${r.error}`}
  catch(e){console.error('Analytics refresh:',e)}finally{analyticsInFlight=false}
}

function releaseAreaState(checks,area){
  const rows=(checks||[]).filter(x=>String(x.area||'')===area);
  if(!rows.length)return{label:'—',cls:''};
  if(rows.some(x=>x.status==='fail'))return{label:'BLOCKED',cls:'fail'};
  if(rows.some(x=>x.status==='warn'))return{label:'REVIEW',cls:'warn'};
  return{label:'PASS',cls:'pass'};
}
function renderReleaseCandidate(rc){
  rc=rc||{};
  const score=Number(rc.score||0);
  const checked=!!rc.checked;
  const blockers=Number(rc.blockers||0);
  const warnings=Number(rc.warnings||0);
  const readiness=checked?(rc.readiness||'NOT CHECKED'):(rc.running?'CHECKING':'NOT CHECKED');

  $('#rcReadiness').textContent=readiness;
  $('#rcScore').textContent=checked?String(score):'—';
  $('#rcScoreRing').style.setProperty('--score',checked?score:0);
  $('#rcBlockers').textContent=blockers.toLocaleString();
  $('#rcWarnings').textContent=warnings.toLocaleString();
  $('#rcCheckedAt').textContent=rc.checked_at?`Checked ${rc.checked_at}`:'Not checked';
  $('#rcSupportPath').textContent=rc.support_bundle||'—';

  const orb=$('#rcReadinessOrb');
  orb.className=`rc-orb ${blockers?'blocked':(checked?'ready':'')}`;
  $('#rcReadinessDetail').textContent=!checked
    ?'Waiting for the initial Stable release preflight.'
    :blockers
      ?`${blockers} blocking release gate(s) must be fixed before distribution.`
      :warnings
        ?`No blockers. Review ${warnings} warning(s) before promoting this build.`
        :'All current Stable release gates passed.';

  const areas={
    rcRuntimeState:'Runtime',
    rcSecurityState:'Security',
    rcStartupState:'Startup',
    rcConfigState:'Configuration',
    rcStorageState:'Storage',
    rcMonitoringState:'Monitoring',
  };
  Object.entries(areas).forEach(([id,area])=>{
    const state=releaseAreaState(rc.checks||[],area);
    const el=$(`#${id}`);el.textContent=state.label;el.className=state.cls;
  });

  const table=$('#rcChecksTable');table.innerHTML='';
  (rc.checks||[]).forEach(row=>{
    const tr=document.createElement('tr');
    const state=String(row.status||'info').toLowerCase();
    tr.innerHTML=`<td><span class="rc-state ${escapeHtml(state)}">${escapeHtml(state.toUpperCase())}</span></td><td>${escapeHtml(row.area||'—')}</td><td>${escapeHtml(row.title||row.code||'—')}</td><td>${escapeHtml(row.detail||'')}</td>`;
    table.appendChild(tr);
  });
  if(!table.children.length)table.innerHTML='<tr><td colspan="4" class="empty-state">Stable release preflight has not run yet.</td></tr>';
}
async function refreshReleaseCandidate(){
  if(!apiReady||!bridgeAvailable('get_release_candidate_state'))return;
  try{
    const r=await callApi('get_release_candidate_state');
    if(r?.release_candidate)renderReleaseCandidate(r.release_candidate);
  }catch(e){console.error('RC readiness refresh:',e)}
}

/* v1.9.0 — Update & Release Center */
function renderUpdateReleaseCenter(state,security){
  state=state||{};security=security||lastState?.security||{};
  const current=state.current||{},inspection=state.inspection||{},trust=inspection.trust||{},staged=state.staged||{};
  if($('#urCurrentVersion'))$('#urCurrentVersion').textContent=current.version||state.version||'2.0.2';
  if($('#urCurrentBuild'))$('#urCurrentBuild').textContent=current.build_id||'—';
  if($('#urCurrentChannel'))$('#urCurrentChannel').textContent=String(current.channel||'Stable').toUpperCase();
  if($('#urCurrentProtected'))$('#urCurrentProtected').textContent=current.protected_files?String(current.protected_files):'—';
  if($('#urCurrentTrust')){
    const trusted=!!security.verified&&!!security.signature_valid;
    $('#urCurrentTrust').textContent=trusted?'TRUSTED':(security.checked?'LOCKED':'CHECKING');
    $('#urCurrentTrust').dataset.state=trusted?'ready':(security.checked?'blocked':'review');
  }
  if($('#urChannel'))$('#urChannel').value=String(state.channel||'stable').toLowerCase();
  if(inspection.source&&$('#urPackagePath')&&!$('#urPackagePath').matches(':focus'))$('#urPackagePath').value=inspection.source;
  const recommendation=inspection.recommendation||'NOT INSPECTED';
  if($('#urInspectionState')){
    $('#urInspectionState').textContent=recommendation;
    $('#urInspectionState').dataset.state=inspection.ok?(inspection.relation==='OLDER'?'review':'ready'):(inspection.inspected_at?'blocked':'');
  }
  if($('#urCandidateVersion'))$('#urCandidateVersion').textContent=trust.version||'—';
  if($('#urCandidateRelation'))$('#urCandidateRelation').textContent=inspection.relation||'—';
  if($('#urCandidateTrust'))$('#urCandidateTrust').textContent=trust.signature_valid?'VALID':(inspection.inspected_at?'INVALID':'—');
  if($('#urCandidateFiles'))$('#urCandidateFiles').textContent=trust.files_total?`${Number(trust.files_verified||0)} / ${Number(trust.files_total||0)}`:'—';
  if($('#urCandidateSha'))$('#urCandidateSha').textContent=inspection.package_sha256||'—';
  if($('#urCandidateDetail'))$('#urCandidateDetail').textContent=inspection.detail||'Select a complete release package or extracted release folder to inspect it without executing candidate code.';
  if($('#urStage'))$('#urStage').disabled=!(inspection.ok&&trust.trusted&&inspection.channel_compatible!==false);
  if($('#urStagedName'))$('#urStagedName').textContent=staged.present?(staged.name||'STAGED'):'NONE';
  if($('#urStagedPath'))$('#urStagedPath').textContent=staged.present?(staged.path||'—'):'—';
  const history=$('#urHistory');
  if(history){
    const rows=Array.isArray(state.history)?state.history:[];
    history.innerHTML=rows.length?rows.slice(0,8).map(row=>`<div class="update-history-row"><span>${row.action==='staged'?'⇧':'×'}</span><div><strong>${escapeHtml(String(row.action||'action').replaceAll('-',' ').toUpperCase())}${row.version?` · v${escapeHtml(row.version)}`:''}</strong><small>${escapeHtml(row.name||row.relation||'Local update action')}</small></div><time>${escapeHtml(row.at||'')}</time></div>`).join(''):'<div class="empty-state">No update staging actions recorded yet.</div>';
  }
}
async function refreshUpdateReleaseCenter(show=false){
  if(!apiReady||!bridgeAvailable('get_update_release_state'))return;
  try{
    const r=await callApi('get_update_release_state');
    if(r?.update_release){renderUpdateReleaseCenter(r.update_release,lastState?.security||{});if(show)showToast('Update & Release Center refreshed')}
  }catch(e){console.error('Update & Release Center refresh:',e)}
}

/* v1.8.0 — Diagnostics & Support Center */
function diagnosticsHealthDetail(d){
  if(!d?.checked)return 'Run a Quick Scan or Full Diagnostic to inspect the current local environment.';
  if(d.health==='CRITICAL')return 'A critical runtime or trust condition requires attention before critical operations.';
  if(d.health==='DEGRADED')return `${Number(d.failures||0)} failure(s) detected. Review the issue list and recommended next steps.`;
  if(d.health==='ATTENTION')return `${Number(d.warnings||0)} warning(s) detected. The application can continue, but review is recommended.`;
  return 'All evaluated operational checks are healthy. Optional/inactive workflows may appear as informational items.';
}
function renderDiagnosticsCenter(d){
  d=d||{};
  const checked=!!d.checked;
  const health=checked?String(d.health||'NOT CHECKED'):'NOT CHECKED';
  const score=Math.max(0,Math.min(100,Number(d.score||0)));
  const hero=$('#diagnosticsHero');if(hero)hero.dataset.health=health.toLowerCase();
  if($('#diagnosticsHealth'))$('#diagnosticsHealth').textContent=health;
  if($('#diagnosticsHealthIcon'))$('#diagnosticsHealthIcon').textContent=health==='HEALTHY'?'✓':health==='ATTENTION'?'!':health==='DEGRADED'||health==='CRITICAL'?'×':'◇';
  if($('#diagnosticsHealthDetail'))$('#diagnosticsHealthDetail').textContent=diagnosticsHealthDetail(d);
  if($('#diagnosticsScore'))$('#diagnosticsScore').textContent=checked?String(score):'—';
  if($('#diagnosticsScoreRing'))$('#diagnosticsScoreRing').style.setProperty('--score',checked?score:0);
  if($('#diagnosticsMode'))$('#diagnosticsMode').textContent=String(d.mode||'quick').toUpperCase();
  if($('#diagnosticsCheckedAt'))$('#diagnosticsCheckedAt').textContent=d.checked_at?`Checked ${d.checked_at}`:'Not checked';
  if($('#diagnosticsDuration'))$('#diagnosticsDuration').textContent=d.duration_ms?`${Number(d.duration_ms).toLocaleString()} ms`:'—';
  if($('#diagnosticsTotal'))$('#diagnosticsTotal').textContent=Number(d.total_checks||0).toLocaleString();
  if($('#diagnosticsPass'))$('#diagnosticsPass').textContent=Number(d.passes||0).toLocaleString();
  if($('#diagnosticsWarnings'))$('#diagnosticsWarnings').textContent=Number(d.warnings||0).toLocaleString();
  if($('#diagnosticsFailures'))$('#diagnosticsFailures').textContent=Number(d.failures||0).toLocaleString();
  if($('#diagnosticsInfo'))$('#diagnosticsInfo').textContent=Number(d.info||0).toLocaleString();
  if($('#diagnosticsChecksMeta'))$('#diagnosticsChecksMeta').textContent=checked?`${String(d.mode||'quick').toUpperCase()} · ${Number(d.total_checks||0)} checks`:'Waiting for scan';

  const categories=$('#diagnosticsCategories');
  if(categories){
    const rows=Array.isArray(d.categories)?d.categories:[];
    categories.innerHTML=rows.length?rows.map(row=>{
      const state=String(row.state||'INFO').toLowerCase();
      return `<article class="diagnostics-category-card glass"><div><small>${escapeHtml(String(row.category||'Other').toUpperCase())}</small><strong>${Number(row.checks||0)} check${Number(row.checks||0)===1?'':'s'}</strong><p>${Number(row.passes||0)} pass · ${Number(row.warnings||0)} warn · ${Number(row.failures||0)} fail · ${Number(row.info||0)} info</p></div><span class="diagnostics-category-state ${escapeHtml(state)}">${escapeHtml(String(row.state||'INFO'))}</span></article>`;
    }).join(''):'<div class="empty-state glass">No diagnostic result yet.</div>';
  }

  const table=$('#diagnosticsChecksTable');
  if(table){
    const rows=Array.isArray(d.checks)?d.checks:[];
    table.innerHTML=rows.length?rows.map(row=>`<tr><td><span class="diagnostics-state ${escapeHtml(String(row.status||'info'))}">${escapeHtml(String(row.status||'info').toUpperCase())}</span></td><td>${escapeHtml(row.category||'—')}</td><td>${escapeHtml(row.title||row.code||'—')}</td><td>${escapeHtml(row.detail||'')}</td></tr>`).join(''):'<tr><td colspan="4" class="empty-state">Run diagnostics to populate the health matrix.</td></tr>';
  }

  const issues=$('#diagnosticsIssueList');
  const issueRows=Array.isArray(d.issues)?d.issues:[];
  if($('#diagnosticsIssueCount'))$('#diagnosticsIssueCount').textContent=`${issueRows.length} issue${issueRows.length===1?'':'s'}`;
  if(issues){
    issues.innerHTML=issueRows.length?issueRows.map(row=>`<div class="diagnostics-issue" data-status="${escapeHtml(row.status||'warn')}"><div class="diagnostics-issue-head"><strong>${escapeHtml(row.title||row.code||'Issue')}</strong><span>${escapeHtml(String(row.status||'warn').toUpperCase())} · ${escapeHtml(row.category||'')}</span></div><p>${escapeHtml(row.detail||'')}</p>${row.remediation?`<span class="diagnostics-next-step"><b>NEXT STEP</b> · ${escapeHtml(row.remediation)}</span>`:''}</div>`).join(''):'<div class="empty-state">No warning or failure conditions were found in the latest scan.</div>';
  }

  if($('#diagnosticsBundlePath'))$('#diagnosticsBundlePath').textContent=d.last_bundle||'—';
  if($('#diagnosticsBundleSize'))$('#diagnosticsBundleSize').textContent=d.last_bundle_size||'—';
  const sys=d.system||{};
  if($('#diagnosticsSystemVersion'))$('#diagnosticsSystemVersion').textContent=sys.version||'2.0.2';
  if($('#diagnosticsSystemPlatform'))$('#diagnosticsSystemPlatform').textContent=sys.platform||'—';
  if($('#diagnosticsSystemPython'))$('#diagnosticsSystemPython').textContent=sys.python?`${sys.python_implementation||'Python'} ${sys.python}`:'—';
  if($('#diagnosticsSystemArch'))$('#diagnosticsSystemArch').textContent=[sys.architecture,sys.machine].filter(Boolean).join(' · ')||'—';
  if($('#diagnosticsSystemCpu'))$('#diagnosticsSystemCpu').textContent=sys.cpu_cores??'—';
  if($('#diagnosticsSystemData'))$('#diagnosticsSystemData').textContent=sys.app_data||'—';
}
async function refreshDiagnosticsCenter(show=false){
  if(!apiReady||!bridgeAvailable('get_diagnostics_state'))return;
  try{
    const r=await callApi('get_diagnostics_state');
    if(r?.diagnostics){renderDiagnosticsCenter(r.diagnostics);if(show)showToast('Diagnostics state refreshed')}
  }catch(e){console.error('Diagnostics refresh:',e)}
}

function fitCanvas(canvas){
  // pywebview/WebView2 can report width=0 during the first layout pass. If the
  // intrinsic canvas is resized at that moment, CSS width:100% + auto height
  // can turn a 1x480 canvas into a gigantic white rectangle. Lock the CSS
  // height first and use a safe parent-width fallback.
  const dpr=Math.max(1,Math.min(2,window.devicePixelRatio||1));
  const requestedHeight=Number(canvas.dataset.cssHeight||canvas.getAttribute('height')||160);
  canvas.style.width='100%';
  canvas.style.height=`${requestedHeight}px`;
  const rect=canvas.getBoundingClientRect();
  const parentWidth=canvas.parentElement?.getBoundingClientRect?.().width||0;
  const cssWidth=Math.max(280,rect.width||parentWidth||600);
  const cssHeight=Math.max(80,requestedHeight);
  const pixelWidth=Math.max(1,Math.round(cssWidth*dpr));
  const pixelHeight=Math.max(1,Math.round(cssHeight*dpr));
  if(canvas.width!==pixelWidth)canvas.width=pixelWidth;
  if(canvas.height!==pixelHeight)canvas.height=pixelHeight;
  const ctx=canvas.getContext('2d',{alpha:true});
  ctx.setTransform(dpr,0,0,dpr,0,0);
  return{ctx,width:cssWidth,height:cssHeight};
}
function drawLine(canvas, values){
  if(!canvas)return;
  const {ctx,width,height}=fitCanvas(canvas);
  ctx.clearRect(0,0,width,height);
  // Explicit dark surface prevents transient white backing-store flashes in
  // WebView2/Windows while the GPU surface is being resized.
  ctx.fillStyle=`rgba(${cssRgb('--deep-surface-rgb','7,6,11')},.42)`;
  ctx.fillRect(0,0,width,height);
  ctx.strokeStyle=`rgba(${cssRgb('--accent-light-rgb','211,165,255')},.075)`;ctx.lineWidth=1;
  for(let i=1;i<5;i++){let y=i*height/5;ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(width,y);ctx.stroke();}
  if(values.length<2)return;
  const max=Math.max(...values,1),min=Math.min(...values,0),span=Math.max(1,max-min);
  const fill=ctx.createLinearGradient(0,0,0,height);fill.addColorStop(0,`rgba(${cssRgb('--accent-rgb')},.30)`);fill.addColorStop(1,`rgba(${cssRgb('--accent-soft-rgb','182,120,255')},.01)`);
  const grad=ctx.createLinearGradient(0,0,width,0);grad.addColorStop(0,cssVar('--accent-mid','#6425A8'));grad.addColorStop(.52,cssVar('--accent','#9654FF'));grad.addColorStop(1,cssVar('--accent-light','#D3A5FF'));
  const points=values.map((v,i)=>[i/(values.length-1)*width,height-12-((v-min)/span)*(height-24)]);
  ctx.beginPath();points.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));ctx.lineTo(width,height);ctx.lineTo(0,height);ctx.closePath();ctx.fillStyle=fill;ctx.fill();
  ctx.beginPath();points.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));ctx.strokeStyle=grad;ctx.lineWidth=2;ctx.shadowColor=cssVar('--accent','#9654FF');ctx.shadowBlur=12;ctx.stroke();ctx.shadowBlur=0;
}
function drawCharts(){
  const vals=history.slice(-40);
  requestAnimationFrame(()=>{
    drawLine($('#sparkline'),vals.slice(-20));
    drawLine($('#dataChart'),vals);
  });
}

function renderActivity(logs){
  const root=$('#activityList'); root.innerHTML='';
  (logs||[]).slice(-4).reverse().forEach(x=>{const d=document.createElement('div');d.innerHTML=`<span>◇</span><p><strong>${escapeHtml(x.message)}</strong><small>Bitcoin Miner Studio</small></p><time>${x.time}</time><b>✓</b>`;root.appendChild(d)});
  if(!root.children.length)root.innerHTML='<div class="empty-state">No activity yet.</div>';
}
function renderLogs(logs){const root=$('#logList');root.innerHTML='';(logs||[]).slice().reverse().forEach(x=>{const d=document.createElement('div');d.className='log-line';d.innerHTML=`<time>${x.time}</time><span>${escapeHtml(x.message)}</span>`;root.appendChild(d)});if(!root.children.length)root.innerHTML='<div class="empty-state">No logs yet.</div>'}
function escapeHtml(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function renderAsics(devices){
  const body=$('#asicTable');body.innerHTML='';
  $('#asicSummary').textContent=`${devices.length} device${devices.length===1?'':'s'}`;
  $('#sysAsics').textContent=devices.length;
  devices.forEach(d=>{
    const tr=document.createElement('tr');
    const temp=d.temperature_c==null?'—':`${Number(d.temperature_c).toFixed(1)} °C`;
    const h=d.hashrate_hs?formatHashrate(d.hashrate_hs):'0 H/s';
    const solo=d.solo_connected?'CONNECTED':(d.solo_assigned?'ASSIGNED':'—');
    tr.innerHTML=`<td>${escapeHtml(d.ip)}</td><td>${escapeHtml(d.alias||'—')}</td><td>${escapeHtml(d.model||'Unknown')}</td><td>${escapeHtml(d.verification||'—')}</td><td>${escapeHtml(d.status||'—')}</td><td><span class="asic-solo-state ${d.solo_connected?'connected':''}">${solo}</span></td><td>${d.health??'—'}/100</td><td>${h}</td><td>${temp}</td><td>${escapeHtml(d.pool_url||'—')}</td><td><div class="asic-actions"><button class="ghost-btn asic-solo-assign" data-ip="${d.ip}" ${d.api_verified&&securityTrusted?'':'disabled'}>Solo</button><button class="ghost-btn asic-pool-zero" data-ip="${d.ip}" ${d.can_switch_pool&&securityTrusted?'':'disabled'}>Pool 0</button><button class="ghost-btn asic-web" data-ip="${d.ip}" ${d.can_open_web?'':'disabled'}>Web</button><button class="ghost-btn asic-restart" data-ip="${d.ip}" ${d.can_restart&&securityTrusted?'':'disabled'}>Restart</button><button class="ghost-btn asic-remove" data-ip="${d.ip}">Remove</button></div></td>`;
    body.appendChild(tr)
  });
  if(!devices.length)body.innerHTML='<tr><td colspan="11" class="empty-state">No ASIC devices loaded.</td></tr>';

  $$('.asic-solo-assign').forEach(b=>b.addEventListener('click',async()=>{
    if(!$('#asicAuthorized').checked){showToast('Confirm ASIC ownership/administration first');return}
    if(confirm(`Assign ${b.dataset.ip} to the local Miner Studio Solo Bridge? Existing pool entries will not be deleted.`)){
      await handleResult(callApi('assign_asic_to_solo',b.dataset.ip,true),'ASIC assigned to Solo Bridge');
      await refreshState();
    }
  }));
  $$('.asic-pool-zero').forEach(b=>b.addEventListener('click',async()=>{
    if(!$('#asicAuthorized').checked){showToast('Confirm ASIC ownership/administration first');return}
    if(confirm(`Switch ${b.dataset.ip} back to its existing pool index 0?`)){
      await handleResult(callApi('restore_asic_pool_zero',b.dataset.ip,true),'ASIC switched to pool 0');
      await refreshState();
    }
  }));
  $$('.asic-web').forEach(b=>b.addEventListener('click',()=>handleResult(callApi('open_asic_web',b.dataset.ip),'Opened ASIC Web UI')));
  $$('.asic-restart').forEach(b=>b.addEventListener('click',async()=>{if(confirm(`Restart miner ${b.dataset.ip}?`))await handleResult(callApi('restart_asic',b.dataset.ip),'Restart requested')}));
  $$('.asic-remove').forEach(b=>b.addEventListener('click',async()=>{if(confirm(`Remove ${b.dataset.ip} from the local fleet list?`)){await handleResult(callApi('remove_asic',b.dataset.ip),'Device removed');await refreshState()}}));
}

function formatHashrate(v){const units=[[1e18,'EH/s'],[1e15,'PH/s'],[1e12,'TH/s'],[1e9,'GH/s'],[1e6,'MH/s'],[1e3,'kH/s']];for(const [n,u] of units)if(Math.abs(v)>=n)return`${(v/n).toFixed(2)} ${u}`;return`${Number(v).toFixed(v<10?2:0)} H/s`}

function formatCoreHashrate(v){v=Number(v||0);const units=[[1e18,'EH/s'],[1e15,'PH/s'],[1e12,'TH/s'],[1e9,'GH/s'],[1e6,'MH/s'],[1e3,'kH/s']];for(const[n,u]of units)if(Math.abs(v)>=n)return`${(v/n).toFixed(2)} ${u}`;return`${v.toFixed(0)} H/s`}
function formatCoreDifficulty(v){v=Number(v||0);if(!v)return'—';if(v>=1e12)return`${(v/1e12).toFixed(2)} T`;if(v>=1e9)return`${(v/1e9).toFixed(2)} G`;if(v>=1e6)return`${(v/1e6).toFixed(2)} M`;if(v>=1e3)return`${(v/1e3).toFixed(2)} K`;return v.toFixed(2)}
function formatCoreTime(ts){if(!ts)return'—';try{return new Date(Number(ts)*1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'})}catch{return'—'}}
function syncCoreAuthFields(){const cookie=$('#coreAuthMode').value==='cookie';$$('.cookie-auth-field').forEach(x=>x.classList.toggle('auth-hidden',!cookie));$$('.manual-auth-field').forEach(x=>x.classList.toggle('auth-hidden',cookie))}
function applyDetectedCoreConfig(c){if(!c)return; if(c.rpc_url!==undefined)$('#rpcUrl').value=c.rpc_url||'';if(c.rpc_user!==undefined)$('#rpcUser').value=c.rpc_user||'';if(c.core_auth_mode!==undefined)$('#coreAuthMode').value=c.core_auth_mode||'password';if(c.core_executable!==undefined)$('#coreExecutable').value=c.core_executable||'';if(c.core_data_dir!==undefined)$('#coreDataDir').value=c.core_data_dir||'';if(c.core_cookie_path!==undefined)$('#coreCookiePath').value=c.core_cookie_path||'';if(c.core_network!==undefined)$('#coreNetwork').value=c.core_network||'main';syncCoreAuthFields()}
function renderCoreSetup(d){d=d||{};const dot=$('#setupDot');const ready=!!d.rpc_listening&&((d.auth_mode_recommended==='cookie'&&d.cookie_exists)||d.auth_mode_recommended==='password');const guard=String(d.data_dir_guard_status||'UNKNOWN');const guardBad=['MISMATCH','UNVERIFIED_RUNNING','UNCONFIGURED'].includes(guard);dot.className=`setup-dot ${guardBad?'partial':(ready?'ready':(d.detected?'partial':''))}`;$('#setupStatus').textContent=guardBad?'Data-Dir Guard':(ready?'RPC Ready':(d.detected?'Bitcoin Core detected':'Not detected'));$('#setupStatusDetail').textContent=guardBad?(d.data_dir_guard_message||'Bitcoin Core data directory needs attention.'):(ready?`${d.network||'main'} · ${d.rpc_url||'RPC detected'} · ${d.auth_mode_recommended||'password'} auth`:(d.remediation?.[0]||'Detect your local Bitcoin Core installation and RPC configuration.'));$('#setupDataDir').textContent=d.data_dir_exists?(d.data_dir||'—'):'Not found';const guardEl=$('#setupDataGuard');if(guardEl){guardEl.textContent=guard.replaceAll('_',' ');guardEl.dataset.guard=guard;guardEl.title=d.data_dir_guard_message||''}$('#setupNetwork').textContent=(d.network||'—').toUpperCase();$('#setupPort').textContent=d.rpc_port||'—';$('#setupListening').textContent=d.rpc_listening?'Yes':'No';$('#setupCookie').textContent=d.cookie_exists?'Available':'Not available';$('#setupServer').textContent=d.server_enabled===true?'Enabled':(d.server_enabled===false?'Disabled':'Not set');$('#setupExecutable').textContent=d.executable||'Not found';$('#setupCookiePath').textContent=d.cookie_exists?(d.cookie_path||'—'):'Not found'}
function renderCore(c){c=c||{};const connected=!!c.connected;const synced=connected&&c.status==='Synced';const dot=$('#coreNodeDot');dot.className=`core-node-dot ${connected?(synced?'online':'syncing'):'offline'}`;
  $('#coreStatusText').textContent=connected?c.status||'Connected':'Offline';$('#coreStatusDetail').textContent=connected?`${c.chain||'unknown'} · height ${Number(c.blocks||0).toLocaleString()} · ${c.connections||0} peer(s)`:(c.error||'Bitcoin Core RPC is unavailable.');
  $('#coreLastCheck').textContent=formatCoreTime(c.last_check);$('#coreLatency').textContent=connected?`${Number(c.latency_ms||0).toFixed(1)} ms`:'—';$('#coreChain').textContent=connected?String(c.chain||'—').toUpperCase():'—';$('#coreBlocks').textContent=connected?Number(c.blocks||0).toLocaleString():'—';$('#coreSync').textContent=connected?`${Number(c.sync_percent||0).toFixed(2)}%`:'—';$('#coreConnections').textContent=connected?String(c.connections??0):'—';$('#coreDifficulty').textContent=connected?formatCoreDifficulty(c.difficulty):'—';$('#coreNetworkHash').textContent=connected?formatCoreHashrate(c.networkhashps):'—';$('#coreMempool').textContent=connected?Number(c.pooledtx||0).toLocaleString():'—';$('#coreVersion').textContent=connected?(c.subversion||c.version||'—'):'—';
  $('#coreBlocksHeaders').textContent=connected?`${Number(c.blocks||0).toLocaleString()} / ${Number(c.headers||0).toLocaleString()}`:'—';$('#coreIbd').textContent=connected?(c.initialblockdownload?'Yes':'No'):'—';$('#corePruned').textContent=connected?(c.pruned?'Yes':'No'):'—';$('#coreNetworkActive').textContent=connected?(c.networkactive?'Yes':'No'):'—';$('#coreProtocol').textContent=connected?(c.protocolversion||'—'):'—';$('#coreRelayFee').textContent=connected?`${Number(c.relayfee||0).toFixed(8)} BTC/kvB`:'—';$('#coreBestHash').textContent=connected?(c.bestblockhash||'—'):'—';$('#coreWarnings').textContent=connected?(c.warnings||'None'):(c.error||'Offline');
}
function formatBtc(v){v=Number(v);return Number.isFinite(v)?`${v.toFixed(8)} BTC`:'—'}
function formatTemplateAge(seconds){seconds=Number(seconds||0);if(seconds<1)return'<1 sec';if(seconds<60)return`${seconds.toFixed(0)} sec`;return`${(seconds/60).toFixed(1)} min`}
function formatUnix(ts){ts=Number(ts||0);if(!ts)return'—';try{return new Date(ts*1000).toLocaleString()}catch{return'—'}}
function formatShareDifficulty(v){v=Number(v||0);if(!v)return'—';if(v>=1e12)return`${(v/1e12).toFixed(2)} T`;if(v>=1e9)return`${(v/1e9).toFixed(2)} G`;if(v>=1e6)return`${(v/1e6).toFixed(2)} M`;if(v>=1e3)return`${(v/1e3).toFixed(2)} K`;if(v>=1)return v.toFixed(3);return v.toExponential(3)}
function formatTargetRatio(v){v=Number(v||0);if(!v)return'—';if(v>=1)return`${v.toFixed(4)}× TARGET`;if(v>=.001)return`${(v*100).toFixed(4)}%`;return v.toExponential(3)}
function formatLongDuration(sec){sec=Number(sec||0);if(!Number.isFinite(sec)||sec<=0)return'—';const years=sec/(365.25*86400);if(years>=1e9)return`${years.toExponential(2)} years`;if(years>=1e6)return`${(years/1e6).toFixed(2)} million years`;if(years>=1000)return`${years.toLocaleString(undefined,{maximumFractionDigits:0})} years`;if(years>=1)return`${years.toFixed(2)} years`;const days=sec/86400;if(days>=1)return`${days.toFixed(1)} days`;const hours=sec/3600;if(hours>=1)return`${hours.toFixed(1)} hr`;return`${Math.max(1,sec/60).toFixed(1)} min`}
function formatProbability(v){v=Number(v||0);if(!Number.isFinite(v)||v<=0)return'—';if(v>=.01)return`${(v*100).toFixed(2)}%`;if(v>=1e-6)return`${(v*100).toFixed(6)}%`;return`${(v*100).toExponential(2)}%`}
function formatIntegerCompact(v){v=Number(v||0);if(!Number.isFinite(v)||v<=0)return'—';if(v>=1e18)return v.toExponential(2);if(v>=1e12)return`${(v/1e12).toFixed(2)}T`;if(v>=1e9)return`${(v/1e9).toFixed(2)}B`;if(v>=1e6)return`${(v/1e6).toFixed(2)}M`;return Math.round(v).toLocaleString()}
function renderTemplate(t){t=t||{};const ready=!!t.available;const stale=ready&&!!t.stale;const dot=$('#templateDot');dot.className=`template-dot ${ready?(stale?'stale':'ready'):''}`;
  $('#templateStatus').textContent=ready?(stale?'Stale':'Ready'):'Unavailable';$('#templateStatusDetail').textContent=ready?`height ${Number(t.height||0).toLocaleString()} · ${Number(t.transactions||0).toLocaleString()} tx · ${t.bits||'no bits'}`:(t.error||'Waiting for getblocktemplate.');
  $('#templateEngineMeta').textContent=ready?`getblocktemplate · height ${Number(t.height||0).toLocaleString()}`:'getblocktemplate · unavailable';$('#templateAge').textContent=ready?formatTemplateAge(t.age_seconds):'—';$('#templateRefreshIn').textContent=ready?formatTemplateAge(t.refresh_in_seconds):'—';$('#templateLatency').textContent=ready?`${Number(t.latency_ms||0).toFixed(1)} ms`:'—';
  $('#templateHeight').textContent=ready?Number(t.height||0).toLocaleString():'—';$('#templateTransactions').textContent=ready?Number(t.transactions||0).toLocaleString():'—';$('#templateCoinbase').textContent=ready?formatBtc(t.coinbase_value_btc):'—';$('#templateDifficulty').textContent=ready?formatCoreDifficulty(t.difficulty):'—';$('#templateFees').textContent=ready?formatBtc(t.total_fees_btc):'—';$('#templateSubsidy').textContent=ready&&t.subsidy_btc!==null?formatBtc(t.subsidy_btc):'—';$('#templateWeight').textContent=ready?Number(t.transaction_weight||0).toLocaleString():'—';$('#templateVersion').textContent=ready?`0x${Number(t.version>>>0).toString(16).padStart(8,'0')}`:'—';
  $('#templatePrevHash').textContent=ready?(t.previousblockhash||'—'):'—';$('#templateTarget').textContent=ready?(t.target||'—'):'—';$('#templateBits').textContent=ready?(t.bits||'—'):'—';$('#templateNonceRange').textContent=ready?(t.noncerange||'—'):'—';$('#templateCurtime').textContent=ready?formatUnix(t.curtime):'—';$('#templateMintime').textContent=ready?formatUnix(t.mintime):'—';$('#templateWeightLimit').textContent=ready?Number(t.weight_limit||0).toLocaleString():'—';$('#templateSigopLimit').textContent=ready?Number(t.sigop_limit||0).toLocaleString():'—';$('#templateRules').textContent=ready?((t.rules||[]).join(', ')||'None'):'—';$('#templateMutable').textContent=ready?((t.mutable||[]).join(', ')||'None'):'—';
}
let lastCoinbaseRenderSignature='';
function renderCoinbase(c,force=false){
  c=c||{};
  const dot=$('#coinbaseDot');
  if(!dot)return;
  const ready=!!c.available;
  const sig=[ready,c.height||0,c.txid||'',c.error||'',c.coinbase_value_sats||0].join('|');
  if(!force && sig===lastCoinbaseRenderSignature)return;
  lastCoinbaseRenderSignature=sig;
  dot.className=`template-dot ${ready?'ready':''}`;
  $('#coinbaseStatus').textContent=ready?'Ready':'Waiting';
  $('#coinbaseStatusDetail').textContent=ready?`height ${Number(c.height||0).toLocaleString()} · ${c.payout_type||'address'} · coinbase ${formatBtc(c.coinbase_value_btc)}`:(c.error||'Enter a payout address and build a preview.');
  $('#coinbaseMeta').textContent=ready?`${c.network||'main'} · ${c.payout_type||'payout'} · local preview`:'public-address payout · preview only';
  $('#coinbaseHeight').textContent=ready?Number(c.height||0).toLocaleString():'—';
  $('#coinbaseScriptBytes').textContent=ready?`${Number(c.coinbase_script_sig_bytes||0)} B`:'—';
  $('#coinbaseOutputs').textContent=ready?Number(c.output_count||0):'—';
  $('#coinbaseType').textContent=ready?(c.payout_type||'—'):'—';
  $('#coinbaseReward').textContent=ready?formatBtc(c.coinbase_value_btc):'—';
  $('#coinbaseSubsidy').textContent=ready&&c.subsidy_btc!==null?formatBtc(c.subsidy_btc):'—';
  $('#coinbaseFees').textContent=ready?formatBtc(c.fees_btc):'—';
  $('#coinbaseSize').textContent=ready?`${Number(c.total_size||0)} B`:'—';
  $('#coinbaseWeight').textContent=ready?`${Number(c.weight||0).toLocaleString()} WU`:'—';
  $('#coinbaseWitness').textContent=ready?(c.witness_commitment_present?'Included':'Not required'):'—';
  $('#coinbaseExtraStat').textContent=ready?`${Number(c.extranonce_size||0)} bytes`:'—';
  $('#coinbaseTxid').textContent=ready?(c.txid||'—'):'—';
  $('#coinbaseScriptPubKey').textContent=ready?(c.payout_script_pubkey||'—'):'—';
  $('#coinbaseWitnessCommitment').textContent=ready?(c.witness_commitment||'Not required'):'—';
  $('#coinbaseRaw').textContent=ready?(c.raw_transaction||'—'):'—';
}

function renderSolo(x){
  x=x||{};
  const running=!!x.running,candidate=!!x.candidate_found;
  const dot=$('#soloDot');
  dot.className=`template-dot ${candidate?'candidate':(running?'ready':'')}`;

  $('#soloStatus').textContent=x.status||'Idle';
  $('#soloStatusDetail').textContent=x.detail||'Ready for a current block template.';
  $('#soloMeta').textContent=candidate?'target-valid candidate preserved · guarded submission ready':(running?'SHA-256d · live probability · stale-work protection':'SHA-256d · Dashboard+ · guarded submission');

  $('#soloHeight').textContent=x.work_height?Number(x.work_height).toLocaleString():'—';
  $('#soloWorkAge').textContent=x.work_height?formatTemplateAge(x.work_age_seconds):'—';
  $('#soloNonce').textContent=(x.work_height||running)?Number(x.nonce||0).toLocaleString():'—';
  $('#soloExtranonce').textContent=(x.work_height||running)?Number(x.extranonce||0).toLocaleString():'—';

  $('#soloHashrate').textContent=running||x.total_hashes?formatCoreHashrate(x.hashrate||0):'—';
  $('#soloAvgHashrate').textContent=x.total_hashes?formatCoreHashrate(x.average_hashrate||0):'—';
  $('#soloPeakHashrate').textContent=x.total_hashes?formatCoreHashrate(x.peak_hashrate||0):'—';
  $('#soloHashes').textContent=Number(x.total_hashes||0).toLocaleString();
  $('#soloBestDifficulty').textContent=formatShareDifficulty(x.best_difficulty);
  $('#soloTargetRatio').textContent=formatTargetRatio(x.target_ratio);
  $('#soloExpected').textContent=formatLongDuration(x.expected_seconds);
  $('#soloTime50').textContent=formatLongDuration(x.time_to_50pct);
  $('#soloSessionChance').textContent=formatProbability(x.session_probability);
  $('#soloChance1h').textContent=formatProbability(x.probability_1h);
  $('#soloChance24h').textContent=formatProbability(x.probability_24h);
  $('#soloChance7d').textContent=formatProbability(x.probability_7d);

  const ratio=Math.max(0,Number(x.target_ratio||0));
  const targetPercent=Math.min(100,ratio*100);
  $('#soloTargetProgress').style.width=`${targetPercent}%`;
  $('#soloTargetProgressText').textContent=ratio>=1?'TARGET MET':formatTargetRatio(ratio);

  $('#soloTemplateSwitches').textContent=Number(x.template_switches||0).toLocaleString();
  $('#soloStaleBatches').textContent=Number(x.stale_batches_discarded||0).toLocaleString();
  $('#soloStaleHashes').textContent=Number(x.stale_hashes_discarded||0).toLocaleString();
  $('#soloStaleCandidates').textContent=Number(x.stale_candidates_rejected||0).toLocaleString();
  $('#soloReliability').textContent=candidate?'Candidate Locked':(running?(x.auto_new_template?'Protected':'Manual Templates'):'Idle');

  $('#soloRolls').textContent=Number(x.extranonce_rolls||0).toLocaleString();
  $('#soloEffectiveBatch').textContent=x.batch_size?Number(x.batch_size).toLocaleString():'—';
  $('#soloAutoState').textContent=x.auto_new_template?'Enabled':'Disabled';

  $('#soloPrevHash').textContent=x.previousblockhash||'—';
  $('#soloMerkle').textContent=x.merkle_root||'—';
  $('#soloBestHash').textContent=x.best_hash||'—';
  $('#soloTarget').textContent=x.target||'—';
  $('#soloCandidateHeader').textContent=x.candidate_header||'—';
  $('#soloSubmitState').textContent=x.candidate_found?'Candidate preserved for guarded submission':'Guarded block-submission path';

  const rateHistory=(x.hashrate_history||[]).map(v=>Number(v.h||0));
  requestAnimationFrame(()=>drawLine($('#soloHashrateChart'),rateHistory));
  $('#soloChartMeta').textContent=rateHistory.length?`${rateHistory.length} sample${rateHistory.length===1?'':'s'} · ${formatCoreHashrate(x.average_hashrate||0)} avg`:'last 90 seconds';

  const historyRoot=$('#soloBestHistory');
  const bestHistory=(x.best_history||[]).slice().reverse();
  historyRoot.innerHTML='';
  bestHistory.forEach(item=>{
    const row=document.createElement('div');
    row.className='solo-best-row';
    let t='—';try{t=new Date(Number(item.time||0)*1000).toLocaleTimeString()}catch{}
    row.innerHTML=`<time>${escapeHtml(t)}</time><div><strong>${escapeHtml(item.hash||'—')}</strong><small>height ${Number(item.height||0).toLocaleString()} · nonce ${Number(item.nonce||0).toLocaleString()}</small></div><b>${escapeHtml(formatShareDifficulty(item.difficulty))}</b>`;
    historyRoot.appendChild(row);
  });
  if(!historyRoot.children.length)historyRoot.innerHTML='<div class="empty-state">No best-work samples yet.</div>';

  $('#soloStart').disabled=!apiReady||running||!securityTrusted;
  $('#soloStop').disabled=!apiReady||!running;
}


function renderSubmission(x){
  x=x||{};
  const assembled=!!x.assembled;
  const proposalValid=!!x.proposal_valid;
  const accepted=!!x.accepted;
  const stale=!!x.stale;
  const busy=!!x.busy;
  const dot=$('#submissionDot');
  dot.className=`template-dot ${accepted?'accepted':(proposalValid?'validated':(assembled?'ready':''))}`;
  $('#submissionStatus').textContent=x.status||'Waiting';
  $('#submissionDetail').textContent=x.detail||'Waiting for a target-valid candidate.';
  $('#submissionHeight').textContent=x.height?Number(x.height).toLocaleString():'—';
  $('#submissionSize').textContent=x.block_size?`${Number(x.block_size).toLocaleString()} B`:'—';
  $('#submissionWeight').textContent=x.block_weight?`${Number(x.block_weight).toLocaleString()} WU`:'—';
  $('#submissionTxCount').textContent=x.transaction_count?Number(x.transaction_count).toLocaleString():'—';
  $('#submissionTargetValid').textContent=assembled?(x.target_valid?'VALID':'FAIL'):'—';
  $('#submissionProposal').textContent=x.proposal_checked?(x.proposal_valid?'VALID':(stale?'STALE':'REJECTED')):'—';
  $('#submissionSubmit').textContent=x.submitted?(x.accepted?'ACCEPTED':'REJECTED'):'—';
  $('#submissionHash').textContent=x.block_hash||'—';
  $('#submissionPrev').textContent=x.previousblockhash||'—';
  $('#submissionMerkle').textContent=x.merkle_root||'—';
  $('#submissionSource').textContent=x.candidate_source||'—';
  $('#submissionArchive').textContent=x.archive_json||x.archive_block||'—';
  $('#submissionTest').disabled=!apiReady||busy;
  $('#submissionAssemble').disabled=!apiReady||busy||!x.candidate_available||!x.target_valid;
  $('#submissionValidate').disabled=!apiReady||busy||!assembled||!x.candidate_available||!x.target_valid||stale||accepted;
  $('#submissionSubmitBtn').disabled=!apiReady||busy||!assembled||!x.candidate_available||!x.target_valid||stale||accepted||!securityTrusted;
  if(x.result_text && $('#submissionResult').dataset.lastResult!==x.result_text){
    $('#submissionResult').dataset.lastResult=x.result_text;
    $('#submissionResult').textContent=x.result_text;
  }
}

function renderRegtest(r){
  r=r||{};
  const busy=!!r.busy;
  const ready=!!r.ready;
  const dot=$('#regtestDot');
  dot.className=`template-dot ${busy?'busy':(ready?'ready':'')}`;
  $('#regtestStatus').textContent=r.status||'Stopped';
  $('#regtestDetail').textContent=r.detail||'Start the isolated lab when ready.';
  $('#regtestHeight').textContent=Number(r.height||0).toLocaleString();
  $('#regtestProgress').textContent=r.progress_total?`${Number(r.progress_current||0).toLocaleString()} / ${Number(r.progress_total).toLocaleString()}`:'—';
  $('#regtestRpc').textContent=r.rpc_port||19443;
  $('#regtestRpcUrl').value=r.rpc_url||'http://127.0.0.1:19443';
  $('#regtestSessionBlocks').textContent=Number(r.blocks_mined_session||0).toLocaleString();
  $('#regtestSpendable').textContent=`${Number(r.spendable_btc||0).toFixed(8)} BTC`;
  $('#regtestImmature').textContent=`${Number(r.immature_btc||0).toFixed(8)} BTC`;
  $('#regtestHashes').textContent=r.last_hashes?Number(r.last_hashes).toLocaleString():'—';
  $('#regtestNonce').textContent=(r.last_block_hash||r.last_nonce)?Number(r.last_nonce||0).toLocaleString():'—';
  $('#regtestProposal').textContent=r.proposal_valid?'VALID':'—';
  $('#regtestSubmit').textContent=r.submit_accepted?'ACCEPTED':'—';
  $('#regtestDataDir').textContent=r.data_dir||'—';
  $('#regtestAddress').textContent=r.payout_address||'—';
  $('#regtestBestHash').textContent=r.bestblockhash||'—';
  $('#regtestLastHash').textContent=r.last_block_hash||'—';
  $('#regtestExecutable').textContent=r.executable||'—';

  ['#regtestStart','#regtestRefresh','#regtestMine','#regtestMine101','#regtestStop','#regtestReset'].forEach(sel=>{
    const el=$(sel);if(el)el.disabled=!apiReady||busy;
  });
  $('#regtestStart').disabled=!apiReady||busy||ready;
  $('#regtestRefresh').disabled=!apiReady||busy||!ready;
  $('#regtestMine').disabled=!apiReady||busy||!ready;
  $('#regtestMine101').disabled=!apiReady||busy||!ready;
  $('#regtestStop').disabled=!apiReady||busy||!ready;
  $('#regtestReset').disabled=!apiReady||busy;

  if(r.result_text && $('#regtestResult').dataset.lastResult!==r.result_text){
    $('#regtestResult').dataset.lastResult=r.result_text;
    $('#regtestResult').textContent=r.result_text;
  }
}

function renderAsicSoloBridge(x){
  x=x||{};
  const running=!!x.running;
  const dot=$('#asicSoloDot');
  dot.className=`template-dot ${running?'ready':''}`;
  $('#asicSoloStatus').textContent=x.status||'Stopped';
  $('#asicSoloDetail').textContent=x.detail||'Start the bridge when Bitcoin Core and payout configuration are ready.';
  $('#asicSoloHeight').textContent=x.template_height?Number(x.template_height).toLocaleString():'—';
  $('#asicSoloClients').textContent=Number(x.connected_clients||0).toLocaleString();
  $('#asicSoloJobAge').textContent=x.job_id?formatTemplateAge(x.job_age_seconds):'—';
  $('#asicSoloAccepted').textContent=Number(x.shares_accepted||0).toLocaleString();
  $('#asicSoloRejected').textContent=Number(x.shares_rejected||0).toLocaleString();
  $('#asicSoloStale').textContent=Number(x.shares_stale||0).toLocaleString();
  $('#asicSoloBestDiff').textContent=formatShareDifficulty(x.best_share_difficulty);
  $('#asicSoloHashrate').textContent=x.estimated_hashrate_hs?formatCoreHashrate(x.estimated_hashrate_hs):'—';
  $('#asicSoloWorkersCount').textContent=Number(x.authorized_workers||0).toLocaleString();
  $('#asicSoloCandidates').textContent=Number(x.candidates_found||0).toLocaleString();
  $('#asicSoloNetwork').textContent=(x.network||'—').toUpperCase();
  $('#asicSoloEndpoint').value=x.endpoint||'—';
  $('#asicSoloPayout').textContent=x.payout_address||'—';
  $('#asicSoloJob').textContent=x.job_id||'—';
  $('#asicSoloPrev').textContent=x.previousblockhash||'—';
  $('#asicSoloLastShare').textContent=x.last_share_hash||'—';
  $('#asicSoloLastCandidate').textContent=x.last_candidate_hash||'—';

  const body=$('#asicSoloWorkers');body.innerHTML='';
  (x.workers||[]).forEach(w=>{
    const tr=document.createElement('tr');
    tr.innerHTML=`<td>${escapeHtml(w.worker||'—')}</td><td>${escapeHtml(w.ip||'—')}</td><td>${w.active?(w.authorized?'AUTHORIZED':'CONNECTED'):'RECENT'}</td><td>${Number(w.shares_accepted||0).toLocaleString()}</td><td>${Number(w.shares_stale||0).toLocaleString()}</td><td>${escapeHtml(formatShareDifficulty(w.best_difficulty))}</td>`;
    body.appendChild(tr);
  });
  if(!body.children.length)body.innerHTML='<tr><td colspan="6" class="empty-state">No ASIC Stratum workers connected yet.</td></tr>';

  $('#asicSoloStart').disabled=!apiReady||running||!securityTrusted;
  $('#asicSoloStop').disabled=!apiReady||!running;
  $('#asicSoloCopy').disabled=!x.endpoint;
}

function renderSecurity(x){
  x=x||{};
  securityChecked=!!x.checked;
  securityTrusted=!!x.critical_actions_allowed;
  document.body.classList.toggle('security-locked',securityChecked&&!securityTrusted);

  const status=securityTrusted?'TRUSTED':(securityChecked?'LOCKED':'CHECKING');
  $('#securityStatus').textContent=status;
  $('#securityControls').textContent=securityTrusted?'ENABLED':'LOCKED';
  $('#securityScheme').textContent=x.security_scheme||x.manifest_security_scheme||'PD-PROVENANCE-2';
  $('#securityDetail').textContent=securityTrusted
    ?'Publisher signature and every protected application file verified successfully.'
    :(securityChecked?(x.error||'Build trust verification failed.'):'Verifying publisher signature and protected application files.');
  $('#securitySignature').textContent=x.signature_valid?'VALID':(securityChecked?'INVALID':'—');
  $('#securityFiles').textContent=`${Number(x.verified_file_count||0)} / ${Number(x.protected_file_count||0)}`;
  $('#securityBuildId').textContent=x.build_id||'—';
  $('#securityReleaseSeal').textContent=x.release_seal||'—';
  $('#securityProvenance').textContent=x.provenance_tag||'—';
  if($('#securityPublisherName'))$('#securityPublisherName').textContent=x.publisher_name||'Purple Dragon Foundation ltd';
  $('#securityPublisherKey').textContent=x.publisher_key_id||'—';
  $('#securityWatermark').textContent=x.release_watermark||'—';
  $('#securityInstallCode').textContent=x.install_fingerprint_short||'—';
  $('#securityPolicyGate').textContent=securityTrusted?'ACTIVE':'LOCKED';

  const hero=$('#securityHero');hero.classList.toggle('locked',securityChecked&&!securityTrusted);
  const chip=$('#securityTopChip');chip.classList.toggle('trusted',securityTrusted);chip.classList.toggle('locked',securityChecked&&!securityTrusted);
  $('#securityTopState').textContent=status;

  const files=x.file_status||[];
  const body=$('#securityFileTable');body.innerHTML='';
  files.forEach(f=>{
    const st=String(f.status||'UNKNOWN').toLowerCase();
    const tr=document.createElement('tr');
    tr.innerHTML=`<td class="mono">${escapeHtml(f.path||'—')}</td><td><span class="security-file-status ${escapeHtml(st)}">${escapeHtml(f.status||'UNKNOWN')}</span></td><td class="mono">${escapeHtml(f.expected||'—')}</td><td class="mono">${escapeHtml(f.actual||'—')}</td>`;
    body.appendChild(tr);
  });
  if(!body.children.length)body.innerHTML='<tr><td colspan="4" class="empty-state">Protected-file verification has not completed yet.</td></tr>';
  $('#securityFileSummary').textContent=securityTrusted
    ?`${Number(x.verified_file_count||0)} protected files verified`
    :(securityChecked?`${Number((x.modified_files||[]).length)} modified · ${Number((x.missing_files||[]).length)} missing`:'Waiting for verification');

  // Fail-safe: start/write controls lock on a failed/unfinished build check,
  // while stop/read-only/diagnostic controls remain available.
  if($('#poolStart'))$('#poolStart').disabled=!apiReady||!!lastState?.miner_running||!securityTrusted;
  if($('#enginePrimary')&&!lastState?.miner_running)$('#enginePrimary').disabled=!securityTrusted;
  if($('#quickMining')&&!lastState?.miner_running)$('#quickMining').disabled=!securityTrusted;
  if($('#soloStart'))$('#soloStart').disabled=!apiReady||!!lastState?.solo_mining?.running||!securityTrusted;
  if($('#asicSoloStart'))$('#asicSoloStart').disabled=!apiReady||!!lastState?.asic_solo_bridge?.running||!securityTrusted;
}

function poolScoreClass(score){
  score=Number(score||0);
  if(score>=85)return'good';
  if(score>=55)return'warn';
  return'';
}
const FAILOVER_POLICY_TEXT={
  manual:'Manual Only: stay on the selected endpoint and reconnect there only.',
  conservative:'Conservative: require two consecutive endpoint failures before switching; retry the primary after 15 minutes.',
  balanced:'Balanced: fail over after one confirmed endpoint failure and retry the primary after 5 minutes on a healthy backup.',
  aggressive:'Aggressive: switch immediately and retry the primary after 1 minute on a healthy backup.'
};
const FAILOVER_POLICY_RECOVERY={manual:0,conservative:900,balanced:300,aggressive:60};
function syncFailoverPolicyUi(useDefault=false){
  const select=$('#poolFailoverPolicy');if(!select)return;
  const policy=select.value||'balanced';
  if(useDefault&&$('#poolPrimaryRecovery'))$('#poolPrimaryRecovery').value=FAILOVER_POLICY_RECOVERY[policy]??300;
  if($('#poolFailoverEnabled'))$('#poolFailoverEnabled').checked=policy!=='manual';
  if($('#poolPrimaryRecovery'))$('#poolPrimaryRecovery').disabled=policy==='manual';
  if($('#poolFailoverPolicyDetail'))$('#poolFailoverPolicyDetail').textContent=FAILOVER_POLICY_TEXT[policy]||FAILOVER_POLICY_TEXT.balanced;
}
function profilePayload(){
  const base=poolPayload();
  return {...base,
    id:$('#poolProfileSelect')?.value||'',
    name:$('#poolProfileName')?.value.trim()||'',
    failover_policy:$('#poolFailoverPolicy')?.value||'balanced',
    primary_recovery_seconds:Number($('#poolPrimaryRecovery')?.value||0),
    job_timeout_seconds:Number($('#poolJobTimeout')?.value||120),
    pool_fee_percent:Number($('#poolProfileFee')?.value||0),
    enabled:!!$('#poolProfileEnabled')?.checked,
    notes:$('#poolProfileNotes')?.value||''
  };
}
function clearPoolProfileEditor(){
  if($('#poolProfileSelect'))$('#poolProfileSelect').value='';
  if($('#poolProfileName'))$('#poolProfileName').value='';
  if($('#poolProfileNotes'))$('#poolProfileNotes').value='';
  if($('#poolProfileFee'))$('#poolProfileFee').value='1';
  if($('#poolProfileEnabled'))$('#poolProfileEnabled').checked=true;
  if($('#poolFailoverPolicy'))$('#poolFailoverPolicy').value='balanced';
  if($('#poolPrimaryRecovery'))$('#poolPrimaryRecovery').value='300';
  syncFailoverPolicyUi();
}
function loadProfileIntoEditor(profile){
  if(!profile)return;
  if($('#poolProfileSelect'))$('#poolProfileSelect').value=profile.id||'';
  if($('#poolProfileName'))$('#poolProfileName').value=profile.name||'';
  if($('#poolProfileFee'))$('#poolProfileFee').value=Number(profile.pool_fee_percent??1);
  if($('#poolProfileEnabled'))$('#poolProfileEnabled').checked=profile.enabled!==false;
  if($('#poolProfileNotes'))$('#poolProfileNotes').value=profile.notes||'';
  if($('#poolFailoverPolicy'))$('#poolFailoverPolicy').value=profile.failover_policy||'balanced';
  if($('#poolPrimaryRecovery'))$('#poolPrimaryRecovery').value=Number(profile.primary_recovery_seconds??300);
  applyPoolConfigToForm({
    pool_url:profile.pool_url,
    pool_backup_urls:profile.pool_backup_urls||[],
    pool_worker:profile.pool_worker,
    pool_failover_enabled:(profile.failover_policy||'balanced')!=='manual',
    pool_failover_policy:profile.failover_policy||'balanced',
    pool_primary_recovery_seconds:Number(profile.primary_recovery_seconds??300),
    pool_job_timeout_seconds:Number(profile.job_timeout_seconds??120),
    mining_processes:Number(profile.mining_processes??2),
    suggest_difficulty_enabled:!!profile.suggest_difficulty_enabled,
    suggest_difficulty:Number(profile.suggest_difficulty??1)
  });
  $('#poolPassword').value='';
  syncFailoverPolicyUi();
}
function renderPoolProfiles(state){
  state=state||{};poolProfilesState=state;
  const rows=Array.isArray(state.profiles)?state.profiles:[];
  const active=state.active_profile||rows.find(x=>x.active)||null;
  if($('#poolProfileCount'))$('#poolProfileCount').textContent=rows.length;
  if($('#poolProfileActiveName'))$('#poolProfileActiveName').textContent=active?.name||'—';
  if($('#poolProfilePolicyKpi'))$('#poolProfilePolicyKpi').textContent=String(active?.failover_policy||state.runtime?.failover_policy||'balanced').toUpperCase();
  if($('#poolProfileRecoveryKpi'))$('#poolProfileRecoveryKpi').textContent=active?durationLong(Number(active.primary_recovery_seconds||0)):'—';
  if($('#poolProfileCredentialKpi'))$('#poolProfileCredentialKpi').textContent=active?(active.credential_stored?'STORED':'ENTER PASSWORD'):'—';
  const badge=$('#poolProfileActiveBadge');if(badge){badge.textContent=active?`ACTIVE · ${active.name}`:'NO ACTIVE PROFILE';badge.classList.toggle('active',!!active)}

  const select=$('#poolProfileSelect');if(select){
    const current=select.value;
    select.innerHTML='<option value="">New profile…</option>'+rows.map(r=>`<option value="${escapeHtml(r.id)}">${escapeHtml(r.name)}${r.active?' · ACTIVE':''}</option>`).join('');
    if(rows.some(r=>r.id===current))select.value=current;else if(active)select.value=active.id;
  }
  const tbody=$('#poolProfilesTable');if(tbody){
    tbody.innerHTML=rows.length?rows.map(r=>`<tr class="${r.active?'active-row':''}" data-profile-id="${escapeHtml(r.id)}">
      <td>${escapeHtml(r.name)}</td><td>${1+(r.pool_backup_urls||[]).length}</td><td>${escapeHtml(String(r.failover_policy||'balanced').toUpperCase())}</td>
      <td>${Number(r.pool_fee_percent||0).toFixed(2)}%</td><td><span class="pool-profile-credential ${r.credential_stored?'yes':''}">${r.credential_stored?'✓ STORED':'—'}</span></td>
      <td><span class="pool-profile-state ${r.active?'active':''}">${r.active?'ACTIVE':(r.enabled===false?'DISABLED':'READY')}</span></td></tr>`).join(''):'<tr><td colspan="6">No saved pool profiles yet.</td></tr>';
  }
}
async function refreshPoolProfiles(show=false){
  if(!bridgeAvailable('get_pool_profiles_state'))return;
  try{const r=await callApi('get_pool_profiles_state');if(!r?.ok)throw new Error(r?.error||'Could not load pool profiles');renderPoolProfiles(r.pool_profiles);if(show)showToast('Pool profiles refreshed')}catch(e){if(show)showToast(`Pool Profiles: ${e.message}`)}
}

function renderPoolPowerTools(x,recentShares=[]){
  x=x||{};
  const session=x.session||{};
  const diag=x.diagnostics||{};
  const connected=!!session.connected;
  const authorized=!!session.authorized;
  const health=Number(session.health||0);

  $('#poolPtDot').className=`template-dot ${connected&&authorized?'ready':''}`;
  $('#poolPtStatus').textContent=lastState?.miner_running?(authorized?'Mining':'Connecting'):'Idle';
  $('#poolPtDetail').textContent=lastState?.miner_running
    ?(authorized?'Stratum session is authorized and protected by failover/job-watchdog controls.':'Connecting/subscribing/authorizing the configured pool endpoint.')
    :'Configure endpoints and start mining when ready.';
  $('#poolPtHealth').textContent=lastState?.miner_running?`${health}/100`:'—';
  $('#poolPtEndpointIndex').textContent=session.endpoint_count?`${Number(session.active_endpoint_index||0)+1} / ${session.endpoint_count}`:'—';
  $('#poolPtJobAge').textContent=session.job_count?formatTemplateAge(session.job_age_seconds):'—';
  $('#poolPtActiveEndpoint').textContent=session.active_endpoint||'—';
  $('#poolPtConnectLatency').textContent=lastState?.latency_text||'—';
  $('#poolPtShareP95').textContent=session.share_response_p95_ms?`${Number(session.share_response_p95_ms).toFixed(1)} ms`:'—';
  $('#poolPtFailovers').textContent=Number(session.failover_count||0).toLocaleString();
  $('#poolPtReconnects').textContent=Number(session.reconnect_count||0).toLocaleString();
  $('#poolPtJobs').textContent=Number(session.job_count||0).toLocaleString();
  $('#poolPtDiffChanges').textContent=Number(session.difficulty_changes||0).toLocaleString();
  $('#poolPtBestShare').textContent=formatShareDifficulty(session.best_share_difficulty);
  if($('#poolPtPolicy'))$('#poolPtPolicy').textContent=String(session.failover_policy||'balanced').toUpperCase();
  if($('#poolPtRecovery'))$('#poolPtRecovery').textContent=Number(session.primary_recovery_seconds||0)>0?durationLong(Number(session.primary_recovery_seconds||0)):'MANUAL';
  if($('#poolPtEndpointUptime'))$('#poolPtEndpointUptime').textContent=durationLong(Number(session.active_endpoint_uptime_seconds||0));
  if($('#poolPtFailoverReason'))$('#poolPtFailoverReason').textContent=session.last_failover_reason||'—';

  $('#poolPtConnected').textContent=connected?'Yes':'No';
  $('#poolPtAuthorized').textContent=authorized?'Yes':'No';
  $('#poolPtCurrentJob').textContent=lastState?.job||'—';
  $('#poolPtDifficulty').textContent=lastState?.difficulty_text||'—';
  $('#poolPtEx1').textContent=session.extranonce1||'—';
  $('#poolPtEx2Size').textContent=session.extranonce2_size?`${session.extranonce2_size} bytes`:'—';
  $('#poolPtCleanJobs').textContent=Number(session.clean_job_count||0).toLocaleString();
  $('#poolPtJobUpdates').textContent=Number(session.job_update_count||0).toLocaleString();
  $('#poolPtDuplicates').textContent=Number(session.duplicate_prevented||0).toLocaleString();
  $('#poolPtDisconnect').textContent=session.last_disconnect_reason||'—';

  $('#poolShareAccepted').textContent=Number(lastState?.accepted||0).toLocaleString();
  $('#poolShareRejected').textContent=Number(lastState?.rejected||0).toLocaleString();
  $('#poolShareStale').textContent=Number(lastState?.stale||0).toLocaleString();
  $('#poolShareAvg').textContent=session.share_response_avg_ms?`${Number(session.share_response_avg_ms).toFixed(1)} ms`:'—';

  const protocol=$('#poolProtocolTable');protocol.innerHTML='';
  (session.protocol_events||[]).forEach(row=>{
    const tr=document.createElement('tr');
    tr.innerHTML=`<td>${escapeHtml(row.time||'—')}</td><td><span class="pool-protocol-direction">${escapeHtml(row.direction||'—')}</span></td><td class="mono">${escapeHtml(row.method||'—')}</td><td>${escapeHtml(row.detail||'')}</td>`;
    protocol.appendChild(tr);
  });
  if(!protocol.children.length)protocol.innerHTML='<tr><td colspan="4" class="empty-state">No Stratum protocol events recorded yet.</td></tr>';

  const shares=$('#poolShareTable');shares.innerHTML='';
  (recentShares||[]).forEach(row=>{
    const result=String(row.result||'—').toUpperCase();
    const tr=document.createElement('tr');
    tr.innerHTML=`<td>${escapeHtml(row.time||'—')}</td><td>${escapeHtml(result)}</td><td class="mono">${escapeHtml(row.job_id||'—')}</td><td class="mono">${escapeHtml(row.nonce||'—')}</td><td>${escapeHtml(formatShareDifficulty(row.share_difficulty))}</td><td>${row.response_ms!=null?`${Number(row.response_ms).toFixed(1)} ms`:'—'}</td>`;
    shares.appendChild(tr);
  });
  if(!shares.children.length)shares.innerHTML='<tr><td colspan="6" class="empty-state">No decided shares in this session yet.</td></tr>';

  const diff=$('#poolDifficultyTable');diff.innerHTML='';
  (session.difficulty_history||[]).forEach(row=>{
    const tr=document.createElement('tr');
    tr.innerHTML=`<td>${escapeHtml(row.time||'—')}</td><td>${escapeHtml(formatShareDifficulty(row.difficulty))}</td><td class="mono">${escapeHtml(row.source||'—')}</td>`;
    diff.appendChild(tr);
  });
  if(!diff.children.length)diff.innerHTML='<tr><td colspan="3" class="empty-state">No pool difficulty changes recorded yet.</td></tr>';

  $('#poolDiagStatus').textContent=diag.running?'RUNNING':String(diag.status||'Idle').toUpperCase();
  $('#poolDiagDetail').textContent=diag.detail||'Run Test All Endpoints to profile configured Stratum endpoints.';
  const diagnostics=$('#poolDiagnosticsTable');diagnostics.innerHTML='';
  (diag.results||[]).forEach((row,index)=>{
    const score=Number(row.score||0);
    const auth=row.worker_supplied?(row.authorized?'OK':'FAIL'):'SKIPPED';
    const tr=document.createElement('tr');
    tr.innerHTML=`<td>${index+1}</td><td class="mono">${escapeHtml(row.endpoint||'—')}</td><td><span class="pool-score ${poolScoreClass(score)}">${score}/100</span></td><td>${escapeHtml(row.transport||'—')}</td><td>${row.dns_ms?`${Number(row.dns_ms).toFixed(1)} ms`:'—'}</td><td>${row.connect_ms?`${Number(row.connect_ms).toFixed(1)} ms`:'—'}</td><td>${row.subscribed?'OK':'FAIL'}</td><td>${escapeHtml(auth)}</td><td>${row.job_received?'YES':'NO'}</td><td title="${escapeHtml(row.error||'')}">${row.error?'ERROR':'READY'}</td>`;
    diagnostics.appendChild(tr);
  });
  if(!diagnostics.children.length)diagnostics.innerHTML='<tr><td colspan="10" class="empty-state">No endpoint diagnostics have been run yet.</td></tr>';

  $('#poolDiagnosticsStart').disabled=!!diag.running;
  $('#poolDiagnosticsClear').disabled=!!diag.running;
}

function benchmarkDurationText(seconds){
  seconds=Math.max(0,Number(seconds||0));
  if(seconds<60)return`${seconds.toFixed(seconds<10?1:0)}s`;
  const m=Math.floor(seconds/60),r=Math.round(seconds%60);
  return r?`${m}m ${r}s`:`${m}m`;
}
function benchmarkTimeLabel(value){
  if(!value)return'—';
  try{return new Date(value).toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'})}catch{return String(value)}
}
function renderBenchmarkLab(lab){
  if(!lab)return;
  benchmarkLabState=lab;
  const stats=lab.stats||{},active=lab.active||{},suite=lab.suite||{};
  const running=!!lab.running, suiteRunning=!!suite.running;
  const avg=Number(stats.average_hashrate||stats.hashrate||0), current=Number(stats.current_hashrate||avg||0), peak=Number(stats.peak_hashrate||0);
  const stability=Math.max(0,Math.min(100,Number(stats.stability_percent??100)));
  const score=Number(lab.score_live||0);
  const progress=Math.max(0,Math.min(100,Number(lab.progress_percent||0)));
  const status=suiteRunning?'SCALING':running?'RUNNING':'READY';
  const badge=$('#benchmarkStatusBadge');if(badge){badge.textContent=status;badge.dataset.state=status.toLowerCase()}
  if($('#benchmarkLiveTitle'))$('#benchmarkLiveTitle').textContent=running?(active.label||'Benchmark Running'):'Local SHA-256d Performance';
  if($('#benchmarkLiveMeta'))$('#benchmarkLiveMeta').textContent=running
    ?`${Number(active.workers||stats.workers||0)} worker(s) · ${active.duration_seconds?benchmarkDurationText(active.duration_seconds):'manual duration'}${suiteRunning?` · scaling step ${suite.current_step||0}/${suite.total_steps||0}`:''}`
    :'Choose a preset or custom duration, then run a local benchmark.';
  if($('#benchmarkProgressBar'))$('#benchmarkProgressBar').style.width=`${running?(active.duration_seconds?progress:100):0}%`;
  if($('#benchmarkElapsed'))$('#benchmarkElapsed').textContent=running?`${benchmarkDurationText(stats.elapsed_seconds||0)} elapsed`:'0.0s elapsed';
  if($('#benchmarkRemaining'))$('#benchmarkRemaining').textContent=running?(active.duration_seconds?`${benchmarkDurationText(lab.remaining_seconds||0)} remaining`:'Manual stop'):'Ready';
  if($('#benchmarkCurrentRate'))$('#benchmarkCurrentRate').textContent=formatHashrate(current);
  if($('#benchmarkAverageRate'))$('#benchmarkAverageRate').textContent=formatHashrate(avg);
  if($('#benchmarkPeakRate'))$('#benchmarkPeakRate').textContent=formatHashrate(peak);
  if($('#benchmarkStability'))$('#benchmarkStability').textContent=`${stability.toFixed(1)}%`;
  if($('#benchmarkHashes'))$('#benchmarkHashes').textContent=Number(stats.total_hashes||0).toLocaleString();
  if($('#benchmarkScore'))$('#benchmarkScore').textContent=score.toFixed(2);
  const hs=lab.history_summary||{};
  if($('#benchmarkScoreDelta')){
    const latest=Number(hs.latest_score||0),best=Number(hs.best_score||0);
    $('#benchmarkScoreDelta').textContent=running?'Live local comparison score':latest&&best?(latest===best?'Latest run is current best':`${((latest/best-1)*100).toFixed(1)}% vs best`):'Local comparison score';
  }
  if($('#benchmarkHistoryCount'))$('#benchmarkHistoryCount').textContent=Number(hs.count||0).toLocaleString();
  if($('#benchmarkBestScore'))$('#benchmarkBestScore').textContent=Number(hs.best_score||0).toFixed(2);
  if($('#benchmarkLatestScore'))$('#benchmarkLatestScore').textContent=Number(hs.latest_score||0).toFixed(2);
  if($('#benchmarkCpuCount'))$('#benchmarkCpuCount').textContent=`${Number(lab.cpu_count||1)} logical CPUs`;

  const primary=$('#benchmarkPrimary'),start=$('#benchmarkStart'),stop=$('#benchmarkStop');
  if(primary){primary.textContent=running||suiteRunning?'Stop Benchmark':'Start Benchmark';primary.disabled=!apiReady}
  if(start)start.disabled=running||suiteRunning||!apiReady;
  if(stop)stop.disabled=!(running||suiteRunning)||!apiReady;
  if($('#benchmarkScalingStart'))$('#benchmarkScalingStart').disabled=running||suiteRunning||!apiReady;
  if($('#benchmarkScalingStop'))$('#benchmarkScalingStop').disabled=!suiteRunning||!apiReady;
  if($('#benchmarkScalingStatus'))$('#benchmarkScalingStatus').textContent=suiteRunning?`Step ${suite.current_step||0} / ${suite.total_steps||0}`:(suite.completed_at?(suite.stop_requested?'Stopped':'Complete'):'Ready');

  const scaling=$('#benchmarkScalingList');
  if(scaling){
    const rows=Array.isArray(suite.results)?suite.results:[];
    scaling.innerHTML=rows.length?rows.map(row=>`<div class="benchmark-scaling-row"><span>${escapeHtml(row.workers)} worker${Number(row.workers)===1?'':'s'}</span><strong>${formatHashrate(Number(row.average_hashrate||0))}</strong><em>${Number(row.scaling_efficiency_percent||0).toFixed(1)}% efficient</em></div>`).join(''):'<div class="benchmark-empty">No scaling run yet.</div>';
  }
  const body=$('#benchmarkHistoryBody');
  if(body){
    const rows=Array.isArray(lab.history)?lab.history:[];
    body.innerHTML=rows.length?rows.map(row=>`<tr><td>${escapeHtml(benchmarkTimeLabel(row.timestamp))}</td><td>${escapeHtml(row.label||'Benchmark')}</td><td>${Number(row.workers||0)}</td><td>${formatHashrate(Number(row.average_hashrate||0))}</td><td>${formatHashrate(Number(row.peak_hashrate||0))}</td><td>${Number(row.stability_percent||0).toFixed(1)}%</td><td><strong>${Number(row.score||0).toFixed(2)}</strong></td><td>${Number(row.scaling_efficiency_percent||0)>0?`${Number(row.scaling_efficiency_percent).toFixed(1)}%`:'—'}</td></tr>`).join(''):'<tr><td colspan="8">No benchmark results yet.</td></tr>';
  }
}
async function refreshBenchmarkLab(show=false){
  if(!apiReady||!bridgeAvailable('get_benchmark_lab'))return;
  try{
    const r=await callApi('get_benchmark_lab');
    if(r?.ok&&r.benchmark_lab){renderBenchmarkLab(r.benchmark_lab);if(show)showToast('Benchmark Lab refreshed')}
  }catch(e){console.error('Benchmark Lab refresh:',e)}
}

function renderState(s){
  lastState=s;renderSecurity(s.security||{});renderArchitecture(s.architecture||architectureState,s.workspace||workspaceState);history.push(Number(s.hashrate||0));if(history.length>80)history.shift();
  $('#heroHashrate').textContent=s.hashrate_text;$('#heroAccepted').textContent=s.accepted;$('#heroDifficulty').textContent=s.difficulty_text;$('#heroUptime').textContent=s.uptime_text;
  $('#modeEyebrow').textContent=`${s.mode} · ${String(s.status).toUpperCase()}`;$('#profileStatus').textContent=s.status;$('#engineOnline').textContent=`● ${s.status}`;$('#engineCopy').textContent=s.endpoint;
  $('#enginePrimary').textContent=s.miner_running?'Stop Mining →':'Start Mining →';$('#quickMining').innerHTML=s.miner_running?'<span>₿</span>Stop Mining':'<span>₿</span>Start Mining';$('#quickBenchmark').innerHTML=s.benchmark_running?'<span>◇</span>Stop Benchmark':'<span>◇</span>Start Benchmark';$('#quickLocalPool').innerHTML=s.local_pool_running?'<span>⌁</span>Stop Local Test Pool':'<span>⌁</span>Local Test Pool';
  $('#enginePrimary').disabled=!s.miner_running&&!securityTrusted;$('#quickMining').disabled=!s.miner_running&&!securityTrusted;
  $('#sideHealth').textContent=`${s.health}%`;$('#gaugeValue').textContent=`${s.health}%`;$('#healthGauge').style.setProperty('--value',s.health);$('#gaugeLabel').textContent=s.health>=90?'Optimal':s.health>=70?'Good':'Attention';$('#liveStatus').textContent=`● ${s.status}`;
  const avgRatio=s.hashrate>0?Math.min(100,s.avg_hashrate/s.hashrate*100):0;$('#meterAvgText').textContent=`${avgRatio.toFixed(0)}%`;$('#meterAvg').style.width=`${avgRatio}%`;$('#meterAcceptanceText').textContent=s.acceptance_text==='—'?'0%':s.acceptance_text;$('#meterAcceptance').style.width=`${Math.min(100,s.acceptance||0)}%`;
  $('#meterSharesText').textContent=s.submitted;$('#meterShares').style.width=`${Math.min(100,s.submitted*5)}%`;$('#meterWorkersText').textContent=s.workers;$('#meterWorkers').style.width=`${Math.min(100,s.workers/16*100)}%`;
  $('#sessionEndpoint').textContent=s.endpoint;$('#sessionMode').textContent=s.mode;$('#sessionJob').textContent=s.job;$('#sessionLatency').textContent=s.latency_text;$('#sessionHashes').textContent=Number(s.total_hashes).toLocaleString();$('#sessionWorkers').textContent=`${s.workers} workers`;$('#sessionEta').textContent=s.expected_share_text;$('#sessionAcceptance').textContent=s.acceptance_text;
  $('#sysCores').textContent=s.system.cpu_cores;$('#sysSubmitted').textContent=s.submitted;$('#sysRejected').textContent=s.rejected;$('#alertCount').textContent=s.rejected+s.stale;
  $('#poolStart').disabled=s.miner_running||!securityTrusted;$('#poolStop').disabled=!s.miner_running;$('#poolReset').disabled=s.miner_running;$('#localPoolToggle').textContent=s.local_pool_running?'Stop Local Test Pool':'Start Local Test Pool';
  const logSig=lightweightSignature(s.logs||[]);
  if(!performancePlusEnabled||logSig!==lastLogSignature){
    lastLogSignature=logSig;
    renderActivity(s.logs);renderLogs(s.logs);
  }
  const asicSig=lightweightSignature((s.asic_devices||[]).map(d=>[d.ip,d.status,d.hashrate_hs,d.temperature_c,d.health,d.alias,d.solo_assigned,d.solo_connected,d.pool_url]));
  if(!performancePlusEnabled||asicSig!==lastAsicSignature){
    lastAsicSignature=asicSig;
    renderAsics(s.asic_devices||[]);
  }
  renderPoolProfiles(s.pool_profiles||poolProfilesState||{});renderPoolPowerTools(s.pool_powertools||{},s.recent_shares||[]);renderCoreSetup(s.core_setup||{});renderCore(s.bitcoin_core||{});renderTemplate(s.block_template||{});renderCoinbase(s.coinbase||{});renderSolo(s.solo_mining||{});renderSubmission(s.block_submission||{});renderRegtest(s.regtest_lab||{});renderAsicSoloBridge(s.asic_solo_bridge||{});
  renderAnalyticsStatus(s.analytics||{});if($('#view-monitoring')?.classList.contains('active'))refreshAnalytics(false);
  renderReleaseCandidate(s.release_candidate||{});
  if(s.update_release_center)renderUpdateReleaseCenter(s.update_release_center,s.security||{});
  if(s.diagnostics_center)renderDiagnosticsCenter(s.diagnostics_center);
  if(s.mining_assistant)renderMiningAssistant(s.mining_assistant);
  if(s.hardware_compatibility)renderHardwareCompatibility(s.hardware_compatibility);
  if(s.tray)renderTrayState(s.tray);
  if(s.benchmark_lab)renderBenchmarkLab(s.benchmark_lab);
  stateRenderCount+=1;
  if(!performancePlusEnabled||stateRenderCount%2===0)drawCharts();
  if(s.performance_plus&&typeof s.performance_plus.enabled==='boolean'&&s.performance_plus.enabled!==performancePlusEnabled){
    applyPerformancePlus(s.performance_plus.enabled);
  }
}

const ASSISTANT_CARD_LABELS={cpu:'THIS PC',pool:'POOL',core:'BITCOIN CORE',asic:'ASIC',solo:'SOLO',security:'SECURITY'};
function renderMiningAssistant(state){
  if(!state)return;
  miningAssistantState=state;
  const goalReady=state.goal_readiness||{};
  if($('#assistantHeroGoal'))$('#assistantHeroGoal').textContent=state.goal_heading||String(state.goal_name||'CAN I MINE?').toUpperCase();
  if($('#assistantOverall'))$('#assistantOverall').textContent=state.goal_status_label||state.overall||'CHECKING';
  if($('#assistantSummary'))$('#assistantSummary').textContent=`${state.goal_status_detail||state.goal_description||''} ${state.mainnet_note||''}`.trim();
  const score=Math.max(0,Math.min(100,Number(state.score||0)));
  if($('#assistantScore'))$('#assistantScore').textContent=`${score}/100`;
  if($('#assistantScoreBar'))$('#assistantScoreBar').style.width=`${score}%`;
  if($('#assistantGoalName'))$('#assistantGoalName').textContent=state.goal_name||'Learn & Test';
  if($('#assistantPathGoal'))$('#assistantPathGoal').textContent=String(state.goal_name||'').toUpperCase();
  if($('#assistantDisclaimer'))$('#assistantDisclaimer').textContent=state.disclaimer||'';
  if($('#assistantMainnetNote'))$('#assistantMainnetNote').textContent=state.mainnet_note||'';

  $$('.assistant-goal').forEach(button=>button.classList.toggle('active',button.dataset.assistantGoal===state.goal));

  const readiness=state.readiness||{};
  Object.keys(ASSISTANT_CARD_LABELS).forEach(key=>{
    const card=$(`.assistant-ready-card[data-assistant-key="${key}"]`);
    const item=readiness[key];
    if(!card||!item)return;
    card.dataset.status=item.status||'setup';
    const strong=card.querySelector('strong');if(strong)strong.textContent=item.label||'—';
    const p=card.querySelector('p');if(p)p.textContent=item.detail||'';
    const route=card.querySelector('button');
    if(route){route.dataset.assistantRoute=item.route||'dashboard';route.textContent=item.action||'Open'}
  });

  const cpu=readiness.cpu?.meta||{};
  if($('#assistantCpuName'))$('#assistantCpuName').textContent=cpu.name||'CPU';
  if($('#assistantCpuThreads'))$('#assistantCpuThreads').textContent=cpu.threads??'—';
  if($('#assistantArch'))$('#assistantArch').textContent=cpu.architecture||'—';
  if($('#assistantPython'))$('#assistantPython').textContent=cpu.python||'—';

  const steps=$('#assistantSteps');
  if(steps){
    const rows=state.steps||[];
    steps.innerHTML=rows.length?rows.map(step=>`
      <div class="assistant-step">
        <span>${escapeHtml(step.index)}</span>
        <div><strong>${escapeHtml(step.title)}</strong><p>${escapeHtml(step.detail)}</p></div>
        <button type="button" data-assistant-route="${escapeHtml(step.route)}">${escapeHtml(step.action)}</button>
      </div>`).join(''):'<div class="empty-state">No recommended steps were returned. Run Guided Check to refresh readiness.</div>';
  }
  if($('#assistantComplete')&&bootstrap?.config)$('#assistantComplete').textContent=bootstrap.config.mining_assistant_completed?'Setup Reviewed ✓':'Mark Setup Reviewed';
}
async function refreshMiningAssistant(logged=false){
  if(!bridgeAvailable(logged?'run_mining_assistant_check':'get_mining_assistant_state'))return;
  try{
    const goal=miningAssistantState?.goal||bootstrap?.config?.mining_assistant_goal||'learn';
    const r=logged?await callApi('run_mining_assistant_check',goal):await callApi('get_mining_assistant_state',goal);
    if(r?.assistant)renderMiningAssistant(r.assistant);
    if(logged&&r?.result)showToast(r.result);
  }catch(e){console.error('Mining Assistant refresh failed:',e);if(logged)showToast(`Mining Assistant: ${e.message}`)}
}
async function saveAssistantPrefs(payload={}){
  if(!bridgeAvailable('save_mining_assistant_preferences'))return null;
  const r=await callApi('save_mining_assistant_preferences',payload.goal??null,payload.intro_seen??null,payload.completed??null);
  if(bootstrap?.config){
    if(r.goal!==undefined)bootstrap.config.mining_assistant_goal=r.goal;
    if(r.intro_seen!==undefined)bootstrap.config.mining_assistant_intro_seen=!!r.intro_seen;
    if(r.completed!==undefined)bootstrap.config.mining_assistant_completed=!!r.completed;
  }
  return r;
}
function maybeShowAssistantIntro(){
  const intro=$('#assistantIntro');
  if(intro&&bootstrap?.config&&!bootstrap.config.mining_assistant_intro_seen)intro.hidden=false;
}


function profitNum(id,fallback=0){
  const el=$(id);const value=Number(el?.value);
  return Number.isFinite(value)?value:fallback;
}
function profitInputs(){
  const multiplier=profitNum('#profitHashrateUnit',1e12);
  return {
    hashrate_hs:Math.max(0,profitNum('#profitHashrate',0)*multiplier),
    power_watts:Math.max(0,profitNum('#profitPowerWatts',0)),
    electricity_per_kwh:Math.max(0,profitNum('#profitElectricity',0.15)),
    pool_fee_percent:Math.max(0,Math.min(100,profitNum('#profitPoolFee',1))),
    btc_price:Math.max(0,profitNum('#profitBtcPrice',0)),
    difficulty:Math.max(0,profitNum('#profitDifficulty',0)),
    height:Math.max(0,Math.floor(profitNum('#profitHeight',0))),
    block_subsidy_btc:Math.max(0,profitNum('#profitSubsidy',3.125)),
    avg_fees_btc_per_block:Math.max(0,profitNum('#profitFees',0)),
  };
}
function money(v){
  const n=Number(v||0);const sign=n<0?'-':'';
  return `${sign}$${Math.abs(n).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}`;
}
function btc(v){
  const n=Number(v||0);
  if(n===0)return '0 BTC';
  if(Math.abs(n)<0.000001)return `${n.toExponential(3)} BTC`;
  return `${n.toLocaleString(undefined,{maximumFractionDigits:8})} BTC`;
}
function pctProb(v){
  const n=Math.max(0,Math.min(1,Number(v||0)));
  if(n===0)return '0%';
  if(n<0.000001)return `${(n*100).toExponential(3)}%`;
  if(n<0.01)return `${(n*100).toFixed(6)}%`;
  return `${(n*100).toFixed(3)}%`;
}
function durationLong(seconds){
  const n=Number(seconds);
  if(!Number.isFinite(n)||n<=0)return '—';
  const years=n/(365.25*86400);
  if(years>=1e6)return `${years.toExponential(3)} years`;
  if(years>=1)return `${years.toLocaleString(undefined,{maximumFractionDigits:2})} years`;
  const days=n/86400;if(days>=1)return `${days.toLocaleString(undefined,{maximumFractionDigits:2})} days`;
  const hours=n/3600;if(hours>=1)return `${hours.toFixed(2)} hours`;
  return `${Math.max(1,n/60).toFixed(1)} min`;
}
function renderProfitability(calc){
  if(!calc)return;
  profitabilityState=calc;
  const fin=calc.financial||{},power=calc.power||{},mining=calc.mining||{},network=calc.network||{};
  if($('#profitNetDay')){
    $('#profitNetDay').textContent=money(fin.net_day);
    $('#profitNetDay').classList.toggle('profit-positive',Number(fin.net_day)>0);
    $('#profitNetDay').classList.toggle('profit-negative',Number(fin.net_day)<0);
  }
  if($('#profitBtcDay'))$('#profitBtcDay').textContent=btc(mining.net_btc_day);
  if($('#profitPowerDay'))$('#profitPowerDay').textContent=money(power.electricity_day);
  if($('#profitBreakEven'))$('#profitBreakEven').textContent=power.break_even_electricity_per_kwh==null?'— / kWh':`${money(power.break_even_electricity_per_kwh)} / kWh`;
  if($('#profitEfficiency'))$('#profitEfficiency').textContent=power.efficiency_w_per_th==null?'— W/TH':`${Number(power.efficiency_w_per_th).toFixed(2)} W/TH`;
  if($('#profitKwhDay'))$('#profitKwhDay').textContent=`${Number(power.kwh_day||0).toFixed(2)} kWh`;
  if($('#profitElectricityDay'))$('#profitElectricityDay').textContent=money(power.electricity_day);
  if($('#profitElectricityMonth'))$('#profitElectricityMonth').textContent=money(power.electricity_month);
  if($('#profitRevenueDay'))$('#profitRevenueDay').textContent=money(fin.revenue_after_pool_day);
  if($('#profitNetMonth'))$('#profitNetMonth').textContent=money(fin.net_month);
  if($('#profitNetYear'))$('#profitNetYear').textContent=money(fin.net_year);
  if($('#profitBlocksDay'))$('#profitBlocksDay').textContent=Number(mining.expected_blocks_per_day||0).toExponential(4);
  if($('#profitGrossBtc'))$('#profitGrossBtc').textContent=btc(mining.gross_btc_day);
  if($('#profitAfterFeeBtc'))$('#profitAfterFeeBtc').textContent=btc(mining.net_btc_day);
  if($('#profitNetworkShare'))$('#profitNetworkShare').textContent=pctProb(network.miner_share);
  if($('#profitMeanBlock'))$('#profitMeanBlock').textContent=durationLong(mining.mean_time_to_block_seconds);
  if($('#profitP50Block'))$('#profitP50Block').textContent=durationLong(mining.probability_50_seconds);
  const odds=mining.solo_probability||{};
  if($('#profitOdds1h'))$('#profitOdds1h').textContent=pctProb(odds['1h']);
  if($('#profitOdds24h'))$('#profitOdds24h').textContent=pctProb(odds['24h']);
  if($('#profitOdds7d'))$('#profitOdds7d').textContent=pctProb(odds['7d']);
  if($('#profitOdds30d'))$('#profitOdds30d').textContent=pctProb(odds['30d']);
  if($('#profitOdds365d'))$('#profitOdds365d').textContent=pctProb(odds['365d']);
  if($('#profitDisclaimer'))$('#profitDisclaimer').textContent=calc.disclaimer||'';
  if($('#profitHeroNote')){
    $('#profitHeroNote').textContent=Number(calc.inputs?.btc_price||0)<=0
      ?'BTC price is 0. Enter a manual price to estimate fiat revenue. Network/mining math is still calculated.'
      :'Estimated from your current assumptions. Actual results can differ materially.';
  }
}
async function calculateProfitability(show=true){
  const i=profitInputs();
  const r=await callApi(
    'calculate_profitability',
    i.hashrate_hs,i.power_watts,i.electricity_per_kwh,i.pool_fee_percent,
    i.btc_price,i.difficulty,i.block_subsidy_btc,i.avg_fees_btc_per_block
  );
  if(!r?.ok)throw new Error(r?.error||'Calculation failed');
  renderProfitability(r.calculation);
  if(show)showToast('Profitability estimate recalculated');
  return r.calculation;
}
function loadProfitInputs(defaults){
  if(!defaults)return;
  const hs=Number(defaults.hashrate_hs||0);
  const choices=[[1e15,'1e15'],[1e12,'1e12'],[1e9,'1e9'],[1e6,'1e6'],[1e3,'1e3']];
  let unit=1e12;
  for(const [value] of choices){if(hs>=value){unit=value;break}}
  if($('#profitHashrateUnit'))$('#profitHashrateUnit').value=String(unit);
  if($('#profitHashrate'))$('#profitHashrate').value=hs?String(hs/unit):'0';
  if($('#profitPowerWatts'))$('#profitPowerWatts').value=defaults.power_watts??0;
  if($('#profitElectricity'))$('#profitElectricity').value=defaults.electricity_per_kwh??0.15;
  if($('#profitPoolFee'))$('#profitPoolFee').value=defaults.pool_fee_percent??1;
  if($('#profitBtcPrice'))$('#profitBtcPrice').value=defaults.btc_price??0;
  if($('#profitDifficulty'))$('#profitDifficulty').value=defaults.difficulty??0;
  if($('#profitHeight'))$('#profitHeight').value=defaults.height??0;
  if($('#profitSubsidy'))$('#profitSubsidy').value=defaults.block_subsidy_btc??3.125;
  if($('#profitFees'))$('#profitFees').value=defaults.avg_fees_btc_per_block??0;
  if($('#profitCoreBadge'))$('#profitCoreBadge').textContent=defaults.core_connected?'CORE DATA':'MANUAL';
}
async function refreshProfitabilityState(){
  if(!bridgeAvailable('get_profitability_state'))return;
  try{
    const r=await callApi('get_profitability_state');
    if(!r?.ok)throw new Error(r?.error||'Could not load profitability state');
    loadProfitInputs(r.defaults);
    await calculateProfitability(false);
  }catch(e){console.error('Profitability state:',e)}
}
async function useCoreProfitabilityData(){
  const r=await callApi('use_core_profitability_data');
  if(!r?.ok)throw new Error(r?.error||'Bitcoin Core data unavailable');
  if($('#profitDifficulty'))$('#profitDifficulty').value=r.difficulty;
  if($('#profitHeight'))$('#profitHeight').value=r.height;
  if($('#profitSubsidy'))$('#profitSubsidy').value=r.block_subsidy_btc;
  if($('#profitCoreBadge'))$('#profitCoreBadge').textContent=`CORE · ${String(r.chain||'').toUpperCase()}`;
  await calculateProfitability(false);
  showToast(r.result||'Loaded Bitcoin Core network data');
}


function hardwareCapabilityChip(label,on){
  return `<span class="hardware-chip ${on?'on':''}">${on?'✓':'—'} ${escapeHtml(label)}</span>`;
}
function hardwareMatches(row){
  const query=String($('#hardwareSearch')?.value||'').trim().toLowerCase();
  const status=String($('#hardwareStatusFilter')?.value||'all');
  if(status!=='all'&&row.status_key!==status)return false;
  if(!query)return true;
  const text=[
    row.vendor,row.model,row.firmware,row.family,row.family_vendor,row.compatibility_level,
    ...(row.evidence||[])
  ].join(' ').toLowerCase();
  return text.includes(query);
}
function renderHardwareCompatibility(state){
  if(!state)return;
  hardwareCompatibilityState=state;
  const summary=state.summary||{};
  if($('#hardwareConfirmed'))$('#hardwareConfirmed').textContent=summary.confirmed_asics??0;
  if($('#hardwareVerified'))$('#hardwareVerified').textContent=summary.verified_runtime??0;
  if($('#hardwareFullControl'))$('#hardwareFullControl').textContent=summary.full_control??0;
  if($('#hardwareNotPromoted'))$('#hardwareNotPromoted').textContent=summary.not_promoted??0;
  if($('#hardwareHeroTitle'))$('#hardwareHeroTitle').textContent=summary.confirmed_asics
    ?`${summary.confirmed_asics} CONFIRMED ASIC${summary.confirmed_asics===1?'':'S'}`
    :'NO VERIFIED HARDWARE YET';
  if($('#hardwareHeroText'))$('#hardwareHeroText').textContent=summary.confirmed_asics
    ?`${summary.verified_runtime||0} verified at runtime · ${summary.full_control||0} with the complete currently verified control set. Capability buttons elsewhere remain evidence-gated.`
    :'No positively identified ASIC is currently active in the fleet. This page does not run a LAN scan; use authorized ASIC Control discovery when needed.';

  const list=$('#hardwareDeviceList');
  if(list){
    const rows=(state.devices||[]).filter(hardwareMatches);
    list.innerHTML=rows.length?rows.map(row=>{
      const name=row.alias?`${row.alias} · ${row.model}`:row.model;
      const family=row.family&&row.family!=='Unknown'?`${row.family_vendor||''} ${row.family}`.trim():'Family unknown';
      const caps=row.capabilities||{};
      const evidence=(row.evidence||[]).join(' · ');
      return `<article class="hardware-device-card" data-status="${escapeHtml(row.status_key||'not_promoted')}">
        <div class="hardware-device-icon">◈</div>
        <div class="hardware-device-main">
          <small>${escapeHtml(row.vendor||'UNKNOWN VENDOR')}</small>
          <h3>${escapeHtml(name||'Unknown device')}</h3>
          <p>${escapeHtml(family)}${row.firmware?` · ${escapeHtml(row.firmware)}`:''}</p>
          <span class="hardware-level">${escapeHtml(row.compatibility_level||'NOT PROMOTED')}</span>
        </div>
        <div class="hardware-evidence">
          <strong>EVIDENCE</strong>
          <p>${escapeHtml(evidence)}</p>
          <small>${escapeHtml(row.explanation||'')}</small>
        </div>
        <div class="hardware-capabilities">
          <strong>CAPABILITIES VERIFIED NOW</strong>
          <div class="hardware-chip-row">
            ${hardwareCapabilityChip('Monitoring',!!caps.monitoring)}
            ${hardwareCapabilityChip('Web UI',!!caps.web_ui)}
            ${hardwareCapabilityChip('Pool Control',!!caps.pool_control)}
            ${hardwareCapabilityChip('Restart',!!caps.restart)}
            ${hardwareCapabilityChip('Solo Bridge',!!caps.solo_bridge)}
          </div>
        </div>
      </article>`;
    }).join(''):'<div class="hardware-empty glass">No hardware matches the current filter.</div>';
  }

  const families=$('#hardwareFamilyGrid');
  if(families){
    const familyRows=Array.isArray(state.families)?state.families:[];
    families.innerHTML=familyRows.map(f=>{
      const rawExamples=f?.examples;
      const examples=Array.isArray(rawExamples)
        ?rawExamples
        :(rawExamples==null||rawExamples===''?[]:[String(rawExamples)]);
      return `<article class="hardware-family-card">
        <small>${escapeHtml(f?.vendor||'')}</small>
        <h3>${escapeHtml(f?.family||'')}</h3>
        <div class="hardware-examples">${examples.map(x=>`<span>${escapeHtml(x)}</span>`).join('')}</div>
        <p><strong>Recognition:</strong> ${escapeHtml(f?.recognition||'')}</p>
        <p>${escapeHtml(f?.notes||'')}</p>
      </article>`;
    }).join('');
  }
}
async function refreshHardwareCompatibility(show=false){
  if(!bridgeAvailable('get_hardware_compatibility_state'))return;
  try{
    const r=await callApi('get_hardware_compatibility_state');
    if(!r?.ok)throw new Error(r?.error||'Could not load hardware compatibility');
    renderHardwareCompatibility(r.compatibility);
    if(show)showToast('Hardware Compatibility Center refreshed from current fleet state');
  }catch(e){console.error('Hardware compatibility:',e);if(show)showToast(`Hardware Compatibility: ${e.message}`)}
}

async function pollPurpleDragonStartup(){
  if(!bridgeAvailable('get_security_state'))return;
  const started=Date.now();
  while(apiInitialized && Date.now()-started<30000){
    try{
      const r=await window.pywebview.api.get_security_state();
      if(r?.security){
        renderSecurity(r.security);
        if(r.security.checked)return;
      }
    }catch(e){
      console.error('Purple Dragon startup poll warning:',e);
    }
    await new Promise(resolve=>setTimeout(resolve,300));
  }
  if(!securityChecked){
    const box=$('#securityResult');
    if(box)box.textContent='Purple Dragon verification did not complete within 30 seconds. Use Verify Build Now or check startup-bridge.log.';
  }
}

async function refreshState(){
  if(!apiReady || refreshInFlight || !bridgeAvailable('get_state'))return;
  refreshInFlight=true;
  try{
    renderState(await callApi('get_state'));
  }catch(e){
    console.error(e);
  }finally{
    refreshInFlight=false;
  }
}

function scheduleStateRefresh(delay=null){
  if(refreshTimer)clearTimeout(refreshTimer);
  const actualDelay=delay==null?currentRefreshDelay():delay;
  refreshTimer=setTimeout(async()=>{
    refreshTimer=null;
    await refreshState();
    if(apiInitialized)scheduleStateRefresh(currentRefreshDelay());
  },actualDelay);
}


if($('#traySave'))$('#traySave').addEventListener('click',async()=>{
  const box=$('#trayResult'),button=$('#traySave');button.disabled=true;box.textContent='Saving Windows tray settings...';
  try{const r=await callApi('save_tray_settings',traySettingsPayload());if(!r?.ok)throw new Error(r?.error||'Could not save tray settings');renderTrayState(r.tray);box.textContent=r.result||'Tray settings saved.';showToast('Tray settings saved')}catch(e){box.textContent=`ERROR: ${e.message}`;showToast(e.message)}finally{button.disabled=false}
});
if($('#trayRefresh'))$('#trayRefresh').addEventListener('click',()=>refreshTrayState(true));
if($('#trayHideNow'))$('#trayHideNow').addEventListener('click',async()=>{try{const r=await callApi('hide_to_tray');if(!r?.ok)throw new Error(r?.error||'Could not hide to tray');renderTrayState(r.tray)}catch(e){showToast(e.message)}});
if($('#trayTestNotification'))$('#trayTestNotification').addEventListener('click',async()=>{const box=$('#trayResult');try{const r=await callApi('test_tray_notification');if(!r?.ok)throw new Error(r?.error||'Notification test failed');renderTrayState(r.tray);box.textContent=r.result||'Test notification sent.';showToast('Tray notification sent')}catch(e){box.textContent=`ERROR: ${e.message}`;showToast(e.message)}});

if($('#academyRefresh'))$('#academyRefresh').addEventListener('click',()=>refreshMiningAcademy(true));
if($('#academyReset'))$('#academyReset').addEventListener('click',async()=>{if(!confirm('Reset all local Mining Academy lesson, lab and quiz progress?'))return;const box=$('#academyResult');try{const r=await callApi('reset_academy_progress');if(!r?.ok)throw new Error(r?.error||'Could not reset Academy');renderMiningAcademy(r.academy);if(box)box.textContent=r.result||'Academy progress reset.';showToast('Mining Academy progress reset')}catch(e){if(box)box.textContent=`ERROR: ${e.message}`}});
if($('#academyLessonList'))$('#academyLessonList').addEventListener('click',e=>{const button=e.target.closest('[data-lesson-id]');if(button)academySelectLesson(button.dataset.lessonId)});
if($('#academyFilters'))$('#academyFilters').addEventListener('click',e=>{const button=e.target.closest('[data-academy-filter]');if(!button)return;academyFilter=button.dataset.academyFilter||'all';$$('#academyFilters button').forEach(x=>x.classList.toggle('active',x===button));renderAcademyLessonList()});
if($('#academyStartLesson'))$('#academyStartLesson').addEventListener('click',()=>academySetStatus('in_progress'));
if($('#academyCompleteLesson'))$('#academyCompleteLesson').addEventListener('click',()=>academySetStatus('completed'));
if($('#academyQuizChoices'))$('#academyQuizChoices').addEventListener('click',async e=>{const button=e.target.closest('[data-academy-answer]');if(!button)return;const box=$('#academyQuizResult');$$('#academyQuizChoices button').forEach(x=>x.disabled=true);try{const r=await callApi('submit_academy_quiz',academyCurrentLessonId,Number(button.dataset.academyAnswer));if(!r?.ok)throw new Error(r?.error||'Quiz could not be checked');renderMiningAcademy(r.academy);const correct=!!r.quiz?.correct;if(box)box.textContent=`${correct?'Correct ✓':'Not quite'} — ${r.quiz?.explanation||''}`;showToast(correct?'Knowledge check passed':'Try the knowledge check again')}catch(err){if(box)box.textContent=`ERROR: ${err.message}`}finally{$$('#academyQuizChoices button').forEach(x=>x.disabled=false)}});
$$('[data-academy-lesson]').forEach(button=>button.addEventListener('click',()=>{pendingAcademyLesson=button.dataset.academyLesson||'';setView('academy');if(miningAcademyState)academySelectLesson(pendingAcademyLesson,{scroll:true})}));
if($('#academyHashRun'))$('#academyHashRun').addEventListener('click',async()=>{const button=$('#academyHashRun'),box=$('#academyResult');button.disabled=true;try{const r=await callApi('run_academy_hash_lab',$('#academyHashInput').value);if(!r?.ok)throw new Error(r?.error||'Hash Lab failed');$('#academySha256').textContent=r.lab.sha256||'—';$('#academySha256d').textContent=r.lab.sha256d||'—';renderMiningAcademy(r.academy);box.textContent=`Hash Explorer completed locally · ${r.lab.input_utf8_bytes} UTF-8 byte(s).`}catch(e){box.textContent=`ERROR: ${e.message}`}finally{button.disabled=false}});
if($('#academyDifficultyRun'))$('#academyDifficultyRun').addEventListener('click',async()=>{const button=$('#academyDifficultyRun'),box=$('#academyResult');button.disabled=true;try{const r=await callApi('run_academy_difficulty_lab',{difficulty:Number($('#academyDifficulty').value||1),bits:$('#academyBits').value.trim()});if(!r?.ok)throw new Error(r?.error||'Difficulty Lab failed');$('#academyDifficultyOut').textContent=Number(r.lab.difficulty||0).toLocaleString(undefined,{maximumSignificantDigits:12});$('#academyTargetOut').textContent=r.lab.target||'—';renderMiningAcademy(r.academy);box.textContent=`Difficulty & Target Lab completed using ${r.lab.source}.`}catch(e){box.textContent=`ERROR: ${e.message}`}finally{button.disabled=false}});
if($('#academyHeaderRun'))$('#academyHeaderRun').addEventListener('click',async()=>{const button=$('#academyHeaderRun'),box=$('#academyResult');button.disabled=true;try{const r=await callApi('run_academy_header_lab',academyHeaderPayload());if(!r?.ok)throw new Error(r?.error||'Block Header Lab failed');$('#academyHeaderHex').textContent=r.lab.header_hex||'—';$('#academyHeaderHash').textContent=r.lab.hash||'—';$('#academyHeaderTarget').textContent=r.lab.target||'—';$('#academyHeaderValid').textContent=r.lab.valid_pow?'VALID · HASH ≤ TARGET':'INVALID · HASH > TARGET';$('#academyHeaderValid').dataset.valid=r.lab.valid_pow?'yes':'no';renderMiningAcademy(r.academy);box.textContent=`Block Header Lab completed · ${r.lab.header_bytes} bytes serialized.`}catch(e){box.textContent=`ERROR: ${e.message}`}finally{button.disabled=false}});
if($('#academyMerkleRun'))$('#academyMerkleRun').addEventListener('click',async()=>{const button=$('#academyMerkleRun'),box=$('#academyResult');button.disabled=true;try{const txids=$('#academyMerkleTxids').value.split(/\n|,/).map(x=>x.trim()).filter(Boolean);const r=await callApi('run_academy_merkle_lab',txids);if(!r?.ok)throw new Error(r?.error||'Merkle Lab failed');$('#academyMerkleRoot').textContent=r.lab.merkle_root||'—';$('#academyMerkleLevels').innerHTML=(r.lab.levels||[]).map((level,i)=>`<div><strong>Level ${i}</strong><span>${level.map(x=>`<code>${escapeHtml(x)}</code>`).join('')}</span></div>`).join('');renderMiningAcademy(r.academy);box.textContent=`Merkle Tree Lab completed with ${r.lab.transaction_count} transaction ID(s).`}catch(e){box.textContent=`ERROR: ${e.message}`}finally{button.disabled=false}});
if($('#academyNonceRun'))$('#academyNonceRun').addEventListener('click',async()=>{const button=$('#academyNonceRun'),box=$('#academyResult');button.disabled=true;$('#academyNonceStatus').textContent='SEARCHING…';try{const r=await callApi('run_academy_nonce_lab',{seed:$('#academyNonceSeed').value,zero_nibbles:Number($('#academyNonceZeros').value||3),max_attempts:Number($('#academyNonceAttempts').value||100000)});if(!r?.ok)throw new Error(r?.error||'Nonce Lab failed');$('#academyNonceStatus').textContent=r.lab.found?`FOUND · TARGET PREFIX ${r.lab.target_prefix}`:`NOT FOUND · BEST RESULT SHOWN`;$('#academyNonceHash').textContent=r.lab.hash||r.lab.best_hash||'—';$('#academyNonceCount').textContent=Number(r.lab.attempts||0).toLocaleString();$('#academyNonceRate').textContent=formatHashrate(Number(r.lab.hashrate||0));$('#academyNonceValue').textContent=r.lab.found?Number(r.lab.nonce).toLocaleString():(r.lab.best_nonce==null?'—':Number(r.lab.best_nonce).toLocaleString());renderMiningAcademy(r.academy);box.textContent=r.lab.note||'Educational nonce simulation completed.'}catch(e){$('#academyNonceStatus').textContent='ERROR';box.textContent=`ERROR: ${e.message}`}finally{button.disabled=false}});

async function init(){
  if(apiInitialized)return;
  if(!bridgeAvailable('get_bootstrap')){
    setBridgeUiState(false);
    scheduleBridgeRetry();
    return;
  }

  apiInitialized=true;
  setBridgeUiState(true);

  try{
    bootstrap=await window.pywebview.api.get_bootstrap();
    initFields(bootstrap);

    // At this point the bridge is definitely usable. Only now start filesystem,
    // RPC, integrity, Regtest and fleet background work.
    if(bridgeAvailable('start_background_services')){
      try{await window.pywebview.api.start_background_services()}catch(serviceError){console.error('Background service startup warning:',serviceError)}
    }

    // v0.7.0.1: security verification has its own lightweight polling path.
    // A problem rendering another dashboard panel can no longer leave Purple
    // Dragon permanently showing the static CHECKING state.
    pollPurpleDragonStartup();

    bridgeRetryCount=0;
    await refreshState();
    maybeShowAssistantIntro();
    scheduleStateRefresh(currentRefreshDelay());
  }catch(e){
    apiInitialized=false;
    setBridgeUiState(false);
    console.error('Python bridge initialization failed:',e);
    const box=$('#coreSetupResult');
    if(box)box.textContent=`Backend initialization retrying: ${e.message}`;
    const securityBox=$('#securityResult');
    if(securityBox)securityBox.textContent=`Backend initialization retrying: ${e.message}`;
    scheduleBridgeRetry();
  }
}

// Listen on both targets for pywebview renderer/version compatibility.
window.addEventListener('pywebviewready',init);
document.addEventListener('pywebviewready',init);
if(bridgeAvailable('get_bootstrap'))init();else scheduleBridgeRetry();
document.addEventListener('visibilitychange',()=>{
  if(apiInitialized)scheduleStateRefresh(currentRefreshDelay());
});
async function runDiagnosticsUi(mode){
  const box=$('#diagnosticsResult');
  const quick=$('#diagnosticsQuickRun'),full=$('#diagnosticsFullRun');
  if(quick)quick.disabled=true;if(full)full.disabled=true;
  if(box)box.textContent=`Running ${mode==='full'?'full diagnostic':'quick scan'} locally...`;
  try{
    const r=await callApi('run_diagnostics',mode);
    if(r?.diagnostics)renderDiagnosticsCenter(r.diagnostics);
    if(box)box.textContent=r.report||r.error||'Diagnostics completed.';
    const health=r?.diagnostics?.health||'COMPLETE';
    showToast(`Diagnostics: ${health}`);
  }catch(e){if(box)box.textContent=`ERROR: ${e.message}`}
  finally{if(quick)quick.disabled=false;if(full)full.disabled=false}
}
$('#diagnosticsQuickRun').addEventListener('click',()=>runDiagnosticsUi('quick'));
$('#diagnosticsFullRun').addEventListener('click',()=>runDiagnosticsUi('full'));
$('#diagnosticsCopyReport').addEventListener('click',async()=>{
  const box=$('#diagnosticsResult');
  try{
    const r=await callApi('get_diagnostics_report');
    if(r?.diagnostics)renderDiagnosticsCenter(r.diagnostics);
    if(box)box.textContent=r.report||r.error||'No diagnostic report available.';
    if(r.report){
      try{await navigator.clipboard.writeText(r.report);showToast('Diagnostics report copied')}
      catch{showToast('Diagnostics report displayed below')}
    }
  }catch(e){if(box)box.textContent=`ERROR: ${e.message}`}
});
$('#diagnosticsCreateBundle').addEventListener('click',async()=>{
  const button=$('#diagnosticsCreateBundle'),box=$('#diagnosticsResult');
  button.disabled=true;if(box)box.textContent='Creating privacy-sanitized diagnostics bundle locally...';
  try{
    const payload={include_settings:!!$('#diagnosticsIncludeSettings')?.checked,include_activity_log:!!$('#diagnosticsIncludeActivity')?.checked};
    const r=await callApi('create_diagnostics_support_bundle',payload);
    if(!r?.ok)throw new Error(r?.error||'Support bundle creation failed');
    if(r.diagnostics)renderDiagnosticsCenter(r.diagnostics);
    if($('#diagnosticsBundlePath'))$('#diagnosticsBundlePath').textContent=r.path_display||r.path||'—';
    if($('#diagnosticsBundleSize'))$('#diagnosticsBundleSize').textContent=r.size_text||'—';
    if(box)box.textContent=`${r.result||'Support bundle created.'}\n\nPath: ${r.path_display||r.path||'—'}\nSize: ${r.size_text||'—'} · ${Number(r.entries||0)} files`;
    showToast('Diagnostics support bundle created locally');
  }catch(e){if(box)box.textContent=`ERROR: ${e.message}`}
  finally{button.disabled=false}
});
$('#diagnosticsOpenFolder').addEventListener('click',async()=>{
  const box=$('#diagnosticsResult');
  try{
    const r=await callApi('open_diagnostics_support_folder');
    if(!r?.ok)throw new Error(r?.error||'Could not open support folder');
    if(box)box.textContent=r.result||'Support folder opened.';showToast('Opened Diagnostics support folder');
  }catch(e){if(box)box.textContent=`ERROR: ${e.message}`}
});

$('#urChannel').addEventListener('change',async()=>{
  const box=$('#urResult');
  try{
    const r=await callApi('set_update_channel',$('#urChannel').value);
    if(!r?.ok)throw new Error(r?.error||'Could not change update channel');
    if(r.update_release)renderUpdateReleaseCenter(r.update_release,lastState?.security||{});
    if(box)box.textContent=`Update channel preference: ${String(r.update_release?.channel||'stable').toUpperCase()}. Automatic downloads and silent apply remain OFF.`;
    showToast('Update channel policy saved');
  }catch(e){if(box)box.textContent=`ERROR: ${e.message}`}
});
$('#urChoosePackage').addEventListener('click',async()=>{
  const box=$('#urResult');
  try{
    const r=await callApi('choose_update_package');
    if(!r?.ok)throw new Error(r?.error||'No package selected');
    $('#urPackagePath').value=r.path||'';if(box)box.textContent='Package selected. Click Inspect & Verify before staging.';
  }catch(e){if(box)box.textContent=`ERROR: ${e.message}`}
});
$('#urChooseFolder').addEventListener('click',async()=>{
  const box=$('#urResult');
  try{
    const r=await callApi('choose_update_folder');
    if(!r?.ok)throw new Error(r?.error||'No folder selected');
    $('#urPackagePath').value=r.path||'';if(box)box.textContent='Release folder selected. Click Inspect & Verify before staging.';
  }catch(e){if(box)box.textContent=`ERROR: ${e.message}`}
});
$('#urInspect').addEventListener('click',async()=>{
  const button=$('#urInspect'),box=$('#urResult');button.disabled=true;
  if(box)box.textContent='Inspecting package metadata, SHA-256, publisher signature, and protected-file hashes without executing candidate code...';
  try{
    const payload={path:$('#urPackagePath').value.trim(),sha256:$('#urExpectedSha').value.trim()};
    const r=await callApi('inspect_update_package',payload);
    if(r?.update_release)renderUpdateReleaseCenter(r.update_release,lastState?.security||{});
    if(box)box.textContent=r.report||r.error||'Package inspection complete.';
    showToast(r?.update_release?.inspection?.ok?'Trusted release verified':'Update package blocked');
  }catch(e){if(box)box.textContent=`ERROR: ${e.message}`}
  finally{button.disabled=false}
});
$('#urStage').addEventListener('click',async()=>{
  const button=$('#urStage'),box=$('#urResult');button.disabled=true;
  if(box)box.textContent='Copying the verified release into local staging and writing rollback metadata...';
  try{
    const r=await callApi('stage_update_package');
    if(!r?.ok)throw new Error(r?.error||'Could not stage update');
    if(r.state)renderUpdateReleaseCenter(r.state,lastState?.security||{});
    if(box)box.textContent=`Trusted release staged locally.\n\n${r.path||''}\nRollback plan: ${r.rollback_plan||''}\n\nThe running Bitcoin Miner Studio folder was not modified.`;
    showToast('Trusted release staged');
  }catch(e){if(box)box.textContent=`ERROR: ${e.message}`}
  finally{button.disabled=false}
});
$('#urClearStaged').addEventListener('click',async()=>{
  if(!confirm('Clear locally staged update packages and rollback-plan metadata? The active Bitcoin Miner Studio installation will not be changed.'))return;
  const box=$('#urResult');
  try{
    const r=await callApi('clear_staged_update');if(!r?.ok)throw new Error(r?.error||'Could not clear staging');
    if(r.state)renderUpdateReleaseCenter(r.state,lastState?.security||{});if(box)box.textContent='Local update staging cleared. The active application was not modified.';showToast('Update staging cleared');
  }catch(e){if(box)box.textContent=`ERROR: ${e.message}`}
});
$('#urOpenFolder').addEventListener('click',async()=>{
  const box=$('#urResult');try{const r=await callApi('open_update_staging_folder');if(!r?.ok)throw new Error(r?.error||'Could not open update folder');if(box)box.textContent=r.result||'Update folder opened.'}catch(e){if(box)box.textContent=`ERROR: ${e.message}`}
});
$('#urExportDescriptor').addEventListener('click',async()=>{
  const box=$('#urResult');try{const r=await callApi('export_release_descriptor');if(!r?.ok)throw new Error(r?.error||'Descriptor export failed');if(box)box.textContent=`Release descriptor exported locally:\n${r.path||'—'}`;showToast('Release descriptor exported')}catch(e){if(box)box.textContent=`ERROR: ${e.message}`}
});
$('#urCopyReport').addEventListener('click',async()=>{
  const box=$('#urResult');try{const r=await callApi('get_update_release_report');if(r?.update_release)renderUpdateReleaseCenter(r.update_release,lastState?.security||{});if(box)box.textContent=r.report||r.error||'No update report available.';if(r.report){try{await navigator.clipboard.writeText(r.report);showToast('Update report copied')}catch{showToast('Update report displayed below')}}}catch(e){if(box)box.textContent=`ERROR: ${e.message}`}
});

$('#rcPreflight').addEventListener('click',async()=>{
  const button=$('#rcPreflight'),box=$('#rcResult');
  button.disabled=true;box.textContent='Running Stable release preflight...';
  try{
    const r=await callApi('run_release_preflight');
    if(r.release_candidate)renderReleaseCandidate(r.release_candidate);
    box.textContent=r.report||(r.error?`RELEASE BLOCKED: ${r.error}`:'Preflight completed.');
    showToast(r.release_candidate?.blockers?'Release blockers detected':'Release preflight complete');
  }catch(e){box.textContent=`ERROR: ${e.message}`}
  finally{button.disabled=false}
});
$('#rcSupportBundle').addEventListener('click',async()=>{
  const button=$('#rcSupportBundle'),box=$('#rcResult');
  button.disabled=true;box.textContent='Creating privacy-sanitized support bundle locally...';
  try{
    const r=await handleResult(callApi('create_release_support_bundle'),'Local support bundle created');
    $('#rcSupportPath').textContent=r.path_display||r.path||'—';
    box.textContent=`${r.result}\n\nPath: ${r.path_display||r.path||'—'}\nSize: ${r.size_text||'—'}`;
    showToast('Support bundle created locally');
    await refreshReleaseCandidate();
  }catch(e){box.textContent=`ERROR: ${e.message}`}
  finally{button.disabled=false}
});
$('#rcCopyReport').addEventListener('click',async()=>{
  const box=$('#rcResult');
  try{
    const r=await callApi('get_release_candidate_report');
    if(r.release_candidate)renderReleaseCandidate(r.release_candidate);
    box.textContent=r.report||r.error||'No release readiness report available.';
    if(r.report){
      try{await navigator.clipboard.writeText(r.report);showToast('Release readiness report copied')}
      catch{showToast('Release readiness report displayed below')}
    }
  }catch(e){box.textContent=`ERROR: ${e.message}`}
});

$('#securityVerify').addEventListener('click',async()=>{
  const button=$('#securityVerify'),box=$('#securityResult');button.disabled=true;box.textContent='Verifying Purple Dragon publisher signature and protected files...';
  try{
    const r=await callApi('verify_security_now');
    if(r.security)renderSecurity(r.security);
    box.textContent=r.report||(r.error?`SECURITY LOCK: ${r.error}`:'Verification completed.');
    if(r.security?.verified)showToast('Purple Dragon build verified');else showToast('Purple Dragon security lock');
    await refreshState();
  }catch(e){box.textContent=`ERROR: ${e.message}`}
  finally{button.disabled=false}
});
$('#securityCopyReport').addEventListener('click',async()=>{
  const box=$('#securityResult');
  try{
    const r=await callApi('get_provenance');
    if(r.security)renderSecurity(r.security);
    box.textContent=r.report||r.error||'No security report available.';
    if(r.report){try{await navigator.clipboard.writeText(r.report);showToast('Purple Dragon security report copied')}catch{showToast('Security report displayed below')}}
  }catch(e){box.textContent=`ERROR: ${e.message}`}
});

$$('#monitorRangePills button').forEach(button=>button.addEventListener('click',()=>{$$('#monitorRangePills button').forEach(x=>x.classList.toggle('active',x===button));analyticsRangeSeconds=Number(button.dataset.seconds||3600);refreshAnalytics(true)}));
$('#analyticsSave').addEventListener('click',async()=>{const box=$('#analyticsResult');try{const payload={enabled:$('#analyticsEnabled').value==='on',sample_seconds:Number($('#analyticsSampleSeconds').value||10),retention_days:Number($('#analyticsRetentionDays').value||30)};const r=await handleResult(callApi('configure_analytics',payload),'Monitoring settings saved');renderAnalyticsStatus(r.status||{});box.textContent=r.result||'Settings saved.';await refreshAnalytics(true)}catch(e){box.textContent=`ERROR: ${e.message}`}});
$('#analyticsExportCsv').addEventListener('click',async()=>{const box=$('#analyticsResult');try{const r=await handleResult(callApi('export_analytics',analyticsRangeSeconds,'csv'),'Analytics CSV exported');box.textContent=r.result}catch(e){box.textContent=`ERROR: ${e.message}`}});
$('#analyticsExportJson').addEventListener('click',async()=>{const box=$('#analyticsResult');try{const r=await handleResult(callApi('export_analytics',analyticsRangeSeconds,'json'),'Analytics JSON exported');box.textContent=r.result}catch(e){box.textContent=`ERROR: ${e.message}`}});
$('#analyticsClear').addEventListener('click',async()=>{if(!confirm('Clear all locally recorded Monitoring & Analytics history? This does not change mining configuration or Bitcoin Core data.'))return;const box=$('#analyticsResult');try{const r=await handleResult(callApi('clear_analytics_history'),'Analytics history cleared');box.textContent=r.result;await refreshAnalytics(true)}catch(e){box.textContent=`ERROR: ${e.message}`}});

const themeToggle=$('#themeToggle');
const themePopover=$('#themePopover');
function setThemePopover(open){
  if(!themePopover||!themeToggle)return;
  themePopover.hidden=!open;
  themeToggle.classList.toggle('open',open);
  themeToggle.setAttribute('aria-expanded',open?'true':'false');
}
if(themeToggle)themeToggle.addEventListener('click',event=>{
  event.stopPropagation();
  setThemePopover(themePopover?.hidden!==false);
});
$$('.theme-option').forEach(button=>button.addEventListener('click',async event=>{
  event.stopPropagation();
  const previous=currentUiTheme;
  const next=applyUiTheme(button.dataset.themeValue||'purple');
  setThemePopover(false);
  if(next===previous)return;
  try{
    const r=await handleResult(callApi('set_ui_theme',next),`${UI_THEME_NAMES[next]} theme enabled`);
    if(r.theme)applyUiTheme(r.theme);
    showToast(`${UI_THEME_NAMES[normalizeUiTheme(r.theme||next)]} theme enabled`);
  }catch(e){
    applyUiTheme(previous);
    showToast(`Theme change failed: ${e.message}`);
  }
}));
document.addEventListener('click',event=>{
  if(themePopover && !themePopover.hidden && !$('#themePicker')?.contains(event.target))setThemePopover(false);
});
document.addEventListener('keydown',event=>{
  if(event.key==='Escape' && themePopover && !themePopover.hidden)setThemePopover(false);
});

$('#performancePlusToggle').addEventListener('click',async()=>{
  const button=$('#performancePlusToggle');
  button.disabled=true;
  const next=!performancePlusEnabled;
  applyPerformancePlus(next);
  try{
    const r=await handleResult(callApi('set_performance_plus',next),`Performance+ ${next?'enabled':'disabled'}`);
    if(typeof r.enabled==='boolean')applyPerformancePlus(r.enabled);
    showToast(next?'Performance+ enabled':'Performance+ disabled');
  }catch(e){
    applyPerformancePlus(!next);
    showToast(`Performance+ error: ${e.message}`);
  }finally{
    button.disabled=false;
  }
});
window.addEventListener('resize',()=>{drawCharts();if(lastAnalytics)renderAnalytics(lastAnalytics)});

if($('#hardwareRefresh'))$('#hardwareRefresh').addEventListener('click',async()=>{
  $('#hardwareRefresh').disabled=true;try{await refreshHardwareCompatibility(true)}finally{$('#hardwareRefresh').disabled=false}
});
if($('#hardwareReport'))$('#hardwareReport').addEventListener('click',async()=>{
  $('#hardwareReport').disabled=true;
  try{
    const r=await callApi('create_hardware_compatibility_report');
    if(!r?.ok)throw new Error(r?.error||'Could not create report');
    showToast(r.result||'Compatibility report created');
  }catch(e){showToast(`Compatibility Report: ${e.message}`)}
  finally{$('#hardwareReport').disabled=false}
});
for(const id of ['#hardwareSearch','#hardwareStatusFilter']){
  const el=$(id);if(el)el.addEventListener(id==='#hardwareSearch'?'input':'change',()=>{if(hardwareCompatibilityState)renderHardwareCompatibility(hardwareCompatibilityState)});
}

const profitCalculate=$('#profitCalculate');
const profitCalculateBottom=$('#profitCalculateBottom');
for(const button of [profitCalculate,profitCalculateBottom])if(button)button.addEventListener('click',async()=>{
  button.disabled=true;try{await calculateProfitability(true)}catch(e){showToast(`Profitability: ${e.message}`)}finally{button.disabled=false}
});
if($('#profitUseCore'))$('#profitUseCore').addEventListener('click',async()=>{
  $('#profitUseCore').disabled=true;try{await useCoreProfitabilityData()}catch(e){showToast(`Bitcoin Core: ${e.message}`)}finally{$('#profitUseCore').disabled=false}
});
if($('#profitSave'))$('#profitSave').addEventListener('click',async()=>{
  const i=profitInputs();
  try{
    const r=await callApi(
      'save_profitability_preferences',
      i.hashrate_hs,i.power_watts,i.electricity_per_kwh,i.pool_fee_percent,
      i.btc_price,i.difficulty,i.height,i.block_subsidy_btc,i.avg_fees_btc_per_block
    );
    if(!r?.ok)throw new Error(r?.error||'Save failed');
    showToast(r.result||'Profitability inputs saved');
  }catch(e){showToast(`Profitability: ${e.message}`)}
});
for(const id of ['#profitHashrate','#profitHashrateUnit','#profitPowerWatts','#profitElectricity','#profitPoolFee','#profitBtcPrice','#profitDifficulty','#profitSubsidy','#profitFees']){
  const el=$(id);if(el)el.addEventListener('change',()=>calculateProfitability(false).catch(()=>{}));
}

const assistantRunCheck=$('#assistantRunCheck');
if(assistantRunCheck)assistantRunCheck.addEventListener('click',async()=>{assistantRunCheck.disabled=true;try{await refreshMiningAssistant(true)}finally{assistantRunCheck.disabled=false}});
$$('.assistant-goal').forEach(button=>button.addEventListener('click',async()=>{
  const goal=button.dataset.assistantGoal||'learn';
  try{await saveAssistantPrefs({goal});const r=await callApi('get_mining_assistant_state',goal);if(r?.assistant)renderMiningAssistant(r.assistant)}catch(e){showToast(`Mining Assistant: ${e.message}`)}
}));
document.addEventListener('click',event=>{
  const button=event.target.closest('[data-assistant-route]');
  if(!button)return;
  const route=button.dataset.assistantRoute;
  if(route){setView(route);showToast(`Opened ${route==='core'?'Bitcoin Core':route==='asic'?'ASIC Control':route==='pool'?'Pool PowerTools':route==='security'?'Purple Dragon':route==='monitoring'?'Monitoring':'Dashboard'}`)}
});
if($('#assistantIntroOpen'))$('#assistantIntroOpen').addEventListener('click',async()=>{try{await saveAssistantPrefs({intro_seen:true})}catch{}$('#assistantIntro').hidden=true;setView('assistant');refreshMiningAssistant(false)});
if($('#assistantIntroLater'))$('#assistantIntroLater').addEventListener('click',async()=>{try{await saveAssistantPrefs({intro_seen:true})}catch{}$('#assistantIntro').hidden=true});
if($('#assistantComplete'))$('#assistantComplete').addEventListener('click',async()=>{try{const r=await saveAssistantPrefs({intro_seen:true,completed:true});$('#assistantComplete').textContent='Setup Reviewed ✓';showToast(r?.result||'Mining Assistant setup reviewed')}catch(e){showToast(`Mining Assistant: ${e.message}`)}});

const paypalDonate=$('#paypalDonate');
if(paypalDonate)paypalDonate.addEventListener('click',async()=>{
  paypalDonate.disabled=true;
  try{
    const r=await handleResult(callApi('open_paypal_donation'),'PayPal donation page opened');
    showToast(r.result||'PayPal donation page opened in your browser');
  }catch(e){
    showToast(`Could not open PayPal: ${e.message}`);
  }finally{
    paypalDonate.disabled=false;
  }
});

$('#refreshBtn').addEventListener('click',refreshState);$('#logsRefresh').addEventListener('click',refreshState);
$('#logsClear').addEventListener('click',async()=>{
  const button=$('#logsClear');
  button.disabled=true;
  try{
    const r=await handleResult(callApi('clear_logs'),'Activity log cleared');
    const logs=r.logs||[];
    lastLogSignature='';
    renderLogs(logs);
    renderActivity(logs);
    showToast('Activity log cleared');
    await refreshState();
  }catch(e){
    showToast(`Clear Log error: ${e.message}`);
  }finally{
    button.disabled=false;
  }
});
$('#enginePrimary').addEventListener('click',async()=>{if(lastState?.miner_running)await handleResult(callApi('stop_mining'),'Mining stopped');else await handleResult(callApi('start_mining',poolPayload()),'Mining started');await refreshState()});
$('#quickMining').addEventListener('click',()=>$('#enginePrimary').click());
if($('#poolFailoverPolicy'))$('#poolFailoverPolicy').addEventListener('change',()=>syncFailoverPolicyUi(true));
if($('#poolFailoverEnabled'))$('#poolFailoverEnabled').addEventListener('change',()=>{
  if(!$('#poolFailoverEnabled').checked){$('#poolFailoverPolicy').value='manual'}else if($('#poolFailoverPolicy').value==='manual'){$('#poolFailoverPolicy').value='balanced'}
  syncFailoverPolicyUi(true);
});
if($('#poolProfileSelect'))$('#poolProfileSelect').addEventListener('change',()=>{
  const id=$('#poolProfileSelect').value;const profile=(poolProfilesState?.profiles||[]).find(x=>x.id===id);
  if(profile)loadProfileIntoEditor(profile);else clearPoolProfileEditor();
});
if($('#poolProfilesTable'))$('#poolProfilesTable').addEventListener('click',e=>{
  const tr=e.target.closest('tr[data-profile-id]');if(!tr)return;const profile=(poolProfilesState?.profiles||[]).find(x=>x.id===tr.dataset.profileId);if(profile)loadProfileIntoEditor(profile);
});
if($('#poolProfileNew'))$('#poolProfileNew').addEventListener('click',()=>{clearPoolProfileEditor();$('#poolProfileResult').textContent='New profile editor ready.'});
if($('#poolProfileSave'))$('#poolProfileSave').addEventListener('click',async()=>{
  const box=$('#poolProfileResult');try{const r=await handleResult(callApi('save_pool_profile',profilePayload()),'Pool profile saved');box.textContent=r.result||'Pool profile saved.';if(r.pool_profiles)renderPoolProfiles(r.pool_profiles);if(r.profile)loadProfileIntoEditor(r.profile)}catch(e){box.textContent=`ERROR: ${e.message}`}
});
if($('#poolProfileActivate'))$('#poolProfileActivate').addEventListener('click',async()=>{
  const box=$('#poolProfileResult');const id=$('#poolProfileSelect').value;if(!id){box.textContent='Select a saved profile first.';return}
  try{const r=await handleResult(callApi('activate_pool_profile',id),'Pool profile activated');box.textContent=r.result||'Profile activated.';if(r.pool_config)applyPoolConfigToForm(r.pool_config);if(r.pool_profiles)renderPoolProfiles(r.pool_profiles);await refreshState()}catch(e){box.textContent=`ERROR: ${e.message}`}
});
if($('#poolProfileDelete'))$('#poolProfileDelete').addEventListener('click',async()=>{
  const box=$('#poolProfileResult');const id=$('#poolProfileSelect').value;if(!id){box.textContent='Select a saved profile first.';return}
  try{const r=await handleResult(callApi('delete_pool_profile',id),'Pool profile deleted');box.textContent=r.result||'Profile deleted.';clearPoolProfileEditor();if(r.pool_profiles)renderPoolProfiles(r.pool_profiles)}catch(e){box.textContent=`ERROR: ${e.message}`}
});
if($('#poolProfileTest'))$('#poolProfileTest').addEventListener('click',async()=>{
  const box=$('#poolProfileResult');const id=$('#poolProfileSelect').value;if(!id){box.textContent='Select a saved profile first.';return}
  try{const r=await handleResult(callApi('test_pool_profile',id),'Profile diagnostics started');box.textContent=r.result||'Profile diagnostics started.';await refreshState()}catch(e){box.textContent=`ERROR: ${e.message}`}
});
if($('#poolProfileExport'))$('#poolProfileExport').addEventListener('click',async()=>{
  const box=$('#poolProfileResult');try{const r=await handleResult(callApi('export_pool_profiles'),'Sanitized profiles exported');box.textContent=r.result||r.report||'Profiles exported.';if(r.report){try{await navigator.clipboard.writeText(r.report);showToast('Sanitized profile export copied')}catch{}}}catch(e){box.textContent=`ERROR: ${e.message}`}
});

$('#poolStart').addEventListener('click',async()=>{await handleResult(callApi('start_mining',poolPayload()),'Mining started');await refreshState()});$('#poolStop').addEventListener('click',async()=>{await handleResult(callApi('stop_mining'),'Mining stopped');await refreshState()});$('#poolReset').addEventListener('click',async()=>{await handleResult(callApi('reset_session'),'Session reset');await refreshState()});
$$('.benchmark-preset').forEach(button=>button.addEventListener('click',()=>{
  $$('.benchmark-preset').forEach(x=>x.classList.toggle('active',x===button));
  if($('#benchmarkDuration'))$('#benchmarkDuration').value=button.dataset.duration||30;
  if($('#benchmarkLabel'))$('#benchmarkLabel').value=button.dataset.label||'Benchmark';
}));
async function startBenchmarkLabRun(){
  const workers=Math.max(1,Math.min(64,Number($('#benchmarkWorkers')?.value||2)));
  const duration=Math.max(3,Math.min(3600,Number($('#benchmarkDuration')?.value||30)));
  const label=($('#benchmarkLabel')?.value||'Benchmark').trim()||'Benchmark';
  const r=await callApi('start_benchmark_lab',workers,duration,label);
  if(!r?.ok)throw new Error(r?.error||'Benchmark could not start');
  if(r.benchmark_lab)renderBenchmarkLab(r.benchmark_lab);
  showToast(r.result||'Benchmark started');
}
if($('#benchmarkStart'))$('#benchmarkStart').addEventListener('click',async()=>{try{await startBenchmarkLabRun()}catch(e){showToast(`Benchmark: ${e.message}`)}});
if($('#benchmarkPrimary'))$('#benchmarkPrimary').addEventListener('click',async()=>{try{if(benchmarkLabState?.running||benchmarkLabState?.suite?.running){const r=await callApi('stop_benchmark');if(!r?.ok)throw new Error(r?.error||'Could not stop benchmark');if(r.benchmark_lab)renderBenchmarkLab(r.benchmark_lab);showToast('Benchmark stopped')}else await startBenchmarkLabRun()}catch(e){showToast(`Benchmark: ${e.message}`)}});
if($('#benchmarkStop'))$('#benchmarkStop').addEventListener('click',async()=>{try{const r=await callApi('stop_benchmark');if(!r?.ok)throw new Error(r?.error||'Could not stop benchmark');if(r.benchmark_lab)renderBenchmarkLab(r.benchmark_lab);showToast('Benchmark stopped')}catch(e){showToast(`Benchmark: ${e.message}`)}});
if($('#benchmarkScalingStart'))$('#benchmarkScalingStart').addEventListener('click',async()=>{try{const seconds=Math.max(3,Math.min(120,Number($('#benchmarkScalingSeconds')?.value||8)));const r=await callApi('start_benchmark_scaling_test',seconds);if(!r?.ok)throw new Error(r?.error||'Scaling test could not start');if(r.benchmark_lab)renderBenchmarkLab(r.benchmark_lab);showToast(r.result||'Worker Scaling Test started')}catch(e){showToast(`Scaling test: ${e.message}`)}});
if($('#benchmarkScalingStop'))$('#benchmarkScalingStop').addEventListener('click',()=>$('#benchmarkStop')?.click());
if($('#benchmarkExportJson'))$('#benchmarkExportJson').addEventListener('click',async()=>{try{const r=await callApi('export_benchmark_history','json');if(!r?.ok)throw new Error(r?.error||'Export failed');showToast(r.result||'Benchmark JSON exported')}catch(e){showToast(`Export: ${e.message}`)}});
if($('#benchmarkExportCsv'))$('#benchmarkExportCsv').addEventListener('click',async()=>{try{const r=await callApi('export_benchmark_history','csv');if(!r?.ok)throw new Error(r?.error||'Export failed');showToast(r.result||'Benchmark CSV exported')}catch(e){showToast(`Export: ${e.message}`)}});
if($('#benchmarkClearHistory'))$('#benchmarkClearHistory').addEventListener('click',async()=>{if(!confirm('Clear all local Benchmark Lab history?'))return;try{const r=await callApi('clear_benchmark_history');if(!r?.ok)throw new Error(r?.error||'Could not clear history');if(r.benchmark_lab)renderBenchmarkLab(r.benchmark_lab);showToast('Benchmark history cleared')}catch(e){showToast(`Benchmark: ${e.message}`)}});

$('#quickBenchmark').addEventListener('click',async()=>{if(lastState?.benchmark_running||lastState?.benchmark_lab?.suite?.running)await handleResult(callApi('stop_benchmark'),'Benchmark stopped');else await handleResult(callApi('start_benchmark',Number($('#benchmarkWorkers')?.value||2),0,'Quick Benchmark'),'Benchmark started');await refreshState()});
$('#quickLocalPool').addEventListener('click',async()=>{const r=await handleResult(callApi('toggle_local_pool'),'Local test pool updated');if(r.pool_config)applyPoolConfigToForm(r.pool_config,r.local_password);else if(r.endpoint){applyPoolConfigToForm({pool_url:r.endpoint,pool_backup_urls:[],pool_worker:'local.worker1',pool_failover_enabled:false,suggest_difficulty_enabled:false,suggest_difficulty:0.000001},'x')}else if(r.restored_pool_url!==undefined){$('#poolUrl').value=r.restored_pool_url||''}await refreshState()});$('#localPoolToggle').addEventListener('click',()=>$('#quickLocalPool').click());
$('#poolTest').addEventListener('click',async()=>{const box=$('#poolResult');box.textContent='Connecting...';try{const r=await handleResult(callApi('test_pool',poolPayload()),'Pool test complete');box.textContent=r.result}catch(e){box.textContent=`ERROR: ${e.message}`}});$('#quickPoolTest').addEventListener('click',()=>{setView('pool');$('#poolTest').click()});

$('#poolDiagnosticsStart').addEventListener('click',async()=>{
  const box=$('#poolResult');
  box.textContent='Starting endpoint diagnostics in the background...';
  try{
    const r=await handleResult(callApi('start_pool_diagnostics',poolPayload()),'Endpoint diagnostics started');
    box.textContent=r.result||'Diagnostics started.';
    await refreshState();
  }catch(e){box.textContent=`ERROR: ${e.message}`}
});
$('#poolDiagnosticsClear').addEventListener('click',async()=>{
  const box=$('#poolResult');
  try{
    const r=await handleResult(callApi('clear_pool_diagnostics'),'Endpoint diagnostics cleared');
    box.textContent=r.result||'Diagnostics cleared.';
    await refreshState();
  }catch(e){box.textContent=`ERROR: ${e.message}`}
});
$('#poolDiagnosticsCopy').addEventListener('click',async()=>{
  const box=$('#poolResult');
  try{
    const r=await handleResult(callApi('get_pool_diagnostic_report'));
    box.textContent=r.report||'No diagnostic report available.';
    if(r.report){
      try{await navigator.clipboard.writeText(r.report);showToast('Pool diagnostic report copied')}
      catch{showToast('Diagnostic report displayed below')}
    }
  }catch(e){box.textContent=`ERROR: ${e.message}`}
});
$('#coreAuthMode').addEventListener('change',syncCoreAuthFields);
$('#coreNetwork').addEventListener('change',()=>{$('#coinbaseNetwork').value=$('#coreNetwork').value});
$('#coreDetect').addEventListener('click',async()=>{const box=$('#coreSetupResult');box.textContent='Scanning local Bitcoin Core installation, data directory, cookie, and RPC ports...';try{const r=await handleResult(callApi('detect_core_setup'),'Bitcoin Core detection complete');box.textContent=r.result||'Detection complete.';if(r.setup)renderCoreSetup(r.setup);await refreshState()}catch(e){box.textContent=`ERROR: ${e.message}`}});
$('#coreLocateExe').addEventListener('click',async()=>{const box=$('#coreSetupResult');box.textContent='Choose bitcoin-qt.exe or bitcoind.exe...';try{const r=await handleResult(callApi('locate_core_executable'),'Bitcoin Core executable selected');box.textContent=r.result||'Executable selected.';if(r.setup)renderCoreSetup(r.setup);if(r.config)applyDetectedCoreConfig(r.config);await refreshState()}catch(e){box.textContent=`ERROR: ${e.message}`}});
$('#coreLocateData').addEventListener('click',async()=>{const box=$('#coreSetupResult');box.textContent='Choose the Bitcoin Core data directory...';try{const r=await handleResult(callApi('locate_core_data_dir'),'Bitcoin Core data directory selected');box.textContent=r.result||'Data directory selected.';if(r.setup)renderCoreSetup(r.setup);if(r.config)applyDetectedCoreConfig(r.config);await refreshState()}catch(e){box.textContent=`ERROR: ${e.message}`}});
$('#coreStartNode').addEventListener('click',async()=>{const box=$('#coreSetupResult');box.textContent='Starting Bitcoin Core with the pinned data directory...';try{const r=await handleResult(callApi('start_bitcoin_core'),'Bitcoin Core start requested');box.textContent=r.result||'Bitcoin Core start requested.';if(r.setup)renderCoreSetup(r.setup);setTimeout(()=>$('#coreDetect').click(),3500)}catch(e){box.textContent=`ERROR: ${e.message}`}});
$('#coreOpenData').addEventListener('click',async()=>{const box=$('#coreSetupResult');try{await handleResult(callApi('open_core_data_dir'),'Opened Bitcoin Core data directory')}catch(e){box.textContent=`ERROR: ${e.message}`}});
$('#coreDownload').addEventListener('click',async()=>{const box=$('#coreSetupResult');try{await handleResult(callApi('download_bitcoin_core'),'Opened Bitcoin Core download page');box.textContent='The official Bitcoin Core download page was opened. Install Bitcoin Core, run it once, then return here and click Detect Bitcoin Core.'}catch(e){box.textContent=`ERROR: ${e.message}`}});
$('#coreAutoConfigure').addEventListener('click',async()=>{const box=$('#coreSetupResult');box.textContent='Detecting and applying the best local Bitcoin Core configuration...';try{const r=await handleResult(callApi('auto_configure_core'),'Bitcoin Core auto-configured');box.textContent=r.result||'Auto Configure complete.';if(r.setup)renderCoreSetup(r.setup);if(r.config)applyDetectedCoreConfig(r.config);if(r.core)renderCore(r.core);await refreshState()}catch(e){box.textContent=`ERROR: ${e.message}`}});
$('#coreShowFix').addEventListener('click',async()=>{const box=$('#coreSetupResult');try{const r=await handleResult(callApi('core_setup_recommendation'));box.textContent=`Recommended bitcoin.conf settings:\n\n${r.result}`;if(r.setup)renderCoreSetup(r.setup)}catch(e){box.textContent=`ERROR: ${e.message}`}});
$('#coreTest').addEventListener('click',async()=>{const box=$('#coreResult');box.textContent='Testing getblockchaininfo, getmininginfo, and getnetworkinfo...';try{const r=await handleResult(callApi('test_core',corePayload()),'Bitcoin Core integration verified');box.textContent=r.result;if(r.core)renderCore(r.core);await refreshState()}catch(e){box.textContent=`ERROR: ${e.message}`;await refreshState()}});$('#coreRefresh').addEventListener('click',async()=>{const box=$('#coreResult');box.textContent='Refreshing node status...';try{const r=await handleResult(callApi('refresh_core'),'Bitcoin Core status refreshed');box.textContent=r.result||'Refreshed.';if(r.core)renderCore(r.core);await refreshState()}catch(e){box.textContent=`ERROR: ${e.message}`;await refreshState()}});$('#quickCoreTest').addEventListener('click',()=>{setView('core');$('#coreTest').click()});$('#coreSave').addEventListener('click',async()=>{await handleResult(callApi('save_core_config',corePayload()),'Bitcoin Core configuration saved');await refreshState()});
$('#templateRefresh').addEventListener('click',async()=>{const box=$('#templateResult');box.textContent='Requesting getblocktemplate...';try{const r=await handleResult(callApi('refresh_block_template'),'Block template refreshed');box.textContent=r.result||'Template refreshed.';if(r.template)renderTemplate(r.template);await refreshState()}catch(e){box.textContent=`ERROR: ${e.message}`;await refreshState()}});$('#templateTest').addEventListener('click',async()=>{const box=$('#templateResult');box.textContent='Testing getblocktemplate parsing and target validation...';try{const r=await handleResult(callApi('test_block_template',corePayload()),'Block Template Engine verified');box.textContent=r.result;if(r.template)renderTemplate(r.template);await refreshState()}catch(e){box.textContent=`ERROR: ${e.message}`;await refreshState()}});
$('#coinbaseValidate').addEventListener('click',async()=>{const box=$('#coinbaseResult');box.textContent='Validating payout address locally...';try{const r=await handleResult(callApi('validate_payout_address',coinbasePayload()),'Payout address valid');box.textContent=r.result||'Address valid.'}catch(e){box.textContent=`ERROR: ${e.message}`}});
$('#coinbaseBuild').addEventListener('click',async()=>{const box=$('#coinbaseResult');box.textContent='Building coinbase transaction locally from the current block template...';try{const r=await handleResult(callApi('build_coinbase_preview',coinbasePayload()),'Coinbase preview built');box.textContent=r.result||'Coinbase ready.';if(r.coinbase)renderCoinbase(r.coinbase,true)}catch(e){box.textContent=`ERROR: ${e.message}`}});
$('#coinbaseSave').addEventListener('click',async()=>{const box=$('#coinbaseResult');try{const r=await handleResult(callApi('save_coinbase_config',coinbasePayload()),'Payout configuration saved');if(r.coinbase)renderCoinbase(r.coinbase,true);box.textContent='Payout configuration saved. Build a preview when you want to use the current template.'}catch(e){box.textContent=`ERROR: ${e.message}`}});
$('#soloTest').addEventListener('click',async()=>{const box=$('#soloResult');box.textContent='Testing coinbase → merkle root → 80-byte header → SHA-256d → target comparison...';try{const r=await handleResult(callApi('test_solo_mining_pipeline',soloPayload()),'Solo mining pipeline verified');box.textContent=r.result||'Pipeline verified.'}catch(e){box.textContent=`ERROR: ${e.message}`}});
$('#soloStart').addEventListener('click',async()=>{const box=$('#soloResult');box.textContent='Starting responsive local SHA-256d candidate search...';try{const r=await handleResult(callApi('start_solo_mining',soloPayload()),'Solo Mining Engine started');box.textContent=r.result||'Solo mining started.';if(r.solo)renderSolo(r.solo)}catch(e){box.textContent=`ERROR: ${e.message}`}});
$('#soloStop').addEventListener('click',async()=>{const box=$('#soloResult');try{const r=await handleResult(callApi('stop_solo_mining'),'Solo Mining Engine stopped');box.textContent=r.result||'Solo mining stopped.';if(r.solo)renderSolo(r.solo)}catch(e){box.textContent=`ERROR: ${e.message}`}});
$('#soloReset').addEventListener('click',async()=>{const box=$('#soloResult');try{const r=await handleResult(callApi('reset_solo_mining'),'Solo mining statistics reset');box.textContent=r.result||'Statistics reset.';if(r.solo)renderSolo(r.solo)}catch(e){box.textContent=`ERROR: ${e.message}`}});

$('#submissionTest').addEventListener('click',async()=>{const box=$('#submissionResult');box.textContent='Starting background block assembly test...';try{const r=await handleResult(callApi('test_block_assembly',coinbasePayload()),'Block assembly test started');box.textContent=r.result||'Block assembly test started.';if(r.submission)renderSubmission(r.submission)}catch(e){box.textContent=`ERROR: ${e.message}`}});
$('#submissionAssemble').addEventListener('click',async()=>{const box=$('#submissionResult');box.textContent='Starting background candidate assembly...';try{const r=await handleResult(callApi('assemble_solo_candidate'),'Candidate assembly started');box.textContent=r.result||'Candidate assembly started.';if(r.submission)renderSubmission(r.submission)}catch(e){box.textContent=`ERROR: ${e.message}`}});
$('#submissionValidate').addEventListener('click',async()=>{const box=$('#submissionResult');box.textContent='Starting background Bitcoin Core proposal validation...';try{const r=await handleResult(callApi('validate_solo_candidate'),'Proposal validation started');box.textContent=r.result||'Proposal validation started.';if(r.submission)renderSubmission(r.submission)}catch(e){box.textContent=`ERROR: ${e.message}`}});
$('#submissionSubmitBtn').addEventListener('click',async()=>{const box=$('#submissionResult');if(!$('#submissionAuthorized').checked){box.textContent='ERROR: Confirm the submission authorization checkbox first.';return}box.textContent='Starting guarded submitblock in the background...';try{const r=await handleResult(callApi('submit_solo_candidate',true),'Controlled submitblock started');box.textContent=r.result||'Controlled submitblock started.';if(r.submission)renderSubmission(r.submission)}catch(e){box.textContent=`ERROR: ${e.message}`}});

$('#regtestStart').addEventListener('click',async()=>{const box=$('#regtestResult');box.textContent='Starting isolated regtest Bitcoin Core node...';try{const r=await handleResult(callApi('start_regtest_lab'),'Regtest Lab starting');box.textContent=r.result||'Regtest Lab starting.';if(r.regtest)renderRegtest(r.regtest)}catch(e){box.textContent=`ERROR: ${e.message}`}});
$('#regtestRefresh').addEventListener('click',async()=>{const box=$('#regtestResult');box.textContent='Refreshing isolated regtest node and wallet...';try{const r=await handleResult(callApi('refresh_regtest_lab'),'Regtest Lab refresh started');box.textContent=r.result||'Regtest refresh started.';if(r.regtest)renderRegtest(r.regtest)}catch(e){box.textContent=`ERROR: ${e.message}`}});
$('#regtestMine').addEventListener('click',async()=>{const box=$('#regtestResult');const count=Math.max(1,Math.min(500,Number($('#regtestBlockCount').value||1)));box.textContent=`Starting full regtest mining/submission pipeline for ${count} block(s)...`;try{const r=await handleResult(callApi('mine_regtest_blocks',count),'Regtest mining started');box.textContent=r.result||'Regtest mining started.';if(r.regtest)renderRegtest(r.regtest)}catch(e){box.textContent=`ERROR: ${e.message}`}});
$('#regtestMine101').addEventListener('click',async()=>{const box=$('#regtestResult');$('#regtestBlockCount').value=101;box.textContent='Starting 101-block maturity run in the background...';try{const r=await handleResult(callApi('mine_regtest_blocks',101),'101-block Regtest run started');box.textContent=r.result||'101-block run started.';if(r.regtest)renderRegtest(r.regtest)}catch(e){box.textContent=`ERROR: ${e.message}`}});
$('#regtestStop').addEventListener('click',async()=>{const box=$('#regtestResult');box.textContent='Stopping only the isolated regtest node...';try{const r=await handleResult(callApi('stop_regtest_lab'),'Regtest Lab stop started');box.textContent=r.result||'Regtest Lab stopping.';if(r.regtest)renderRegtest(r.regtest)}catch(e){box.textContent=`ERROR: ${e.message}`}});
$('#regtestReset').addEventListener('click',async()=>{const box=$('#regtestResult');const authorized=$('#regtestResetAuthorized').checked;if(!authorized){box.textContent='ERROR: Confirm the Regtest reset checkbox first.';return}box.textContent='Resetting only the isolated Regtest Lab chain...';try{const r=await handleResult(callApi('reset_regtest_lab',true),'Regtest Lab reset started');box.textContent=r.result||'Regtest reset started.';if(r.regtest)renderRegtest(r.regtest)}catch(e){box.textContent=`ERROR: ${e.message}`}});
$('#asicDiscover').addEventListener('click',async()=>{await handleResult(callApi('discover_asics',$('#asicCidr').value,$('#asicAuthorized').checked),'ASIC discovery complete');await refreshState()});$('#asicRefresh').addEventListener('click',async()=>{await handleResult(callApi('refresh_asics'),'ASIC fleet refreshed');await refreshState()});$('#quickAsic').addEventListener('click',()=>$('#asicRefresh').click());$('#asicAdd').addEventListener('click',async()=>{const ip=prompt('Private LAN IP address:');if(ip){await handleResult(callApi('add_asic',ip),'ASIC added');await refreshState()}});

$('#asicSoloStart').addEventListener('click',async()=>{
  const box=$('#asicSoloResult');
  if(!$('#asicAuthorized').checked){box.textContent='ERROR: Confirm that you own or administer the ASIC devices first.';return}
  const payload={bind_ip:$('#asicSoloBindIp').value.trim(),port:Number($('#asicSoloPort').value||3333),share_difficulty:Number($('#asicSoloDifficulty').value||65536)};
  box.textContent='Starting LAN-only ASIC Solo Stratum Bridge...';
  try{
    const r=await handleResult(callApi('start_asic_solo_bridge',payload,true),'ASIC Solo Bridge started');
    box.textContent=r.result||'ASIC Solo Bridge started.';
    if(r.asic_solo_bridge)renderAsicSoloBridge(r.asic_solo_bridge);
    await refreshState();
  }catch(e){box.textContent=`ERROR: ${e.message}`}
});
$('#asicSoloStop').addEventListener('click',async()=>{
  const box=$('#asicSoloResult');box.textContent='Stopping ASIC Solo Bridge...';
  try{
    const r=await handleResult(callApi('stop_asic_solo_bridge'),'ASIC Solo Bridge stopped');
    box.textContent=r.result||'ASIC Solo Bridge stopped.';
    if(r.asic_solo_bridge)renderAsicSoloBridge(r.asic_solo_bridge);
    await refreshState();
  }catch(e){box.textContent=`ERROR: ${e.message}`}
});
$('#asicSoloCopy').addEventListener('click',async()=>{
  const value=$('#asicSoloEndpoint').value;
  if(!value||value==='—'){showToast('Start the Solo Bridge first');return}
  try{await navigator.clipboard.writeText(value);showToast('Solo Bridge endpoint copied')}
  catch{showToast(`Solo Bridge: ${value}`)}
});

$('#hashHuntRun').addEventListener('click',runHashHuntAttempt);
$('#hashHuntClaim').addEventListener('click',claimHashHuntBlock);
$('#hashHuntReset').addEventListener('click',resetHashHunt);
$('#hashHuntDifficulty').addEventListener('change',e=>changeHashHuntDifficulty(e.target.value));
renderHashHunt();


