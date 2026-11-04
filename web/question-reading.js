'use strict';
(()=>{
const cache=new Map(),pending=new Map(),positions=new Map(),zooms=new Map();
const figure=q=>q.reading_source?.presentation==='figure';
const hasRegion=q=>!!(q.reading_source&&q.page_images?.length);
const enabled=q=>hasRegion(q)&&(q.module==='资料分析'||figure(q));
S.hasQuestionRegion=hasRegion;
S.questionStem=q=>{let t=q.reading_stem??q.stem;if(!figure(q)||q.module!=='判断推理')return t;return t.split(/\n\s*\n|\n(?=\s*(?:[?？A-D①②③④⑤⑥]|\[图形))/)[0].trim()};
S.isReadingQuestion=enabled;
function textMarkup(value){
 const lines=String(value||'').split('\n');let out='',table=[];
 const flush=()=>{if(!table.length)return;out+='<div class="reading-table-scroll"><table>'+table.filter(l=>!/^\s*\|?[\s|:-]+\|?\s*$/.test(l)).map((l,i)=>'<tr>'+l.replace(/^\s*\||\|\s*$/g,'').split('|').map(c=>`<${i?'td':'th'}>${E(c.trim())}</${i?'td':'th'}>`).join('')+'</tr>').join('')+'</table></div>';table=[]};
 for(const line of lines){if(line.trim().startsWith('|')&&line.trim().endsWith('|'))table.push(line);else{flush();out+=E(line)+'\n'}}flush();return out;
}
S.questionMaterial=q=>{
 if(!enabled(q))return q.material?`<div class="material top20">${E(q.material)}</div>`:'';
 const group=q.group_id||q.id,isFigure=figure(q);
 return `<div class="reading-layout"><section class="reading-panel" data-reading-group="${E(group)}"><div class="reading-heading"><div><h3>${isFigure?'题目图形':'题目资料'}</h3><span>${isFigure?'当前题干、图形与选项':'保留表格与图表原貌'}</span></div><div class="reading-tools">${btn('−','reading-zoom-out','sm','','aria-label="缩小资料"')}${btn('适宽','reading-fit','sm','','aria-label="资料适合宽度"')}${btn('+','reading-zoom-in','sm','','aria-label="放大资料"')}</div></div><div class="reading-viewport" tabindex="0" aria-label="题目资料，可滚动和放大"><div class="reading-images" ${isFigure?'data-reading-question':'data-reading-material'}="${E(q.id)}"><p class="reading-loading">正在定位本题资料…</p></div></div>${isFigure?'':`<details class="reading-transcript"><summary>查看材料文字（可复制）</summary><div class="reading-text">${textMarkup(q.reading_material??q.material)}</div></details>`}</section><section class="reading-answer"><div class="reading-answer-title">当前题目 <span>原题第 ${E(q.source_number||'')} 题</span></div>`;
};
S.questionReadingSource=q=>hasRegion(q)&&!figure(q)?`<details class="reading-question-source"><summary>查看当前题目原图</summary><div data-reading-question="${E(q.id)}"><p class="reading-loading">正在定位当前题目…</p></div></details>`:'';
S.questionReviewReading=q=>enabled(q)?`<details class="reading-review"><summary>查看本题资料与原题</summary>${S.questionMaterial(q)}${S.questionReadingSource(q)}</section></div></details>`:'';
function images(assets,kind){return assets.map((a,i)=>`<figure class="reading-figure"><a href="/api/visuals/${E(a.id)}" target="_blank" rel="noopener" aria-label="放大${kind}第${i+1}部分"><img src="/api/visuals/${E(a.id)}" width="${a.width}" height="${a.height}" alt="${kind} · 原文件第${a.page}页" loading="lazy"></a><figcaption>原文件第 ${a.pages?.join('、')||a.page} 页${a.pages?.length>1?' · 连续资料':''}${assets.length>1?` · ${i+1}/${assets.length}`:''}</figcaption></figure>`).join('')}
function fill(host,data,kind){
 if(!host.isConnected)return;
 const warning=data.warnings.filter(w=>w.kind===kind);
 host.innerHTML=images(data[kind],kind==='material'?'本题资料':'当前题目')+(warning.length?`<p class="reading-error">${warning.map(w=>E(`第${w.page}页：${w.message}`)).join('<br>')}</p>`:'')+(data[kind].length||warning.length?'':'<p class="reading-loading">本题没有额外的共用资料。</p>');
 const panel=host.closest('.reading-panel');
 if(panel){const key=panel.dataset.readingGroup;panel.style.setProperty('--reading-zoom',zooms.get(key)||'100%');const viewport=panel.querySelector('.reading-viewport');viewport.scrollTop=positions.get(key)?.top||0;viewport.scrollLeft=positions.get(key)?.left||0}
}
async function load(host,kind){
 const id=host.dataset[kind==='material'?'readingMaterial':'readingQuestion'];if(host.dataset.loaded)return;host.dataset.loaded='true';
 try{let data=cache.get(id);if(!data){if(!pending.has(id))pending.set(id,api('/api/question-reading/'+encodeURIComponent(id)).then(d=>{cache.set(id,d);return d}).finally(()=>pending.delete(id)));data=await pending.get(id)}fill(host,data,kind)}
 catch(e){if(host.isConnected){host.innerHTML=`<p class="reading-error">${E(e.message)}</p>${btn('重试定位','reading-retry','sm')}`;host.dataset.loaded='error'}}
}
function hydrate(){for(const host of document.querySelectorAll('[data-reading-material]:not([data-loaded])'))load(host,'material');for(const host of document.querySelectorAll('[data-reading-question]:not([data-loaded])'))load(host,'question')}
function zoom(el,change){const panel=el.closest('.reading-panel');if(!panel)return;const key=panel.dataset.readingGroup;const value=change===0?100:Math.max(100,Math.min(240,parseInt(zooms.get(key)||'100')+change));zooms.set(key,value+'%');panel.style.setProperty('--reading-zoom',value+'%')}
Object.assign(actions,{'reading-zoom-in':el=>zoom(el,25),'reading-zoom-out':el=>zoom(el,-25),'reading-fit':el=>zoom(el,0),'reading-retry':el=>{const host=el.parentElement;delete host.dataset.loaded;hydrate()}});
document.addEventListener('scroll',event=>{const el=event.target;if(el.classList?.contains('reading-viewport'))positions.set(el.closest('.reading-panel').dataset.readingGroup,{top:el.scrollTop,left:el.scrollLeft})},true);
new MutationObserver(hydrate).observe(document.body,{childList:true,subtree:true});hydrate();
})();
