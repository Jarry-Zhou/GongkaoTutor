'use strict';
(()=>{
const A={point:'',domain:'',preview:null,selected:null,busy:false,error:''};
S.learningAnalysisEntry=()=>`<section class="card learning-analysis-entry"><div><h3>个性化分析与训练</h3><p class="small muted top12">确认后再调用 AI。整合新增证据，更新能力假设，并安排短训练与未见题复测。</p></div><div class="row wrap">${btn('查看 / 更新 AI 综合分析','learning-analysis-open','soft','spark')}${btn('能力与训练','coach-open','sm','target')}${btn('申论维度画像','shenlun-dimensions-open','sm','chart')}</div></section>`;
function structuredMarkup(r){
 return `${r.step_diagnostics?.length?`<section class="diagnosis-section"><h3>具体步骤与材料依据</h3>${r.step_diagnostics.map(d=>`<article class="analysis-cause"><div class="row between wrap"><strong>${E(d.observation)}</strong>${pill(d.evidence_status,d.evidence_status==='待验证'?'orange':'green')}</div>${d.user_quote?`<p class="coach-evidence-quote">你的记录：${E(d.user_quote)}</p>`:''}<p class="prose top12">${E(d.explanation)}</p>${d.citations.map(c=>`<blockquote class="coach-evidence-quote">${E(c.paragraph_id)} · ${E(c.quote)}</blockquote>`).join('')}${d.coverage!=='complete'?'<p class="inline-error">本次未提供完整材料，不能据此认定遗漏或给出完整评价。</p>':''}${d.minimal_rewrite?`<details class="top12"><summary>最小修改建议</summary><p class="prose top12">${E(d.minimal_rewrite)}</p></details>`:''}${d.concise_rewrite?`<details class="top12"><summary>精简表达建议</summary><p class="prose top12">${E(d.concise_rewrite)}</p></details>`:''}${d.next_question?`<p class="small top12">下一步验证：${E(d.next_question)}</p>`:''}${btn('查看对应作答','diagnose','sm top12','eye',`data-id="${E(d.attempt_id)}"`)}</article>`).join('')}</section>`:''}${r.task_reviews?.length?`<section class="diagnosis-section"><h3>本次短训练反馈</h3>${r.task_reviews.map(t=>`<article class="analysis-cause"><p class="coach-evidence-quote">${E(t.answer_quote)}</p><p class="prose top12">${E(t.feedback)}</p><p class="small top12">${E(t.next_step)}</p></article>`).join('')}</section>`:''}${r.abilities?.length?`<section class="diagnosis-section"><h3>能力假设已保存</h3><p class="small muted top12">本次档案共 ${r.abilities.length} 项。训练、复测和材料变更会更新其状态。</p>${btn('进入能力与训练','coach-open','primary top16','target')}</section>`:''}`;
}
async function open(point='',domain=''){
 A.domain=domain;
 A.point=point;A.error='';A.selected=null;openModal(A.domain==='shenlun'?'申论个性化分析':'AI 共同原因分析','<p class="field-note">正在核对本地作答与已保存结论，不调用模型…</p>');
 A.preview=await api('/api/learning-analysis/preview','POST',{point,domain,shenlun_version:1,shenlun_dimensions_version:1});render();
}
function resultMarkup(run){
 if(!run)return '<div class="intro-box">尚未生成 AI 综合结论。本地单题证据和成绩已保留，可确认下方范围后分析。</div>';
 const r=run.result;
 return `<div class="row between wrap bottom16">${pill('已保存 · '+fmtDate(run.created_at),'green')}${pill('累计整合 '+run.covered_count+' 条作答')}</div><div class="prose">${E(r.summary)}</div>${r.common_causes?.length?`<div class="diagnosis-section"><h3>具体共同原因</h3>${r.common_causes.map(c=>`<section class="analysis-cause"><div class="row between wrap"><strong>${E(c.cause)}</strong>${pill(c.confidence,c.confidence==='有证据支持'?'green':'orange')}</div><p class="small muted top12">${E(c.fix)}</p><p class="small top12">验证方式：${E(c.verify)}</p><p class="field-note">关联 ${c.evidence_attempt_ids.length} 次已记录作答</p></section>`).join('')}</div>`:''}${r.progress?`<div class="diagnosis-section"><h3>这次有哪些变化</h3><div class="prose">${E(r.progress)}</div></div>`:''}${r.next_actions?.length?`<div class="diagnosis-section"><h3>下一步</h3>${r.next_actions.map((t,i)=>`<p class="small top12">${i+1}. ${E(t)}</p>`).join('')}</div>`:''}${S.shenlunDimensionMarkup?.(r.shenlun_dimension_profile)||''}${structuredMarkup(r)}${S.shenlunReviewMarkup?.(r.shenlun_reviews)||''}<p class="field-note">AI 结论用于复习，不改动已记录成绩。没有思路证据的原因仍需验证。</p>`;
}
function render(){
 const p=A.preview,run=A.selected||p.latest;
 openModal(A.domain==='shenlun'?'申论个性化分析':'AI 共同原因分析',`${A.domain==='shenlun'?'<p class="field-note">本次只处理申论与综合应用能力主观题，与全局分析共用记录；下方可能包含上次全局结论。</p>':''}${A.point?`<p class="small muted bottom16">本次聚焦：${E(A.point)}。与综合分析共用已处理记录，保留其他知识点的已有结论。</p>`:''}${resultMarkup(run)}<section class="analysis-confirm"><h3>本次分析范围</h3>${p.dimensions_mode?'<p class="field-note">综合分析包含申论七维画像：层次、主旨、业务、找点、论证、表达、效率。没有申论新证据时保留旧结论。</p>':''}<p class="small top12">新增 ${p.new_count} 条作答，补充或反馈更新 ${p.revised_count} 条。此前 ${p.covered_count} 条已整合；另有 ${p.task_count||0} 份短训练待评价。</p>${p.pending_count?`<p class="small muted top12">本次处理 ${p.batch_count} 条作答和 ${p.task_count||0} 份短训练；${p.pending_count>p.batch_count+(p.task_count||0)?'其余 '+(p.pending_count-p.batch_count-(p.task_count||0))+' 条留待下一批确认。':''}发送上次结论、本次新证据及相关单题裁图${p.answer_images?'，含你上传的草稿 '+p.answer_images+' 张':''}；不会再次提交已处理的旧错题全文。</p><p class="field-note">模型：${E(S.boot.settings.model||'未配置')}。点击确认后会使用已配置的 API，产生服务商费用。</p>${btn(A.busy?'正在调用 API 并保存结论…':'确认并调用 API','learning-analysis-confirm','primary top20','spark',A.busy?'disabled':'')}`:'<p class="small muted top12">暂无新增或更新证据，直接读取已保存结果，无须调用 API。</p>'}${A.error?`<div class="inline-error">${E(A.error)}<br>已有结论保留，本次未完成的证据仍待分析。</div>`:''}</section>${p.history.length?`<details class="analysis-history"><summary>已保存的历次分析（${p.history.length}）</summary>${p.history.map(r=>`<div class="row between top12"><span class="tiny muted">${fmtDate(r.created_at)} · 累计 ${r.covered_count} 条 · 本次新增 ${r.new_count} 条</span>${btn('查看结论','learning-analysis-history','sm','','data-id="'+r.id+'"')}</div>`).join('')}</details>`:''}<div class="row wrap top20">${btn('查看本地单题证据','learning-analysis-evidence','sm')}${btn('重新核对待分析数量','learning-analysis-refresh','sm','refresh',A.busy?'disabled':'')}</div>`);
}
async function confirm(){
 if(A.busy||!A.preview.pending_count)return;
 A.busy=true;A.error='';render();
 try{
  const result=await api('/api/learning-analysis/run','POST',{point:A.point,domain:A.domain,confirmed:true,plan_token:A.preview.plan_token,coach_version:1,shenlun_version:1,shenlun_dimensions_version:1});
  A.preview=await api('/api/learning-analysis/preview','POST',{point:A.point,domain:A.domain,shenlun_version:1,shenlun_dimensions_version:1});A.selected=result;toast(result.reused?'已读取保存结果，未调用模型':'分析结论已保存，下次将继续整合新增证据');
 }catch(e){A.error=e.message}finally{A.busy=false;render()}
}
async function evidence(){
 const records=await api('/api/attempts');
 openModal('本地作答证据',`${btn('返回综合分析','learning-analysis-back','sm')}<p class="field-note top12">此页面读取本地记录，不调用模型。</p>${records.filter(a=>(!A.point||a.question.knowledge_points.includes(A.point))&&(!A.domain||['申论','综合应用能力'].includes(a.question.module)&&['essay','short'].includes(a.question.type))).slice(0,50).map(a=>`<div class="evidence"><p>${E((S.questionStem?.(a.question)||a.question.stem).slice(0,180))}</p><p class="tiny muted">${E(a.question.module)} · ${a.correct===true?'答对':a.correct===false?'错误 / 漏答':'待评阅'} · ${fmtDate(a.created_at)}</p><p class="small">${a.response.reason?'你的思路：'+E(a.response.reason):'未记录关键思路，不能直接确定个人错因。'}</p>${btn('查看单题证据','diagnose','sm','','data-id="'+a.id+'"')}</div>`).join('')||'<p class="field-note">暂无已完成作答。</p>'}`);
}
Object.assign(actions,{'learning-analysis-open':()=>open(),'learning-analysis-confirm':confirm,'learning-analysis-refresh':()=>open(A.point,A.domain),
 'shenlun-analyze':()=>open('','shenlun'),'learning-analysis-back':render,'learning-analysis-evidence':evidence,
 'learning-analysis-history':async el=>{A.selected=await api('/api/learning-analysis/'+el.dataset.id);render()},
 'topic-ai':()=>open(S.topic)});
})();
