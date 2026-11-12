'use strict';
(()=>{
let poll=null;
const allowed=new Set(['p','br','table','thead','tbody','tr','th','td','sup','sub','strong','em','b','i','span','ul','ol','li']);
function rich(nodes,depth=0){
 if(!Array.isArray(nodes)||depth>30)return '';
 return nodes.slice(0,20000).map(n=>{
  if(!n||typeof n!=='object')return '';
  if(n.tag==='text')return E(String(n.text||''));
  if(n.tag==='missing')return '<span class="national-missing">【来源配图缺失，待核对】</span>';
  if(n.tag==='img'){
   if(!/^[a-f0-9]{64}$/.test(n.asset||''))return '';
   const w=Math.max(1,Math.min(10000,Number(n.width)||1)),h=Math.max(1,Math.min(10000,Number(n.height)||1));
   return `<img src="/api/national-assets/${n.asset}" width="${w}" height="${h}" alt="${E(n.label||'题目配图')}" data-action="national-image" data-asset="${n.asset}" role="button" tabindex="0" title="点击放大配图" loading="lazy">`;
  }
  if(!allowed.has(n.tag))return '';
  const attrs=['td','th'].includes(n.tag)?['rowspan','colspan'].filter(k=>Number.isInteger(n[k])&&n[k]>=1&&n[k]<=20).map(k=>` ${k}="${n[k]}"`).join(''):'';
  return n.tag==='br'?'<br>':`<${n.tag}${attrs}>${rich(n.children,depth+1)}</${n.tag}>`;
 }).join('');
}
function field(q,key){return q.rich_content?`<div class="national-rich">${rich(q.rich_content[key]||[])}</div>`:null}
S.nationalStem=q=>{
 if(!q.rich_content)return null;
 const x=q.true_exam||{};
 return `<div class="national-source-line">${E(x.paper||q.source)} · 模块内第 ${E(x.module_number||q.source_number||'')} 题<br><span>来源整理 / 网友回忆版，非官方逐题核验</span></div>${field(q,'stem')}`;
};
S.nationalOption=(q,key)=>q.rich_content?`<span class="national-rich">${rich(q.rich_content.options?.[key]||[])}</span>`:null;
S.nationalExplanation=q=>q.rich_content?.explanation?`${field(q,'explanation')}${q.source_warnings?.length?`<p class="national-missing">${q.source_warnings.map(E).join('；')}</p>`:''}`:null;
S.nationalReview=q=>q.rich_content?`<details class="reading-review"><summary>核对真题题面与完整材料</summary>${field(q,'material')}${S.nationalStem(q)}<div class="question-preview-options">${Object.keys(q.options||{}).map(k=>`<div>${E(k)}. ${S.nationalOption(q,k)}</div>`).join('')}</div></details>`:null;
const priorReading=S.isReadingQuestion,priorMaterial=S.questionMaterial,priorReview=S.questionReviewReading;
const hasMaterial=q=>q.rich_content&&String(q.material||'').trim().length>0;
S.isReadingQuestion=q=>q.rich_content?hasMaterial(q):priorReading?.(q);
S.questionMaterial=q=>{
 if(!q.rich_content)return priorMaterial?.(q);
 if(!hasMaterial(q))return '';
 return `<div class="reading-layout national-reading"><section class="reading-panel"><div class="reading-heading"><div><h3>本组资料</h3><span>完整材料与原始表格 / 图形，支持滚动</span></div></div><div class="reading-viewport national-material" tabindex="0" aria-label="完整真题材料，可滚动">${field(q,'material')}</div></section><section class="reading-answer"><div class="reading-answer-title">当前题目 <span>模块内第 ${E(q.source_number||'')} 题</span></div>`;
};
S.questionReviewReading=q=>q.rich_content?`<details class="reading-review"><summary>查看本题完整资料</summary>${field(q,'material')}</details>`:priorReview?.(q);
S.nationalEntry=()=>`<section class="card national-entry"><div><h2>国考真题库</h2><p class="small muted top12">2016—2026 年行测 · 保留答案、解析、配图与原始来源。旧题库可恢复。</p></div>${btn('查看 / 载入国考真题','national-open','soft','book')}</section>`;
function panel(s){
 const r=s.report||{},j=s.job||{},busy=j.status==='running';
 return `<p class="small muted">来源：ERRRC/xingcezhenti · 固定版本 ${E(s.commit.slice(0,12))}。${E(s.scope)}</p><div class="intro-box top20"><strong>${s.installed?'当前使用国考真题':'当前尚未启用此版本国考真题'}</strong>${s.installed?`<p class="small top12">${r.questions} 条试卷题目记录 · ${r.papers} 个卷型索引 · ${r.unique_content} 个题面指纹 · ${r.images} 张来源配图</p><p class="field-note">同题可在不同试卷重复收录。来源答案与解析未逐题官方核验，不把重复记录算作独立题量。</p>`:`<p class="small top12">首次需下载约 ${Math.ceil(s.download_bytes/1024/1024)} MB。下载校验通过后替换当前题库，之后可离线练习。</p>`}<p class="field-note">旧题库、历史作答、成绩和知识资料均保留。此源只含行测，原申论题留在旧题库归档。</p></div>${j.status?`<div class="national-job top20" role="status"><strong>${busy?'正在处理':j.status==='completed'?'处理完成':j.status==='failed'?'本次未完成':'上次处理被中断'}</strong><p>${E(j.phase||'')}${j.total?' · '+j.done+'/'+j.total:''}</p>${j.error?`<p class="field-note">${E(j.error)}</p>`:''}</div>`:''}<div class="row wrap top20">${s.installed?'':btn(busy?'正在下载与校验…':'下载并替换当前题库','national-confirm','primary','download',busy?'disabled':'')}${btn('更新状态','national-refresh','sm','refresh')}${s.can_restore?btn('恢复旧题库','national-restore-open','sm','refresh'):''}</div><p class="field-note top20">项目仅分发来源清单和适配代码，题面、解析和图片下载后保存在本机，不改挂为MIT内容。不会调用付费模型。</p>`;
}
async function open(){
 clearTimeout(poll);openModal('国考真题库','<p class="field-note">读取本地状态…</p>');
 const s=await api('/api/national-bank/status');S.nationalState=s;
 openModal('国考真题库',panel(s));watch(s);
}
function watch(s){
 if(s.job?.status==='running')poll=setTimeout(async()=>{
  if(!document.querySelector('[data-action="national-refresh"]'))return;
  try{const next=await api('/api/national-bank/status');S.nationalState=next;$('#modal-body').innerHTML=panel(next);watch(next);
   if(next.job?.status==='completed'){await refresh();await render();toast('国考真题已启用，旧题库已归档保留')}
  }catch(e){toast(e.message,true)}
 },1500);
}
Object.assign(actions,{
 'national-open':open,'load-demo':open,'national-refresh':open,
 'national-confirm':()=>openModal('确认下载并替换题库',`<p>将下载固定来源的国考行测题目、答案、解析和配图，校验通过后启用。当前题库保留在可恢复归档，历史作答、成绩和知识资料保留。</p><p class="field-note top12">首次约31 MB，需要网络。不是模型调用，不产生API费用。只有全部处理成功才切换题库。</p><div class="row top20">${btn('取消','close-modal')}${btn('确认下载并替换','national-install','primary','download')}</div>`),
 'national-install':async()=>{await api('/api/national-bank/install','POST',{confirmed:true});await open()},
 'national-restore-open':()=>openModal('恢复旧题库',`<p>将上次替换前的题库恢复为当前题库。新真题仍保存在本机，原作答与成绩不改动。</p><div class="row top20">${btn('取消','close-modal')}${btn('确认恢复旧题库','national-restore','primary')}</div>`),
 'national-restore':async()=>{await api('/api/national-bank/restore','POST',{confirmed:true});closeModal();await refresh();await render();toast('旧题库已恢复，新真题仍保存在本机')},
 'national-image':el=>{if(/^[a-f0-9]{64}$/.test(el.dataset.asset||''))openModal('题目配图',`<img class="national-enlarged" src="/api/national-assets/${el.dataset.asset}" alt="题目配图原貌">`)}
});
document.addEventListener('keydown',e=>{if((e.key==='Enter'||e.key===' ')&&e.target.matches('img[data-action="national-image"]')){e.preventDefault();actions['national-image'](e.target)}});
})();
