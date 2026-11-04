'use strict';
(()=>{
const H={data:null,contexts:{},editId:null,busy:false};
const kinds={summary:'归纳概括',analysis:'综合分析',proposal:'对策启示',document:'公文写作',essay:'大作文',unknown:'待确认题型'};
const verdict={covered:'已覆盖',partial:'部分覆盖',missing:'建议补充',uncertain:'待核验'};
const relevant=q=>q&&['申论','综合应用能力'].includes(q.module)&&['short','essay'].includes(q.type);
S.shenlunQuestionLabel=q=>relevant(q)?'分值与字数见题干':null;
S.shenlunQuestionTools=q=>relevant(q)?`<div class="shenlun-question-tools"><span class="small muted">申论分值与字数以题干或你的确认为准</span>${btn('核对题目条件','shenlun-context','sm','eye',`data-id="${q.id}"`)}</div>`:'';
S.shenlunPage=async()=>{
 H.data=await api('/api/shenlun');const d=H.data;
 return pageHead('SHENLUN · READ, ORGANIZE, EXPRESS','申论专训','把材料读成要点，把要点组织成回答。结合你的实际作答，定位需要练的那一步。',`${btn('确认分析范围','shenlun-analyze','primary','spark')}${btn('方法来源','shenlun-about','sm','book')}`)+
 `<section class="card shenlun-hero"><div><h2>采点、归并、表达，分别验证</h2><p class="small muted top12">已接入 Shenlun Master 的小题与大作文方法。分析会回到本题材料和你的原句，训练与能力档案继续沿用现有记录。</p></div><div class="row wrap">${pill(d.skill.ready?'本地规则已就绪':'规则包待修复',d.skill.ready?'green':'orange')}${pill('API 调用前确认')}</div></section>`+
 `${S.shenlunDimensionSection?.(d.dimensions)||''}<section class="shenlun-types">${Object.entries(kinds).map(([key,label])=>`<article class="card"><h3>${label}</h3><p class="shenlun-number">${d.inventory[key]||0}<span> 题可练</span></p>${btn(key==='unknown'?'先选题核对':'开始一题','shenlun-start','soft sm','pen',`data-kind="${key}" ${!d.inventory[key]?'disabled':''}`)}</article>`).join('')}</section>`+
 `<div class="shenlun-layout"><section class="stack"><div class="card-head"><h2>我的申论报告</h2>${btn('查看能力与短训练','coach-open','sm','target')}</div>${d.reviews.length?d.reviews.map((r,i)=>`<details class="card shenlun-review" ${i===0?'open':''}><summary><strong>${E(r.kind_label)} · ${E(r.title.slice(0,80))}</strong><span class="tiny muted">${fmtDate(r.created_at)}</span></summary>${report(r)}</details>`).join(''):`<section class="card">${empty('先完成一份申论作答','这里不会预填你的问题。做题后确认分析，AI 才会结合材料、原句和已保存结论生成报告。',btn('从题库开始','shenlun-start','primary sm','pen','data-kind="all"'))}<p class="field-note">原有客观题分析与申论共用增量记录。进入此处分析，只发送本次申论证据。</p></section>`}<section class="card"><details><summary>查找题目与核对条件</summary><p class="field-note">题型不明、分值或字数识别有误时，可在这里修正。条件变更只影响对应题目的下次分析。</p><label for="shenlun-question-search">搜索题干</label><input id="shenlun-question-search" placeholder="输入题干关键词"><div id="shenlun-question-list">${questionRows(d.questions)}</div></details></section></section>
 <aside class="stack"><section class="card"><h2>跨题复发观察</h2><p class="field-note">${E(d.note)}</p>${d.losses.length?d.losses.map(loss=>`<section class="shenlun-loss"><div class="row between wrap"><strong>${E(loss.code+' · '+loss.label)}</strong>${pill(loss.state+' · '+loss.count+' 题',loss.count>1?'orange':'')}</div><p class="small muted top12">${E(loss.occurrences[0].action)}</p>${loss.count>1?`<p class="field-note">上次依据：${E(loss.occurrences[1].title.slice(0,100))}</p>`:''}<p class="field-note">归因建议：${E(loss.occurrences[0].cause)}</p></section>`).join(''):empty('等不同题目提供证据','同一题重评不会被算成反复出现的弱点。')}<p class="field-note">“多题反复”表示已记录的出现次数，不是永久能力标签。误判可在报告里撤销。</p></section>
 <section class="card"><h3>看报告时关注什么</h3><p class="small muted top12">先核对材料引文与原句，再看哪个要点未表达清楚。两版参考作答用于比较组织方式，优先学适合本次问题的那一步。</p><p class="field-note">分值未确认不默认 40 分；材料不全不估分。模拟配点结果不会改动你的原成绩。</p></section></aside></div>`;
};
function questionRows(rows){
 return rows.slice(0,90).map(q=>`<div class="shenlun-question-row"><div><p class="small">${E(q.title)}</p><p class="tiny muted top12">${E(q.context.kind_label)} · ${q.context.max_score?E(q.context.max_score)+' 分（'+E(q.context.score_source)+'）':'分值未确认'} · ${q.context.word_max?'字数上限 '+q.context.word_max:'字数上限未确认'}</p></div>${btn('核对','shenlun-context','sm','',`data-id="${q.id}"`)}</div>`).join('')||'<p class="field-note">没有符合条件的题目。</p>';
}
function quoteMarkup(citations){return (citations||[]).map(c=>`<blockquote class="coach-evidence-quote"><strong>${E(c.paragraph_id)}</strong> · ${E(c.quote)}</blockquote>`).join('')}
function report(r){
 const ctx=r.context;
 return `<div class="row wrap top20">${pill(r.stale?'材料或条件已变更，待重新校验':r.transcription_pending?'手写文字待核对':r.complete?'材料覆盖完整':'材料不完整',r.stale||!r.complete?'orange':'green')}${pill('AI 建议 · 可核对、可撤销')}</div><p class="field-note">${ctx.answer_characters} 个非空字符（含标点，仅作参考）${ctx.word_min?' · 要求至少 '+ctx.word_min+' 字':''}${ctx.word_max?' · 上限 '+ctx.word_max+' 字':''}${ctx.over_limit?' · 超过记录上限':''}${ctx.below_limit?' · 低于记录下限':''}</p>
 ${r.transcription_pending?`<section class="shenlun-transcription intro-box top16"><h3>先核对手写转写</h3><p class="field-note">这份文字尚不作为判错依据。请对照你的草稿修正后确认；[字迹不清]处需要你补全。${r.transcription_confirmed?'你已保存确认文字，下一次确认分析范围后生成报告。':''}</p>${r.draft_urls?.length?`<details class="top16"><summary>对照原草稿</summary>${r.draft_urls.map(url=>`<img src="${E(url)}" alt="用户上传的原始草稿" style="display:block;max-width:100%;max-height:420px;object-fit:contain;margin-top:12px">`).join('')}</details>`:''}<label for="sl-transcription-${r.attempt_id}">转写文字</label><textarea id="sl-transcription-${r.attempt_id}">${E(r.confirmed_transcription_text||r.transcription)}</textarea>${btn('确认转写文字','shenlun-transcription-save','primary sm top12','check',`data-id="${r.attempt_id}"`)}</section>`:''}
 ${r.score.available?`<div class="intro-box top16"><strong>模拟估分：${r.score.value} / ${r.score.max_score}</strong><p class="small top12">${E(r.score.basis)}</p><p class="field-note">${E(r.score.note)}</p></div>`:`<p class="field-note">${E(r.score.reason)}</p>`}
 <div class="row wrap top12">${btn('核对题目条件','shenlun-context','sm','',`data-id="${r.question_id}"`)}${btn('查看原作答','diagnose','sm','eye',`data-id="${r.attempt_id}"`)}</div>
 <h3 class="top20">材料要点与作答核对</h3><p class="field-note">以下为基于已提供材料的建议要点，不冒充官方采分细则。</p>${r.points.map(p=>`<section class="shenlun-point"><div class="row between wrap"><strong>${E(p.label)}</strong>${pill(verdict[p.verdict],p.verdict==='missing'?'orange':'')}</div>${p.user_quote?`<p class="coach-evidence-quote">你的原句：${E(p.user_quote)}</p>`:''}<p class="small top12">${E(p.explanation)}</p>${quoteMarkup(p.citations)}<p class="small top12">怎样改：${E(p.improve)}</p>${p.max_score!==undefined?`<p class="field-note">建议配点 ${p.max_score} · 本项模拟 ${p.awarded}</p>`:''}</section>`).join('')||'<p class="field-note">本次没有可完整核验的材料要点；先补齐材料再评价遗漏。</p>'}
 ${r.findings.length?`<h3 class="top20">本次需要练的步骤</h3>${r.findings.map(f=>`<section class="shenlun-point ${f.dismissed?'shenlun-dismissed':''}"><div class="row between wrap"><strong>${E(f.code+' · '+f.label)}</strong>${pill(f.dismissed?'已撤销':'AI 建议',f.dismissed?'':'orange')}</div><p class="small top12">${E(f.description)}</p>${f.user_quote?`<p class="coach-evidence-quote">${E(f.user_quote)}</p>`:''}<p class="small top12">${E(f.action)}</p><p class="field-note">归因：${E(f.cause)}${f.cause_quote?' · 依据：'+E(f.cause_quote):'，没有足够过程证据时不归咎于知识或态度。'}</p>${f.feedback?`<p class="field-note">你的修正：${E(f.feedback.reason)}</p>`:''}${btn(f.dismissed?'恢复此判断':'撤销此判断','shenlun-feedback','sm top12','',`data-id="${f.id}" data-dismissed="${!f.dismissed}"`)}</section>`).join('')}`:''}
 ${r.rewrites.length?`<h3 class="top20">接着你的原句改</h3>${r.rewrites.map(w=>`<div class="shenlun-rewrite"><p class="small muted">原句：${E(w.original)}</p><p class="prose top12">建议：${E(w.replacement)}</p><p class="field-note">${E(w.why)}</p>${quoteMarkup(w.citations)}</div>`).join('')}`:''}
 ${r.reference_versions.length?`<h3 class="top20">两种组织方式，结合本题比较</h3><div class="shenlun-reference-grid">${r.reference_versions.map(v=>`<section class="shenlun-reference"><h4>${E(v.style)}</h4><p class="prose top16">${E(v.text)}</p><p class="field-note">${v.characters} 个非空字符${v.over_limit?' · 超过本题记录上限，请先精简':''}</p><details><summary>材料依据</summary>${quoteMarkup(v.citations)}</details></section>`).join('')}</div><p class="prose top16">${E(r.comparison)}</p>`:''}
 ${r.kind==='essay'?`<h3 class="top20">主题与论证关系</h3><p class="field-note">主题结构建议：${E(r.theme_type||'待确认')}。结构自洽优先，不强制套用固定公式。</p>${r.structure.map(s=>`<section class="shenlun-point"><p class="coach-evidence-quote">${E(s.user_quote)}</p><p class="small top12">主张：${E(s.claim)}</p><p class="small top12">论证关系：${E(s.mechanism)}</p><p class="small top12">怎样改：${E(s.fix)}</p></section>`).join('')}`:''}
 ${r.advice.length?`<h3 class="top20">下一次只改这几步</h3>${r.advice.map((t,i)=>`<p class="small top12">${i+1}. ${E(t)}</p>`).join('')}`:''}<div class="row wrap top20">${btn('查看能力与短训练','coach-open','soft sm','target')}${btn('核对下一批分析范围','shenlun-analyze','sm','spark')}</div>`;
}
S.shenlunReviewMarkup=reviews=>reviews?.length?`<section class="diagnosis-section"><h3>申论专项报告已保存</h3>${reviews.map(r=>`<p class="small top12">${E(r.kind_label)} · ${r.points.length} 项材料核对${r.score.available?' · 模拟 '+r.score.value+'/'+r.score.max_score:' · 定性反馈'} · ${r.findings.length} 项训练建议</p>`).join('')}<p class="field-note">打开专训页查看原句、材料引文、表达改写与参考作答对照。</p>${btn('查看申论报告','shenlun-open','primary top16','book')}</section>`:'';
async function openContext(id){
 H.editId=id;const ctx=await api('/api/shenlun/contexts/'+id);H.contexts[id]=ctx;
 openModal('核对申论题目条件',`<p class="field-note">这些条件决定题型方法、字数提示及是否能给模拟估分。留空的分值和字数按题干提取；无法识别时保持未确认。不会改动历史成绩。</p><div class="form-grid top20"><div class="wide"><label for="sl-kind">题型</label><select id="sl-kind"><option value="auto">按题干自动识别</option>${Object.entries(kinds).map(([k,v])=>`<option value="${k}" ${ctx.kind===k?'selected':''}>${v}</option>`).join('')}</select></div><div><label for="sl-max-score">本题实际满分</label><input id="sl-max-score" type="number" min="0.5" max="100" step="0.5" value="${ctx.max_score??''}" placeholder="不清楚则留空"><p class="field-note">当前来源：${E(ctx.score_source)}</p></div><div><label for="sl-word-min">字数下限（如有）</label><input id="sl-word-min" type="number" min="1" max="10000" value="${ctx.word_min??''}" placeholder="无明确下限可留空"></div><div><label for="sl-word-max">字数上限（如有）</label><input id="sl-word-max" type="number" min="1" max="10000" value="${ctx.word_max??''}" placeholder="不清楚则留空"></div></div><div class="row wrap top20">${btn('保存题目条件','shenlun-context-save','primary','check')}${btn('按这道题开始作答','shenlun-one','soft','pen',`data-id="${id}"`)}</div>`);
}
async function start(kind='all',qid=null){
 if(kind==='unknown'&&!qid){openModal('先核对题型',`<p class="field-note">这些题干暂不能可靠自动分类。选一题核对后即可开始。</p>${questionRows(H.data.questions.filter(q=>q.context.kind==='unknown'))}`);return}
 if(location.hash.startsWith('#session/')&&S.session?.status==='active')await flush();
 const s=await api('/api/practice-sessions','POST',{shenlun_only:true,...(kind!=='all'?{shenlun_kind:kind}:{}),...(qid?{question_ids:[qid]}:{}),count:1,minutes:kind==='essay'?60:20,feedback:'end',title:'申论 · '+(kinds[kind]||'材料作答')});
 S.index=0;S.drafts={};closeModal();location.hash='session/'+s.id;
}
const oldDiagnoseAI=actions['diagnose-ai'],oldFollowup=actions['answer-followup'];
actions['diagnose-ai']=async()=>{
 if(relevant(S.diag?.display_question)){
  const response=$('#followup')?.value.trim();if(response)await api('/api/diagnoses','POST',{attempt_id:S.attemptId,use_ai:false,response});
  return actions['shenlun-analyze']();
 }
 return oldDiagnoseAI();
};
actions['answer-followup']=async()=>{
 if(relevant(S.diag?.display_question)&&S.diag.engine==='model'){
  const response=$('#followup')?.value.trim();if(response)await api('/api/diagnoses','POST',{attempt_id:S.attemptId,use_ai:false,response});
  return actions['shenlun-analyze']();
 }
 return oldFollowup();
};
document.addEventListener('input',event=>{
 if(event.target.id==='shenlun-question-search'){
  const term=event.target.value.trim();$('#shenlun-question-list').innerHTML=questionRows(H.data.questions.filter(q=>q.title.includes(term)));
 }
});
Object.assign(actions,{
 'shenlun-open':async()=>{closeModal();if(location.hash==='#shenlun')await render();else location.hash='shenlun'},
 'shenlun-start':el=>start(el.dataset.kind||'all'),
 'shenlun-one':async el=>{
  await api('/api/shenlun/contexts/'+H.editId,'POST',{kind:$('#sl-kind').value,max_score:$('#sl-max-score').value,word_min:$('#sl-word-min').value,word_max:$('#sl-word-max').value});
  await start('all',el.dataset.id);
 },
 'shenlun-context':el=>openContext(el.dataset.id),
 'shenlun-context-save':async()=>{
  await api('/api/shenlun/contexts/'+H.editId,'POST',{kind:$('#sl-kind').value,max_score:$('#sl-max-score').value,word_min:$('#sl-word-min').value,word_max:$('#sl-word-max').value});
  toast('题目条件已保存在本机；相关分析下次重新核对');closeModal();if(location.hash==='#shenlun')await render();
 },
 'shenlun-feedback':el=>{
  H.findingId=el.dataset.id;H.dismissed=el.dataset.dismissed==='true';
  openModal(H.dismissed?'撤销此项判断':'恢复此项判断',`<p class="field-note">原报告保留，当前复发计数会同步调整。你的说明也会作为对应题目的新增证据，供下次确认分析时修正。</p><label for="sl-feedback" class="top20">说明原因</label><textarea id="sl-feedback" placeholder="例如：这一点我已在第二句回答，属于含义相同的表达。"></textarea>${btn('保存修正','shenlun-feedback-save','primary top20','check')}`);
 },
 'shenlun-feedback-save':async()=>{
  await api('/api/shenlun/findings/'+H.findingId+'/feedback','POST',{dismissed:H.dismissed,reason:$('#sl-feedback').value});closeModal();toast('修正已保存在本机，未调用模型');await render();
 },
 'shenlun-transcription-save':async el=>{
  await api('/api/shenlun/transcriptions/'+el.dataset.id,'POST',{confirmed:true,text:$('#sl-transcription-'+el.dataset.id).value});
  toast('转写文字已在本机确认；再次核对分析范围后才会调用模型');await render();
 },
 'shenlun-about':()=>openModal('方法来源与适配',`<div class="prose">规则来源：<a href="${E(H.data.skill.repository)}" target="_blank" rel="noreferrer">coffe-d / Shenlun.skill · Shenlun Master</a>，保留 MIT 许可与署名。
 小题参考白鹭与小马哥的材料阅读和组织方式，大作文参考袁东的论点与论证方法。这些属于上游项目整理建议，不冒充官方标准。
 应用只加载对应题型相关节选。原规则中固定总括句、领域分类、机械字数比例、缺省40分及与材料证据相冲突的要求，不作硬性评分依据。
 不导入原讲义或上游真题语料，不执行上游脚本，不自动联网、修改规则或额外调用模型。
 本机保留原规则文档、许可和固定版本，付费分析仍由你在预览后确认。</div><p class="field-note">固定版本：${E(H.data.skill.commit?.slice(0,12)||'待修复')} · ${E(H.data.skill.files||0)} 份规则与许可文件</p>`)
});
})();
