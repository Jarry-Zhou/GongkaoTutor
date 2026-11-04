'use strict';
(()=>{
let profile=null;
const tone=c=>c.state==='跨题反复'?'orange':['出现改善证据','本批表现较好'].includes(c.state)?'green':'';
const judgment={weak:'补强信号',adequate:'表现较好',uncertain:'待验证'};
function shortCards(p){
 return `<div class="dimension-compact-grid">${p.dimensions.map(c=>`<article class="dimension-compact"><div class="row between wrap"><strong>${E(c.name)}</strong>${pill(c.state,tone(c))}</div><p class="tiny muted top12">${c.written_questions} 道已分析题 · ${c.training_records} 条训练记录</p>${c.conclusion?`<p class="small top12">${E(c.conclusion.summary)}</p>`:''}</article>`).join('')}</div>`;
}
S.shenlunDimensionSection=p=>p?`<section class="card dimension-entry"><div class="row between wrap"><div><h2>申论综合维度画像</h2><p class="small muted top12">层次划分、主旨凝练、业务熟悉度，以及找点、论证、表达和效率，一并进入综合 AI 分析。</p></div>${btn('查看七维画像','shenlun-dimensions-open','soft','target')}</div><div class="dimension-state-strip top20">${p.dimensions.map(c=>`<span>${E(c.name)} ${pill(c.state,tone(c))}</span>`).join('')}</div><p class="field-note">${E(p.note)}</p></section>`:'';
S.shenlunDimensionMarkup=p=>p?`<section class="diagnosis-section"><h3>申论跨题维度分析</h3><p class="field-note">累计 ${p.questions} 道有维度证据的申论题。以下是本次保存的快照；可打开当前画像核对最新修订。</p>${shortCards(p)}<div class="row wrap top16">${btn('查看证据与针对性训练','shenlun-dimensions-open','primary sm','target')}</div></section>`:'';
function detailedCard(c,p){
 const tasks=p.tasks.filter(t=>t.dimension===c.dimension&&['ready','active','paused'].includes(t.status));
 return `<article class="dimension-card"><div class="row between wrap"><h3>${E(c.name)}</h3>${pill(c.state,tone(c))}</div><p class="field-note">${E(c.description)}</p><p class="tiny muted">${c.written_questions} 道题 · ${c.weak_questions} 道有补强信号 · ${c.adequate_questions} 道有较好表现 · ${c.training_records} 条训练记录</p>
 ${c.conclusion?`<div class="intro-box top16"><p class="prose">${E(c.conclusion.summary)}</p>${c.conclusion.change?`<p class="small top12">变化：${E(c.conclusion.change)}</p>`:''}<p class="small top12">下一步：${E(c.conclusion.next_step)}</p></div>`:`<p class="small muted top16">${c.conclusion_pending?'已有结论的依据发生变化，等待新证据校验。':c.observations.length?'已有本题观察，跨题共同原因仍需继续验证。':'尚无足够的已分析证据，不预填个人薄弱点。'}</p>`}
 ${c.stale_records?`<p class="field-note">${c.stale_records} 条旧证据待重新校验，不计入当前判断。</p>`:''}
 ${c.observations.length?`<details class="dimension-evidence top16"><summary>核对 ${c.observations.length} 条当前依据</summary>${c.observations.map(o=>`<section class="dimension-observation"><div class="row between wrap">${pill(judgment[o.judgment],o.judgment==='weak'?'orange':'')}${pill(o.source_type==='training'?'短训练':'作答')}</div><p class="small top12">${E(o.observation)}</p>${o.user_quote?`<p class="coach-evidence-quote">你的记录：${E(o.user_quote)}</p>`:''}${o.process_quote?`<p class="small top12">过程依据：${E(o.process_quote)}</p>`:''}${o.citations.map(q=>`<blockquote class="coach-evidence-quote">${E(q.paragraph_id)} · ${E(q.quote)}</blockquote>`).join('')}${o.timing.length?`<p class="field-note">分步停留：${o.timing.map(t=>E(t.prompt.slice(0,50))+' '+t.seconds+' 秒').join('；')}。仅为本次记录，不是标准用时。</p>`:''}<p class="small top12">怎样改：${E(o.action)}</p><p class="small top12">验证问题：${E(o.verify)}</p><p class="tiny muted top12">${E(o.title.slice(0,140))}</p>${btn('查看来源记录','dimension-source','sm top12','eye',`data-type="${o.source_type}" data-id="${o.source_id}"`)}</section>`).join('')}</details>`:''}
 ${tasks.length?`<div class="row wrap top20">${tasks.slice(0,2).map(t=>btn(t.status==='ready'?'开始针对性训练':'继续针对性训练','dimension-task','soft sm','pen',`data-id="${t.id}"`)).join('')}</div>`:`${c.observations.length?'<p class="field-note top16">根据本次关键观察生成的短训练可在“能力与训练”查看；没有完整材料时先补齐证据。</p>':''}`}</article>`;
}
async function open(){
 openModal('申论综合维度画像','<p class="field-note">正在读取本地记录，不调用模型…</p>');
 profile=await api('/api/shenlun/dimensions');
 openModal('申论综合维度画像',`<p class="small muted">${E(profile.note)}</p><p class="field-note">先区分“答案表现”与“原因假设”：漏点不等于业务不熟，总用时也不能说明慢在哪一步。不同题目相互验证后，判断才更有依据。</p><div class="row wrap top16">${btn('更新综合 AI 分析','learning-analysis-open','primary sm','spark')}${btn('去做申论题','shenlun-open','sm','book')}</div><div class="shenlun-dimension-grid top20">${profile.dimensions.map(c=>detailedCard(c,profile)).join('')}</div>`);
}
Object.assign(actions,{
 'shenlun-dimensions-open':open,
 'dimension-task':el=>actions['coach-task'](el),
 'dimension-source':el=>el.dataset.type==='training'?actions['coach-task'](el):actions['diagnose'](el)
});
})();
