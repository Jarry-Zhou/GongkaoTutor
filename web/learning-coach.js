'use strict';
(()=>{
const C={data:null,task:null,reading:null,saving:false};
const labels={elements:'关键要素',relation:'关系建模',formula:'列式',calculation:'计算',approximation:'近似与校验',business:'业务理解',points:'要点提炼',expression:'总结表达'};
const tone=state=>state==='较稳定'?'green':state==='待重新校验'?'orange':'';
const fields=q=>['申论','综合应用能力'].includes(q.module)?[['business','业务关系','谁负责、遇到什么问题、采取什么做法、形成什么效果'],['points','材料要点','记下你认为能用于回答的原文事实与要点'],['summary','总结句','写下你的概括句或本题中心句']]:[['elements','关键要素','求什么；对象、时间、单位、限制条件分别是什么'],['relation','关系与理由','这些条件如何关联；排除或选择的依据'],...(['资料分析','数量关系'].includes(q.module)?[['formula','算式','例如 120/(1+20%)，可本地核验加减乘除'],['result','计算结果','你的计算结果或近似结果'],['unit','单位与近似','量纲、单位换算、取近似的理由']]:[])];
S.coachSteps=(q,d,checked)=>`<details class="coach-steps"><summary>按步骤留下思路（选填）</summary><p class="field-note">只记录你实际做过的步骤。用于区分卡点，填写不会自动调用 AI。</p>${fields(q).map(([key,label,placeholder])=>`<label for="step-${key}">${label}</label><textarea id="step-${key}" data-coach-step="${key}" placeholder="${E(placeholder)}" ${checked?'disabled':''}>${E(d.steps?.[key]||'')}</textarea>`).join('')}${['资料分析','数量关系'].includes(q.module)?`${btn('核验这一步算术','coach-calculate','sm','',''+(checked?'disabled':''))}<div id="coach-calc-result" class="field-note" role="status"></div>`:''}</details>`;
document.addEventListener('input',event=>{
 const el=event.target;if(el.dataset.coachStep&&S.session?.status==='active'){
  const d=draft();d.steps={...(d.steps||{}),[el.dataset.coachStep]:el.value};scheduleSave();
 }
});
S.coachPage=async()=>{
 C.data=await api('/api/coach');const {abilities,tasks}=C.data;
 const ready=tasks.filter(t=>!t.stale&&['ready','active','paused'].includes(t.status));
 return pageHead('YOUR NEXT STEP','能力与训练','从真实作答形成假设，用短训练找到步骤，再用未见题验证迁移。',btn('查看 / 更新 AI 分析','learning-analysis-open','soft','spark'))+
 `<section class="coach-intro card"><div><h2>让结论成为下一次练习</h2><p class="small muted top12">AI 负责分析具体卡点。训练与复测会留下证据，逐步验证，而不是仅凭一次错题给你贴标签。</p></div><div class="coach-counts"><div><strong>${abilities.length}</strong><span>能力假设</span></div><div><strong>${ready.length}</strong><span>待做短训练</span></div><div><strong>${abilities.filter(a=>a.due).length}</strong><span>可复测能力</span></div></div></section>`+
 `<div class="coach-layout"><section class="stack"><div class="card-head"><h2>当前能力档案</h2>${pill('由证据更新','green')}</div>${abilities.length?abilities.map(a=>abilityCard(a,tasks)).join(''):`<section class="card">${empty('先做题，再形成个人档案','完成作答后，点击“查看 / 更新 AI 分析”。确认调用后，AI 会提出有证据关联的具体能力假设。',btn('查看待分析证据','learning-analysis-open','soft sm','spark'))}<p class="field-note">已有历史分析仍可查看；升级不会预填你的薄弱点。</p></section>`}</section><aside class="stack"><section class="card"><h2>短步骤训练</h2><p class="field-note">使用本次分析过的题目，聚焦一个步骤。重复题与提示后回答计作训练。</p>${tasks.length?tasks.map(taskCard).join(''):empty('等待 AI 制定针对性任务','AI 将根据你的实际作答生成训练，题干与材料保持关联。')}</section><section class="card"><h3>状态怎么变化</h3><p class="small muted top12">${E(C.data.note)}</p><p class="small muted top12">暂时改善后间隔一天复测；较稳定后间隔三天回访。相关材料变更会标记待重新校验。</p><p class="field-note">停留时长来自训练各步骤，支持暂停。仅凭总用时不能定位慢在哪一步。</p></section></aside></div>`;
};
function abilityCard(a,tasks){
 const linked=tasks.filter(t=>a.task_ids.includes(t.id)&&!t.stale&&t.status!=='answered');
 return `<article class="card coach-ability"><div class="row between wrap"><h3>${E(a.name)}</h3>${pill(a.state,tone(a.state))}</div><p class="tiny muted top12">${E(a.module)} · ${E(a.point)} · ${E(labels[a.stage])}</p><p class="prose top12">${E(a.hypothesis)}</p><div class="intro-box top16"><strong>下一步怎样做</strong><p class="small top12">${E(a.fix)}</p></div><p class="field-note">${E(a.confidence)} · 关联 ${a.evidence_attempt_ids.length} 次作答 · 独立复测通过 ${a.independent_successes} 题</p>${a.stale_question_ids.length?'<p class="inline-error">关联材料已修订。更新综合分析后再使用该结论。</p>':`<p class="field-note">${a.due?'已到可复测时间':'建议复测：'+fmtDate(a.due_at)}</p>`}<div class="row wrap top16">${linked[0]?btn('开始短训练','coach-task','primary sm','pen',`data-id="${linked[0].id}"`):''}${btn('未见题复测','coach-retest','soft sm','refresh',`data-id="${a.id}" ${a.stale_question_ids.length?'disabled':''}`)}${btn('查看依据','coach-evidence','sm','eye',`data-id="${a.id}"`)}</div></article>`;
}
function taskCard(t){
 const status=t.stale?'材料已变更':t.review?(t.review.assessment==='pass'?'AI 建议通过':t.review.assessment==='retry'?'建议再练':'仍需验证'):t.status==='answered'?'待确认 AI 评价':t.status==='paused'?'已暂停':t.status==='active'?'进行中':'未开始';
 return `<div class="coach-task-item"><strong class="small">${E(t.title)}</strong><p class="tiny muted top12">${E(labels[t.stage])} · ${t.prompts.length} 个短步骤</p><div class="row between top12">${pill(status,t.stale?'orange':'')}${btn(t.status==='answered'?'查看':'打开','coach-task','sm','',`data-id="${t.id}"`)}</div></div>`;
}
async function openTask(id){
 clearTimeout(C.saveTimer);
 C.task=await api('/api/coach/tasks/'+id);C.reading=null;
 if(C.task.question?.requires_image||C.task.question?.reading_source){
  try{C.reading=await api('/api/question-reading/'+C.task.question_id)}catch(e){C.reading={warnings:[e.message]}}
 }
 taskModal();
}
function sourceMarkup(){
 const q=C.task.question;if(!q)return '<p class="field-note">原题已不可用。</p>';
 const reading=C.reading;
 const assets=reading?[...(reading.material||[]),...(reading.question||[])]:q.visual?[q.visual]:[];
 return `<h3>关联原题与材料</h3><p class="tiny muted top12">${E(q.module)} · ${E(q.knowledge_points.join('、'))}</p><p class="prose top16">${E(q.reading_stem||q.stem)}</p>${Object.entries(q.options||{}).map(([k,v])=>`<p class="small top12">${E(k)}. ${E(v)}</p>`).join('')}${reading?.warnings?.length?`<p class="inline-error">${E(reading.warnings.join('；'))}</p>`:''}${assets.length?`<div class="coach-original">${assets.map(a=>`<img src="/api/visuals/${E(a.id)}" alt="关联原题区域">`).join('')}</div>`:''}${q.material?`<details class="top20" ${assets.length?'':'open'}><summary>关联材料全文</summary><div class="prose coach-fulltext">${E(q.reading_material||q.material)}</div></details>`:''}`;
}
function taskModal(){
 const t=C.task,done=t.status==='answered',active=t.status==='active',index=t.answers.length;
 const review=C.data?.tasks.find(x=>x.id===t.id)?.review;
 openModal(t.title,`<div class="coach-work"><section class="coach-source">${sourceMarkup()}</section><section class="coach-answer"><div class="row wrap">${pill(labels[t.stage],'green')}${pill('本题短训练 · 不计作独立复测')}</div>${t.stale?'<div class="inline-error top20">材料已变更，本训练保留历史。请更新 AI 综合分析。</div>':''}${t.answers.map((a,i)=>`<details class="coach-completed"><summary>步骤 ${i+1} · 页面停留 ${a.duration_seconds} 秒</summary><p class="small top12">${E(t.prompts[i])}</p><p class="prose top12">${E(a.text)}</p></details>`).join('')}${!done?`<h3 class="top20">步骤 ${index+1} / ${t.prompts.length}</h3><p class="prose top16">${E(t.prompts[index])}</p><label for="coach-response" class="top20">你的回答</label><textarea id="coach-response" placeholder="只回答这一步，留下实际判断依据…" ${active&&!t.stale?'':'disabled'}>${E(t.draft||'')}</textarea><p class="field-note">开始后按步骤记录停留时长；离开页面、走神或查资料时请暂停。关闭训练也会暂停。</p><div class="row wrap top16">${active?`${btn('保存并暂停','coach-task-pause','sm','clock')}${btn(index+1===t.prompts.length?'完成短训练':'提交本步','coach-task-answer','primary sm','check',t.stale?'disabled':'')}`:btn(t.status==='paused'?'继续本步骤':'开始本步骤','coach-task-start','primary sm','pen',t.stale?'disabled':'')}${btn('查看提示','coach-task-hint','sm','',t.stale?'disabled':'')}</div>${t.hint_used?`<div class="intro-box top20">${E(t.hint||'本训练未提供提示。')}</div><p class="field-note">本次已记录使用提示。</p>`:''}`:`<div class="intro-box top20"><strong>短训练已保存在本机</strong><p class="small top12">${review?E(review.feedback):'确认下一次综合分析后，AI 会结合本次回答、原有结论和新增作答评价这一步。'}</p>${review?`<p class="small top12">${E(review.next_step)}</p>`:''}</div><details class="top20"><summary>查看建议对照（AI 生成）</summary><p class="prose top12">${E(t.reference)}</p></details><div class="row wrap top20">${btn('确认分析范围','coach-task-analyze','soft','spark')}${btn('再练本步骤','coach-task-retry','sm','',''+(t.stale?'disabled':''))}${btn('返回能力与训练','coach-task-back','sm')}</div>`}</section></div>`);
}
async function taskAction(action,body={}){
 C.task=await api('/api/coach/tasks/'+C.task.id+'/'+action,'POST',body);taskModal();
}
async function saveTaskDraft(){
 const value=$('#coach-response')?.value;
 if(value!==undefined&&['active','paused'].includes(C.task?.status))await api('/api/coach/tasks/'+C.task.id+'/draft','POST',{text:value});
}
const baseClose=actions['close-modal'];
actions['close-modal']=async()=>{
 if($('#coach-response')&&C.task?.status==='active'){await saveTaskDraft();await api('/api/coach/tasks/'+C.task.id+'/pause','POST',{});C.task.status='paused'}
 baseClose();if(location.hash==='#coach')await render();
};
// Backdrop and Escape also use closeModal directly in the base app. Save and pause on dismissal.
new MutationObserver(()=>{
 if(C.task?.status==='active'&&!document.querySelector('.coach-work')){
  const id=C.task.id,value=C.task.draft||'';C.task.status='paused';clearTimeout(C.saveTimer);
  api('/api/coach/tasks/'+id+'/draft','POST',{text:value}).then(()=>api('/api/coach/tasks/'+id+'/pause','POST',{})).catch(()=>{});
 }
}).observe($('#modal-root'),{childList:true});
document.addEventListener('input',event=>{
 if(event.target.id==='coach-response'){
  if(C.task)C.task.draft=event.target.value;
  clearTimeout(C.saveTimer);C.saveTimer=setTimeout(()=>saveTaskDraft().catch(e=>toast(e.message,true)),500);
 }
});
document.addEventListener('visibilitychange',()=>{
 if(document.hidden&&C.task?.status==='active'&&$('#coach-response')){
  saveTaskDraft().then(()=>taskAction('pause')).catch(e=>toast(e.message,true));
 }
});
Object.assign(actions,{
 'coach-open':async()=>{closeModal();if(location.hash==='#coach')await render();else location.hash='coach'},
 'coach-task':el=>openTask(el.dataset.id),
 'coach-task-start':()=>taskAction('start'),
 'coach-task-retry':()=>taskAction('retry'),
 'coach-task-pause':async()=>{await saveTaskDraft();await taskAction('pause')},
 'coach-task-hint':async()=>{await saveTaskDraft();await taskAction('hint')},
 'coach-task-answer':async()=>{const value=$('#coach-response').value;await taskAction('answer',{text:value,stage_index:C.task.answers.length})},
 'coach-task-analyze':async()=>{await actions['close-modal']();await actions['learning-analysis-open']()},
 'coach-task-back':async()=>{await actions['close-modal']();location.hash='coach'},
 'coach-retest':async el=>{const s=await api('/api/coach/retest','POST',{ability_id:el.dataset.id});S.index=0;S.drafts={};closeModal();location.hash='session/'+s.id},
 'coach-evidence':async el=>{
  const a=C.data.abilities.find(a=>a.id===el.dataset.id),all=await api('/api/attempts');
  openModal(a.name+' · 证据',`<p class="field-note">${E(a.confidence)}。历史作答与成绩保持原样。</p>${a.evidence_attempt_ids.map(id=>{const r=all.find(r=>r.id===id);return r?`<section class="evidence"><p class="small">${E(r.question.stem.slice(0,260))}</p><p class="field-note">${fmtDate(r.created_at)} · ${r.correct===null?'待评阅':r.correct?'正确':'错误 / 漏答'} · ${r.independent?'独立未见题':'重复 / 有提示 / 不确定'}</p>${btn('查看单题记录','diagnose','sm','eye',`data-id="${E(id)}"`)}</section>`:''}).join('')}`);
 },
 'coach-calculate':async()=>{
  const s=draft().steps||{},r=await api('/api/coach/arithmetic','POST',{expression:s.formula,claimed:s.result});
  $('#coach-calc-result').textContent=(r.available?'算术结果：'+r.value+(r.matches_claim===false?'；与你记录的结果不一致':r.matches_claim===true?'；与你记录的结果一致':'')+'。':'')+r.note;
 }
});
})();
