'use strict';
(()=>{
const C={overview:null,session:null,chain:Promise.resolve(),busy:false,timer:null,beat:null,saveTimer:null,clockAt:0,clockBase:0};
const endpoint='/api/calculation-training';
const cbtn=(...args)=>btn(...args).replace('<button ', '<button type="button" ');
const modeName=m=>m==='table'?'同组联练':'单项速练';
const levelName={basic:'基础 · 整数与常用率',standard:'常规 · 小数增长率',challenge:'进阶 · 较大数与负增长'};
const stateName={active:'进行中',paused:'已暂停',review:'待下一题',finished:'已结束'};
const seconds=n=>n<60?Number(n).toFixed(1)+' 秒':Math.floor(n/60)+' 分 '+Math.floor(n%60)+' 秒';
const pct=(n,d)=>d?Math.round(n*100/d)+'%':'—';
const signed=n=>(Number(n)>0?'+':'')+Number(n).toFixed(2);
const answerText=q=>String(q.result?.input||'').replace(/\s*(?:亿元|个百分点|[%％])\s*$/,'').trim();
const resultPill=r=>pill(r.skipped?'未作答':r.correct?'估算达标':'超出范围',r.correct?'green':'orange');
function stopTimers(){clearInterval(C.timer);clearInterval(C.beat);clearTimeout(C.saveTimer)}
function route(){return '#calculation/'+C.session?.id}
function currentQuestion(){const s=C.session;return s.questions.find(q=>q.id===s.review_item)||s.questions.find(q=>!q.result)}
function capture(){
 const s=C.session;if(!s)return {};
 document.querySelectorAll('[data-calc-input]').forEach(el=>{const q=s.questions.find(q=>q.id===el.dataset.calcInput);if(q&&!q.result)q.draft=el.value});
 return Object.fromEntries(s.questions.filter(q=>!q.result).map(q=>[q.id,q.draft||'']));
}
function saveDraft(){
 const s=C.session;if(!s||s.status==='finished')return C.chain;
 const id=s.id,values=capture();clearTimeout(C.saveTimer);
 C.chain=C.chain.catch(()=>{}).then(()=>api(`${endpoint}/sessions/${id}/draft`,'POST',{values}));
 return C.chain;
}
function adopt(s){C.session=s;C.clockBase=s.elapsed_seconds;C.clockAt=Date.now()}
async function act(verb,body={}){
 await saveDraft();const s=await api(`${endpoint}/sessions/${C.session.id}/${verb}`,'POST',body);adopt(s);paint();return s;
}
function updateClock(){
 const s=C.session;if(!s)return;
 const elapsed=C.clockBase+(s.status==='active'?Math.min(30,(Date.now()-C.clockAt)/1000):0);
 const el=$('#calc-clock');if(el)el.textContent=seconds(elapsed);
}
function mount(){
 stopTimers();if(!C.session)return;
 updateClock();C.timer=setInterval(updateClock,1000);
 C.beat=setInterval(async()=>{
  if(C.session?.status!=='active'||C.busy||document.hidden)return;
  const id=C.session.id;
  try{await C.chain.catch(()=>{});const s=await api(`${endpoint}/sessions/${id}/heartbeat`,'POST',{});
   if(C.session?.id===id){adopt(s);if(s.status!=='active')paint();else updateClock()}
  }catch(e){toast('计时续报中断；断线后最多记录30秒。恢复连接后可继续。',true)}
 },15000);
 if(C.session.mode==='quick'&&C.session.status==='active')$('#calc-answer')?.focus();
}
function parameters(p){return `<div class="calc-parameters"><div class="calc-data a"><span>现期量 A</span><strong>${E(p.a)}<small>亿元</small></strong><span>同比增长率 r₁ <b>${E(p.r1)}%</b></span></div><div class="calc-data b"><span>现期量 B</span><strong>${E(p.b)}<small>亿元</small></strong><span>同比增长率 r₂ <b>${E(p.r2)}%</b></span></div></div>`}
function bounds(q){return `参考值 ${q.result.reference} ${q.unit} · 达标范围 [${q.result.lower}, ${q.result.upper}]`}
function explanation(q){const r=q.result;return `<details class="calc-explanation"><summary>查看公式与计算思路</summary><p>${E(r.formula)}</p><p class="muted">代入：${E(r.substitution)}</p><p>${E(r.tip)}</p></details>`}
function hint(q){return q.hint?`<div class="calc-hint"><strong>公式提示</strong><p>${E(q.hint.formula)}</p><p class="field-note">${E(q.hint.tip)}</p></div>`:''}
function overviewPage(o){
 const groups=[...new Set(o.types.map(t=>t.group))];
 return pageHead('CALCULATE · ESTIMATE · CHECK','计算训练','从一组数开始，把基期、增长、比重与和差练顺。')+
 `<div class="calc-rule"><strong>估算允许 ±3</strong><span>${E(o.rule)}</span><small>先将参考值保留两位小数。百分数直接填数值，例如 21.92；不是 0.2192。</small></div>`+
 `<section class="grid four stats calc-stats">${stat('累计训练',o.total,'项','独立计算练习记录','pen')}${stat('估算达标率',pct(o.correct,o.total),'','按±3判定','target')}${stat('有效停留',Math.round(o.elapsed_seconds/60),'分钟','暂停与反馈阅读不计时','clock')}${stat('可练题型',o.types.length,'类','自动换数，本地判定','layers')}</section>`+
 `<section class="card"><div class="card-head"><h2>开始一轮计算</h2>${pill('本地出题 · 无需模型','green')}</div><form id="calc-setup"><div class="calc-mode-grid"><label class="calc-mode"><input type="radio" name="mode" value="quick" checked><span><strong>单项速练</strong><small>每题换数，提交后立即核对，按回车继续。</small></span></label><label class="calc-mode"><input type="radio" name="mode" value="table"><span><strong>同组联练</strong><small>同一组 A、B 与增长率，连续推算多项结果。</small></span></label></div><div class="form-grid top20"><div><label for="calc-level">数值难度</label><select name="level" id="calc-level">${Object.entries(levelName).map(([k,v])=>`<option value="${k}" ${k==='standard'?'selected':''}>${v}</option>`).join('')}</select></div><div><label for="calc-count">单项速练题量</label><select name="count" id="calc-count">${[5,10,20,30].map(n=>`<option ${n===10?'selected':''}>${n}</option>`).join('')}</select><p class="field-note" id="calc-count-note">所选题型尽量均衡抽取；题量不足时随机选部分题型。</p></div></div><div class="row between wrap top20"><h3>选择题型</h3><div class="row">${cbtn('全选','calc-select-all','sm')}${cbtn('清空','calc-select-none','sm')}</div></div>${groups.map(g=>`<fieldset class="calc-type-group"><legend>${E(g)}</legend><div class="calc-type-grid">${o.types.filter(t=>t.group===g).map(t=>`<label class="calc-type"><input type="checkbox" name="types" value="${t.id}" checked><span>${E(t.name)}<small>${t.unit}</small></span></label>`).join('')}</div></fieldset>`).join('')}<div class="row wrap top20"><button class="btn primary" type="submit">开始训练 ${icon('arrow')}</button><span class="small muted">支持暂停续练，记录自动保存在本机。</span></div><p class="field-note">基期和、和增长率仅作数列计算；间隔增长率把两率视为连续两段增长率。</p></form></section>`+
 `<section class="card top24"><div class="card-head"><h2>分项练习记录</h2><span class="tiny muted">只反映计算结果，不推断个人错因</span></div><div class="calc-table-wrap"><table class="calc-history"><thead><tr><th>题型</th><th>已练</th><th>达标率</th><th>提示 / 未答</th><th></th></tr></thead><tbody>${o.types.map(t=>`<tr><td>${E(t.name)}</td><td>${t.answered}</td><td>${pct(t.correct,t.answered)}</td><td>${t.hinted} / ${t.skipped}</td><td>${cbtn('练此项','calc-practice-type','sm','',`data-type="${t.id}"`)}</td></tr>`).join('')}</tbody></table></div></section>`+
 `<section class="card top24"><div class="card-head"><h2>最近训练</h2></div>${o.recent.length?`<div class="calc-table-wrap"><table class="calc-history"><thead><tr><th>时间 / 模式</th><th>进度与结果</th><th>状态</th><th></th></tr></thead><tbody>${o.recent.map(s=>`<tr><td>${fmtDate(s.created_at)}<div class="tiny muted">${modeName(s.mode)}</div></td><td>完成 ${s.answered}/${s.total} · 达标 ${s.correct} 项</td><td>${E(stateName[s.status])}</td><td><a class="btn sm" href="#calculation/${s.id}">${s.status==='finished'?'查看记录':'继续训练'}</a></td></tr>`).join('')}</tbody></table></div>`:empty('还没有计算训练记录','选一类题，从五次快速估算开始。')}</section>`;
}
function sessionHeader(s){return pageHead('CALCULATION PRACTICE',modeName(s.mode),`${levelName[s.level]} · 已提交 ${s.answered}/${s.total} 项`,'<a class="btn" href="#calculation">训练首页</a>')+`<div class="calc-work-bar"><div class="row wrap">${pill(stateName[s.status],s.status==='active'?'green':'')}<span>有效停留 <strong id="calc-clock">${seconds(s.elapsed_seconds)}</strong></span><span>达标 <b>${s.correct}</b> / 已提交 ${s.answered}</span></div><div class="row">${s.status==='active'?cbtn('暂停并保存','calc-toggle','sm','clock'):s.status==='paused'?cbtn('继续计时','calc-toggle','primary sm','clock'):''}${s.status!=='finished'?cbtn('结束本轮','calc-finish-open','sm'):''}</div></div>`}
function quick(s){
 const q=currentQuestion();if(!q)return summary(s);
 const r=q.result,active=s.status==='active';
 return `<section class="card calc-quick"><div class="row between wrap"><span class="eyebrow">第 ${s.questions.indexOf(q)+1} / ${s.total} 项</span>${pill(q.unit==='亿元'?'允许 ±3 亿元':'允许 ±3 个百分点')}</div>${parameters(q.parameters)}<h2 class="calc-question">估算：${E(q.name)}</h2><p class="field-note">${q.kind==='compound_growth'?'本项把r₁、r₂视为连续两段增长率，求合计增长率。':q.kind.includes('difference')?'差值按 B 减 A 计算。':q.kind==='share_change'?'求现期比重减基期比重，结果用百分点表示。':'A为部分量，B为整体量；两率分别是A、B的同比增长率。'}</p>
 ${r?`<div class="calc-feedback ${r.correct?'pass':'miss'}"><div class="row between wrap"><strong>${r.skipped?'本题已跳过':r.correct?'估算达标':'再核对一下这一步'}</strong>${resultPill(r)}</div><p>你的估算：${r.skipped?'未作答':E(answerText(q))+' '+q.unit}${!r.skipped?' · 误差 '+signed(r.error):''}</p><p>${E(bounds(q))}</p>${r.direction_warning?'<p class="calc-warning">数值按±3规则判定；你的正负方向与参考值不同，建议另行核对方向。</p>':''}${explanation(q)}</div><div class="row top20">${cbtn('下一题 · Enter','calc-next','primary','arrow')}</div>`:
 `<form id="calc-answer-form"><label for="calc-answer">你的估算${q.unit!=='亿元'?'（直接填百分数数值）':''}</label><div class="calc-answer-row"><div class="calc-input-wrap"><input id="calc-answer" data-calc-input="${q.id}" value="${E(q.draft)}" type="text" inputmode="decimal" maxlength="40" autocomplete="off" placeholder="例如 ${q.unit==='亿元'?'142':'21.92'}" ${active?'':'disabled'}><span>${E(q.unit)}</span></div><button class="btn primary" type="submit" ${active?'':'disabled'}>提交估算 · Enter</button></div><p class="field-note">绝对误差≤3即达标，边界也计入。${active?'':'当前暂停，点击“继续计时”后作答。'}</p></form><div class="row wrap top20">${cbtn('看公式提示','calc-hint','sm','',`data-id="${q.id}"`)}${cbtn('跳过并查看','calc-skip','sm','',active?'':'disabled')}</div>${hint(q)}`}</section>`;
}
function table(s){
 const active=s.status==='active';return `<section class="card calc-linked">${parameters(s.questions[0].parameters)}<p class="field-note">用同一组数依次推算。数量题填亿元，百分数直接填数值；空白项提交后记为未作答。间隔增长率另把r₁、r₂视为连续两段增长率。</p><form id="calc-table-form"><div class="calc-table-wrap"><table class="calc-linked-table"><thead><tr><th>计算项目</th><th>你的估算</th><th>核对与思路</th></tr></thead><tbody>${s.questions.map((q,i)=>`<tr><td><strong>${i+1}. ${E(q.name)}</strong><div class="tiny muted">${E(q.unit)} · 容差 ±3</div></td><td><label class="sr-only" for="calc-${q.id}">${E(q.name)}</label><div class="calc-input-wrap"><input id="calc-${q.id}" data-calc-input="${q.id}" value="${E(q.result?answerText(q):q.draft)}" inputmode="decimal" type="text" maxlength="40" autocomplete="off" ${active&&!q.result?'':'disabled'}><span>${E(q.unit)}</span></div></td><td>${q.result?`${resultPill(q.result)}<p class="small">参考 ${q.result.reference}${q.unit} ${q.result.skipped?'':`· 误差 ${signed(q.result.error)}`}</p><p class="tiny muted">范围 [${q.result.lower}, ${q.result.upper}]</p>${q.result.direction_warning?'<p class="calc-warning">请核对正负方向</p>':''}${explanation(q)}`:`${cbtn('公式提示','calc-hint','sm','',`data-id="${q.id}"`)}${hint(q)}`}</td></tr>`).join('')}</tbody></table></div>${s.status!=='finished'?`<div class="row wrap top20"><button class="btn primary" type="submit" ${active?'':'disabled'}>提交整组并核对</button><span class="small muted">${active?'回车跳到下一项，最后一项回车提交。':'已暂停，继续计时后可以作答。'}</span></div>`:''}</form></section>`;
}
function summary(s){
 const answered=s.questions.filter(q=>q.result),wrong=answered.filter(q=>!q.result.correct);
 return `<section class="card calc-summary"><div class="row between wrap"><div><p class="eyebrow">本轮训练已保存</p><h2 class="top12">${s.correct} / ${s.answered} 项估算达标</h2><p class="small muted top12">有效停留 ${seconds(s.elapsed_seconds)}${s.total>s.answered?' · '+(s.total-s.answered)+' 项未完成':''} · 容差按绝对值±3计算</p></div><div class="row wrap">${wrong.length?cbtn('针对未达标题型再练','calc-retry-wrong','soft','refresh'):''}${cbtn('再来一组','calc-repeat','primary','arrow')}</div></div><p class="field-note">这是计算练习记录，不计入模考估分。使用提示与未作答分别保留。</p></section>`+
 (s.mode==='table'?table(s):`<section class="card top24"><h2>逐项核对</h2>${answered.length?answered.map(q=>`<article class="calc-review"><div class="row between wrap"><h3>${E(q.name)}</h3>${resultPill(q.result)}</div><p class="small muted">A=${E(q.parameters.a)}，B=${E(q.parameters.b)}；r₁=${E(q.parameters.r1)}%，r₂=${E(q.parameters.r2)}%</p><p class="small">你的估算 ${q.result.skipped?'未作答':E(answerText(q))+q.unit} · ${E(bounds(q))}${!q.result.skipped?' · 误差 '+signed(q.result.error):''}${q.result.hint_used?' · 使用过提示':''}</p>${q.result.direction_warning?'<p class="calc-warning">数值按容差判定，请额外核对正负方向。</p>':''}${explanation(q)}</article>`).join(''):empty('本轮尚未提交估算','可以返回选择题型，再开始一轮。')}</section>`);
}
function work(s){return sessionHeader(s)+(s.status==='finished'?summary(s):s.mode==='table'?table(s):quick(s))}
function paint(){if(location.hash!==route())return;$('#main').innerHTML=work(C.session)+foot();mount()}
S.calculationPage=async id=>{
 if(C.session?.status==='active'&&C.session.id!==id)leave(true);
 stopTimers();
 if(id){adopt(await api(`${endpoint}/sessions/${encodeURIComponent(id)}`));return work(C.session)}
 C.session=null;C.overview=await api(endpoint);return overviewPage(C.overview);
};
S.calculationMount=mount;
async function create(spec){
 const s=await api(endpoint+'/sessions','POST',spec);adopt(s);location.hash='calculation/'+s.id;
}
Object.assign(actions,{
 'calc-select-all':()=>document.querySelectorAll('#calc-setup [name=types]').forEach(el=>el.checked=true),
 'calc-select-none':()=>document.querySelectorAll('#calc-setup [name=types]').forEach(el=>el.checked=false),
 'calc-toggle':()=>act(C.session.status==='active'?'pause':'start'),
 'calc-hint':el=>act('hint',{question_id:el.dataset.id}),
 'calc-next':()=>act('start'),
 'calc-skip':()=>act('skip',{question_id:currentQuestion().id}),
 'calc-finish-open':()=>openModal('结束本轮计算',`<p>已提交的估算和草稿会保留，剩余未完成项不补作答。</p><div class="row top20">${cbtn('继续训练','close-modal')}${cbtn('结束并看记录','calc-finish','primary')}</div>`),
 'calc-finish':async()=>{closeModal();await act('finish')},
 'calc-practice-type':el=>create({mode:'quick',types:[el.dataset.type],count:10,level:'standard'}),
 'calc-repeat':()=>create({mode:C.session.mode,types:C.session.types,count:C.session.mode==='quick'?C.session.total:10,level:C.session.level}),
 'calc-retry-wrong':()=>create({mode:'quick',types:[...new Set(C.session.questions.filter(q=>q.result&&!q.result.correct).map(q=>q.kind))],count:10,level:C.session.level})
});
document.addEventListener('change',event=>{
 if(event.target.matches('#calc-setup [name=mode]')){
  const tableMode=event.target.value==='table';$('#calc-count').disabled=tableMode;
  $('#calc-count-note').textContent=tableMode?'本组每种已选题型各练一项，最多13项。':'所选题型尽量均衡抽取；题量不足时随机选部分题型。';
 }
});
document.addEventListener('input',event=>{
 if(!event.target.matches('[data-calc-input]'))return;capture();clearTimeout(C.saveTimer);
 C.saveTimer=setTimeout(()=>saveDraft().catch(e=>toast('草稿未保存：'+e.message,true)),500);
});
document.addEventListener('submit',async event=>{
 const f=event.target;if(!['calc-setup','calc-answer-form','calc-table-form'].includes(f.id))return;
 event.preventDefault();if(C.busy)return;C.busy=true;const submit=f.querySelector('[type=submit]');if(submit)submit.disabled=true;
 try{
  if(f.id==='calc-setup'){
   const types=[...f.querySelectorAll('[name=types]:checked')].map(el=>el.value);
   if(!types.length)throw new Error('请至少选择一种题型');
   await create({mode:f.elements.mode.value,level:f.elements.level.value,count:f.elements.count.value,types});
  }else if(f.id==='calc-answer-form'){
   const q=currentQuestion();await act('answer',{question_id:q.id,value:$('#calc-answer').value});
  }else await act('check',{values:capture()});
 }catch(e){toast(e.message,true)}finally{C.busy=false;if(submit)submit.disabled=false}
});
document.addEventListener('keydown',event=>{
 if(event.key!=='Enter'||event.isComposing||$('.modal'))return;
 if(event.target.matches('[data-calc-input]')&&C.session?.mode==='table'){
  const inputs=[...document.querySelectorAll('[data-calc-input]:not([disabled])')],i=inputs.indexOf(event.target);
  if(i>=0&&i<inputs.length-1){event.preventDefault();inputs[i+1].focus()}
 }else if(location.hash===route()&&C.session?.status==='review'){
  event.preventDefault();if(!C.busy){C.busy=true;act('start').catch(e=>toast(e.message,true)).finally(()=>C.busy=false)}
 }
});
function leave(keepalive=false){
 const s=C.session;if(!s||s.status!=='active')return;
 const id=s.id,values=capture();s.status='paused';stopTimers();
 if(keepalive){
  for(const [verb,body] of [['draft',{values}],['pause',{}]])fetch(`${endpoint}/sessions/${id}/${verb}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),keepalive:true}).catch(()=>{});
 }else{
  C.chain=C.chain.catch(()=>{}).then(()=>api(`${endpoint}/sessions/${id}/draft`,'POST',{values})).then(()=>api(`${endpoint}/sessions/${id}/pause`,'POST',{})).then(value=>{if(C.session?.id===id){adopt(value);paint()}}).catch(e=>toast('暂停保存未完成：'+e.message,true));
 }
}
window.addEventListener('hashchange',()=>{if(C.session&&location.hash!==route())leave(true)});
document.addEventListener('visibilitychange',()=>{if(document.hidden)leave();else if(C.session&&location.hash===route())paint()});
window.addEventListener('pagehide',()=>leave(true));
})();
