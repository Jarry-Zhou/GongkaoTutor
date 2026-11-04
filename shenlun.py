"""Pinned Shenlun Master document adapter; no networking, scripts or model calls."""
import copy
import hashlib
import json
import math
import re
import uuid
import base64
from functools import lru_cache
from pathlib import Path
import learning_coach as coach

ROOT=Path(__file__).resolve().parent
VENDOR=ROOT/'vendor/shenlun-master'
ADAPTER='shenlun-master-1'
KINDS={'summary':'归纳概括','analysis':'综合分析','proposal':'对策启示','document':'公文写作','essay':'大作文','unknown':'待确认题型'}
LOSSES={'A1':'漏材料要点','A2':'材料定位不符','A3':'添加无依据内容','A4':'改写丢失关键含义',
        'B2':'分类层次混杂','B3':'归并过散或过度','C2':'总括与展开不对应','C3':'篇幅分配影响展开',
        'C4':'论述关系不清','C5':'双主题互动论证不足','D1':'遗漏题干要素','D2':'问题做法效果未对应',
        'D3':'对策缺少依据','E1':'材料与论述脱节','E2':'材料范围不符','F1':'表达影响准确性',
        'F2':'字数不符已知要求','F3':'未落实明确形式要求','G1':'未回应题干主题','G2':'标题与主张不符',
        'G3':'缺少明确中心论点','G4':'中心论点过于空泛','H1':'有例子缺论证','H3':'缺少机制解释','H4':'论据与论点不符'}


def is_shenlun(q):return q.get('module') in ('申论','综合应用能力') and q.get('type') in ('short','essay')
def nonspace(value):return len(re.sub(r'\s','',str(value or '')))
def lists(value,n=20):return value[:n] if isinstance(value,list) else []
def txt(value,n=1200):return str(value or '')[:n]


@lru_cache(maxsize=1)
def package():
    manifest=json.loads((VENDOR/'manifest.json').read_text('utf-8'))
    docs={}
    for f in manifest['files']:
        path=(VENDOR/f['path']).resolve()
        if not path.is_relative_to(VENDOR.resolve()):raise ValueError('规则包路径无效')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=f['sha256']:raise ValueError('规则文件与已固定版本不一致：'+f['path'])
        docs[f['path']]=raw.decode('utf-8')
    return manifest,docs


def status():
    try:
        manifest,_=package()
        return {'ready':True,'name':'Shenlun Master','repository':manifest['repository'],'commit':manifest['commit'],
                'adapter':ADAPTER,'license':manifest['license'],'files':len(manifest['files']),
                'note':'按题型使用上游方法节选，均为训练建议；不代表官方阅卷标准。'}
    except (OSError,ValueError,KeyError):
        return {'ready':False,'name':'Shenlun Master','note':'本地规则包校验未通过，请修复规则包后再分析。'}


def classify(q):
    stem=re.sub(r'\s+','',str(q.get('reading_stem',q.get('stem',''))))
    # Purpose-specific documents outrank the generic word "文章".
    if re.search(r'(?:拟写|写一[份篇则封段]|起草|撰写|草拟).{0,35}(?:倡议书|通知|报告|提纲|讲话稿|发言稿|简报|公开信|建议书|宣传稿|短评|导学|推介|编者按|工作总结|调研报告)',stem,re.S):return 'document'
    if re.search(r'大作文|议论文|写一篇文章|撰写一篇文章|自拟题目|自选角度|自选题目|写一篇.{0,16}(?:文章|议论)|以.{0,100}为(?:题|主题).{0,30}(?:文章|写作)',stem,re.S):return 'essay'
    if re.search(r'提出.{0,18}(?:对策|建议)|针对.{0,30}建议|对策|启示',stem):return 'proposal'
    if re.search(r'谈谈.{0,15}(?:理解|认识|看法)|如何理解|分析|评析|评价|为什么|解释',stem):return 'analysis'
    if re.search(r'概括|归纳|梳理|提炼|总结.{0,10}(?:做法|经验|问题|特点)',stem):return 'summary'
    return 'unknown'


def context(app,q,saved=None):
    if saved is None:saved=app.store.get('shenlun_contexts',q['id'],{})
    stem=str(q.get('reading_stem',q.get('stem','')))
    kind=saved.get('kind') if saved.get('kind') in KINDS else classify(q)
    scores={float(x) for x in re.findall(r'[（(]\s*(\d+(?:\.\d+)?)\s*分\s*[）)]',stem)}
    if not scores:scores={float(x) for x in re.findall(r'(?:本题|满分|分值)[为：:\s]*(\d+(?:\.\d+)?)\s*分',stem)}
    score=next(iter(scores)) if len(scores)==1 else None
    minimum=None;maximum=None
    match=re.search(r'(\d+)\s*[-—－~～至到]\s*(\d+)\s*字',stem)
    if match:minimum,maximum=map(int,match.groups())
    upper=re.search(r'(?:不超过|不多于|最多|以内)\s*(\d+)\s*字|(\d+)\s*字(?:以内|以下)',stem)
    if upper:maximum=int(upper.group(1) or upper.group(2))
    lower=re.search(r'(?:不少于|至少)\s*(\d+)\s*字',stem)
    if lower:minimum=int(lower.group(1))
    for key in ('max_score','word_min','word_max'):
        if key in saved:
            if key=='max_score':score=saved[key]
            elif key=='word_min':minimum=saved[key]
            else:maximum=saved[key]
    if score is not None and not 0<score<=100:score=None
    if minimum and maximum and minimum>maximum:minimum=maximum=None
    return {'kind':kind,'kind_label':KINDS[kind],'max_score':score,'word_min':minimum,'word_max':maximum,
            'score_source':'用户确认' if 'max_score' in saved and score else '题干提取' if score else '未确认',
            'question_id':q['id'],'adapter':ADAPTER,'updated_at':saved.get('updated_at')}


def save_context(app,qid,body):
    q=app.require('questions',qid)
    if not is_shenlun(q):raise app.uploads.error('该题不是申论或综合应用能力主观题。')
    old=app.store.get('shenlun_contexts',qid,{})
    result={**old,'id':qid,'updated_at':coach.stamp()}
    if 'kind' in body:
        if not isinstance(body['kind'],str) or (body['kind'] not in KINDS and body['kind']!='auto'):raise app.uploads.error('题型无效。')
        if body['kind']=='auto':result.pop('kind',None)
        else:result['kind']=body['kind']
    for key in ('max_score','word_min','word_max'):
        if key not in body:continue
        value=body[key]
        if value in ('',None):result.pop(key,None);continue
        try:
            if isinstance(value,bool):raise ValueError()
            number=float(value)
            if not math.isfinite(number) or not 0<number<=(100 if key=='max_score' else 10000):raise ValueError()
            if key!='max_score' and number!=int(number):raise ValueError()
        except (TypeError,ValueError):raise app.uploads.error('请输入有效的题目分值或整数字数；不清楚可留空。')
        result[key]=number if key=='max_score' else int(number)
    auto=context(app,q,{})
    minimum=result.get('word_min',auto['word_min']);maximum=result.get('word_max',auto['word_max'])
    if minimum and maximum and minimum>maximum:
        raise app.uploads.error('字数下限不能大于上限。')
    result['history']=lists(old.get('history'),100)+[{'at':coach.stamp(),'previous':{k:v for k,v in old.items() if k!='history'}}]
    app.store.put('shenlun_contexts',result)
    return context(app,q)


def feedback_for(app,qid):
    return [{k:r[k] for k in ('finding_id','dismissed','reason','created_at')} for r in app.store.iter('shenlun_feedback') if r['question_id']==qid][:6]


def draft_signature(app,attempt):
    rows=[]
    for a in lists(attempt['response'].get('attachments'),3):
        if not isinstance(a,dict):continue
        aid=str(a.get('id',''));mime=a.get('mime')
        if not re.fullmatch(r'img_[a-f0-9]{16}',aid) or mime not in ('image/png','image/jpeg','image/webp'):
            raise app.uploads.error('草稿图片记录无效，请重新上传后作答。',409)
        path=app.store.folder/'evidence'/aid
        if not path.is_file():raise app.uploads.error('草稿原图在本机不可用，请重新上传；本次未调用模型。',409)
        rows.append([aid,mime,hashlib.sha256(path.read_bytes()).hexdigest()])
    return coach.digest(rows)


def confirmed_answer(app,attempt):
    record=app.store.get('shenlun_transcriptions',attempt['id'])
    if record and record['image_signature']==draft_signature(app,attempt):return record
    return None


def draft_count(app,attempt):
    if not is_shenlun(attempt['question']) or not attempt['response'].get('attachments'):return 0
    return 0 if confirmed_answer(app,attempt) else len(lists(attempt['response']['attachments'],3))


def draft_images(app,attempt):
    if not draft_count(app,attempt):return []
    draft_signature(app,attempt)
    return ['data:'+a['mime']+';base64,'+base64.b64encode((app.store.folder/'evidence'/a['id']).read_bytes()).decode() for a in attempt['response']['attachments'][:3]]


def answer_text(app,attempt):
    confirmed=confirmed_answer(app,attempt) if attempt['response'].get('attachments') else None
    return confirmed['text'] if confirmed else str(attempt['response'].get('value',''))


def confirm_transcription(app,aid,body):
    attempt=app.require('attempts',aid)
    if not is_shenlun(attempt['question']) or not attempt['response'].get('attachments'):raise app.uploads.error('该记录没有申论草稿图片。')
    value=txt(body.get('text'),12001).strip()
    if body.get('confirmed') is not True or not value or len(value)>12000:raise app.uploads.error('请核对并确认转写文字，再保存。')
    old=app.store.get('shenlun_transcriptions',aid,{})
    signature=draft_signature(app,attempt)
    if old.get('text')==value and old.get('image_signature')==signature:return {'saved':True,'characters':nonspace(value)}
    record={'id':aid,'text':value,'image_signature':signature,'created_at':coach.stamp(),
            'history':lists(old.get('history'),50)+([{'text':old['text'],'at':old['created_at']}] if old else [])}
    app.store.put('shenlun_transcriptions',record)
    return {'saved':True,'characters':nonspace(value)}


def evidence_version(app,q):
    if not is_shenlun(q):return None
    ctx=context(app,q);ctx.pop('updated_at',None)
    return coach.digest([ADAPTER,ctx,feedback_for(app,q['id'])])


def evidence(app,attempt,q):
    value=answer_text(app,attempt);ctx=context(app,q)
    count=nonspace(value)
    return {**ctx,'answer_characters':count,'count_method':'非空字符（含标点），仅作字数参考',
            'over_limit':ctx['word_max'] is not None and count>ctx['word_max'],
            'below_limit':ctx['word_min'] is not None and count<ctx['word_min'],
            'requirement_text':q.get('reading_stem',q['stem']),
            'answer_paragraphs':[{'id':'a'+str(i+1),'text':s} for i,s in enumerate(value.splitlines()) if s.strip()],
            'user_corrections':feedback_for(app,q['id']),
            'transcription_required':bool(attempt['response'].get('attachments') and not confirmed_answer(app,attempt) and (not value.strip() or re.fullmatch(r'(?:见|详见)(?:附件|草稿|图|图片)[。！!\s]*',value)))}


def excerpt(docs,path,title,limit=1900):
    source=docs[path];lines=source.splitlines();start=None;level=0;part=[]
    for line in lines:
        heading=re.match(r'^(#{1,6})\s+(.+)',line)
        if start is None:
            if heading and title in heading[2]:start=True;level=len(heading[1]);part.append(line)
        else:
            if heading and len(heading[1])<=level:break
            part.append(line)
    return {'source':path,'section':title,'excerpt':'\n'.join(part)[:limit]}


def method_packet(kinds):
    manifest,docs=package();sections=[]
    shared='skills/shenlun-xiaoti/references/'
    if any(k!='essay' for k in kinds):
        sections.append(excerpt(docs,shared+'bai-lu-methodology.md','一、题干四要素审题法',1700))
        sections.append(excerpt(docs,shared+'bai-lu-methodology.md','8.1 ✅ 有据分歧',1700))
        sections.append(excerpt(docs,shared+'xiaoma-methodology.md','四项基本原则',700))
        heading={'summary':'一、归纳概括题','analysis':'三、综合分析题','proposal':'二、对策启示题','document':'5.1 文种格式要素对照表'}
        for kind in sorted(kinds):
            if kind in heading:sections.append(excerpt(docs,shared+'xiaoma-methodology.md',heading[kind],1000))
    if 'essay' in kinds:
        path='skills/shenlun-dawenti/references/yuan-dong-methodology.md'
        sections.extend([excerpt(docs,path,'零、第一原则',1000),excerpt(docs,path,'6.5',2200),excerpt(docs,path,'7.5',1400)])
    return {'repository':manifest['repository'],'commit':manifest['commit'],'adapter':ADAPTER,
            'notice':'以下为上游项目整理的方法建议节选，非官方标准；适配约束优先于节选中的绝对化表述。',
            'sections':[s for s in sections if s['excerpt']],'allowed_loss_codes':LOSSES}


def citations(raw,quotes):
    out=[]
    for row in lists(raw,8):
        if not isinstance(row,dict):continue
        pid=row.get('paragraph_id');quote=row.get('quote')
        if isinstance(pid,str) and isinstance(quote,str) and quote and len(quote)<=1000 and quote in quotes.get(pid,''):
            out.append({'paragraph_id':pid,'quote':quote})
    return out


def validate_reviews(app,answer,evidence_rows,run_id):
    source={e['attempt_id']:e for e in evidence_rows if e.get('shenlun')}
    out=[];seen=set()
    for raw in lists(answer.get('shenlun_reviews'),2):
        if not isinstance(raw,dict) or not isinstance(raw.get('attempt_id'),str):continue
        row=source.get(raw['attempt_id'])
        if not row or row['attempt_id'] in seen:continue
        ctx=row['shenlun'];bundle=row.get('material_bundle',{});complete=bundle.get('coverage')=='complete'
        if ctx.get('transcription_required'):
            transcription=txt(raw.get('transcription'),12000).strip()
            if not transcription:raise app.uploads.error('模型未返回手写转写草稿，本次未记为已分析。',502)
            q=app.require('questions',row['question']['id'])
            out.append({'id':'slr_'+coach.digest([run_id,row['attempt_id']])[:20],'analysis_id':run_id,'attempt_id':row['attempt_id'],
                'question_id':q['id'],'kind':ctx['kind'],'kind_label':ctx['kind_label'],'created_at':coach.stamp(),
                'source_version':coach.version(app,q),'context_version':evidence_version(app,q),'adapter':ADAPTER,
                'title':q['stem'][:220],'source':q.get('source',''),'context':ctx,'complete':False,'points':[],
                'score':{'available':False,'reason':'手写转写尚待你确认，不据此判错或估分。'},'findings':[],'reference_versions':[],
                'comparison':'','rewrites':[],'theme_type':'待确认','structure':[],'advice':[],
                'transcription':transcription,'transcription_pending':True})
            seen.add(row['attempt_id']);continue
        user=str(row['user_answer']);quotes={p['id']:p['text'] for p in bundle.get('paragraphs',[])}
        quotes['question']=ctx['requirement_text']
        points=[];point_ids=set();score_valid=True
        for p in lists(raw.get('points'),14):
            if not isinstance(p,dict):continue
            cites=citations(p.get('citations'),quotes);label=txt(p.get('label'),250).strip();pid=p.get('id')
            quote=txt(p.get('user_quote'),1200)
            if not cites or not label or not isinstance(pid,str) or not pid or len(pid)>40 or pid in point_ids:continue
            verdict=p.get('verdict') if p.get('verdict') in ('covered','partial','missing','uncertain') else 'uncertain'
            if verdict in ('covered','partial') and (not quote or quote not in user):verdict='uncertain';quote=''
            if quote and quote not in user:quote=''
            if not complete:verdict='uncertain'
            values={}
            try:
                if not ctx.get('max_score') or ctx['kind'] in ('essay','unknown'):raise ValueError()
                if isinstance(p.get('max_score'),bool) or isinstance(p.get('awarded'),bool):raise ValueError()
                maximum=float(p.get('max_score'));awarded=float(p.get('awarded'))
                if not complete or not (math.isfinite(maximum) and math.isfinite(awarded) and 0<maximum<=100 and 0<=awarded<=maximum):raise ValueError()
                if verdict=='uncertain' or (verdict=='missing' and awarded!=0):raise ValueError()
                values={'max_score':maximum,'awarded':awarded}
            except (ValueError,TypeError):score_valid=False
            points.append({'id':pid,'label':label,'citations':cites,'user_quote':quote,'verdict':verdict,
                           'explanation':txt(p.get('explanation'),700),'improve':txt(p.get('improve'),700),**values});point_ids.add(pid)
        if complete and not points:raise app.uploads.error('申论报告未提供可核验的材料依据，本次未记为已分析。',502)
        max_score=ctx.get('max_score');allocated=sum(p.get('max_score',0) for p in points)
        score={'available':False,'reason':'满分、材料或有效配点不完整，仅提供定性建议。'}
        if ctx['kind']=='essay':score['reason']='大作文提供论证与表达建议，本版本不将其折算成未经校准的数字成绩。'
        elif ctx['kind']=='unknown':score['reason']='题型待确认，暂不采用数字估分。'
        elif complete and max_score and points and score_valid and math.isclose(allocated,max_score,abs_tol=.01):
            value=round(sum(p['awarded'] for p in points),2)
            score={'available':True,'value':value,'max_score':max_score,'basis':'模型建议配点；程序核算分项和',
                   'note':'模拟估分，非官方阅卷分数；不写入原始成绩或模考预测。'}
        elif score_valid and max_score and not math.isclose(allocated,max_score,abs_tol=.01):score['reason']='有效配点之和与题目满分不一致，不采用数字估分。'
        theme=txt(raw.get('theme_type'),80)
        findings=[];codes=set();corrections={}
        for correction in app.store.iter('shenlun_feedback'):
            if correction.get('attempt_id')==row['attempt_id'] and correction.get('source_version')==coach.version(app,app.require('questions',row['question']['id'])):
                corrections.setdefault(correction.get('code'),correction)
        for f in lists(raw.get('findings'),8):
            if not isinstance(f,dict) or not isinstance(f.get('code'),str):continue
            code=f['code'].split('-')[0]
            if code not in LOSSES or code in codes:continue
            if corrections.get(code,{}).get('dismissed'):continue
            if code=='E2' and 'A2' in codes:continue
            quote=txt(f.get('user_quote'),1200)
            if quote and quote not in user:continue
            related=[i for i in lists(f.get('point_ids'),8) if isinstance(i,str) and i in point_ids]
            if not complete or not related:continue
            if code not in ('A1','D1','F2','G3') and not quote:continue
            if code=='F2' and not (ctx['over_limit'] or ctx['below_limit']):continue
            if code=='G1' and ctx['kind']!='essay':continue
            if code=='C5' and theme not in ('AB','ABC'):continue
            action=txt(f.get('action'),800).strip()
            if not action:continue
            cause=txt(f.get('cause'),100)
            if cause not in ('知识盲区','技巧不熟','粗心大意','时间不够'):cause='暂不确定'
            # A single written answer cannot establish why a learner struggled.
            process='\n'.join([str(row.get('reason',''))]+list(row.get('steps',{}).values())+row.get('user_followups',[]))
            cause_quote=txt(f.get('cause_quote'),400)
            if not cause_quote or cause_quote not in process:cause='暂不确定';cause_quote=''
            findings.append({'id':'slf_'+coach.digest([run_id,row['attempt_id'],code])[:20],'code':code,'label':LOSSES[code],
                             'question_id':row['question']['id'],'attempt_id':row['attempt_id'],'user_quote':quote,'point_ids':related,
                             'cause':cause,'cause_quote':cause_quote,'action':action,'description':txt(f.get('description'),800)})
            codes.add(code)
        if 'A2' in codes:findings=[f for f in findings if f['code']!='E2']
        refs=[]
        if complete and ctx['kind'] not in ('essay','unknown'):
            for ref in lists(raw.get('reference_versions'),2):
                if not isinstance(ref,dict):continue
                body=txt(ref.get('text'),2400).strip();cites=citations(ref.get('citations'),quotes)
                if not body or not cites or any(r['text']==body for r in refs):continue
                refs.append({'style':'紧凑归并（参考小马哥）' if not refs else '按题干要素组织（参考白鹭）',
                             'text':body,'characters':nonspace(body),'citations':cites,
                             'over_limit':bool(ctx.get('word_max') and nonspace(body)>ctx['word_max'])})
        rewrites=[]
        for r in lists(raw.get('rewrites'),3):
            if not isinstance(r,dict):continue
            original=txt(r.get('original'),800);replacement=txt(r.get('replacement'),1000)
            if original and original in user and replacement and replacement!=original and citations(r.get('citations'),quotes):
                rewrites.append({'original':original,'replacement':replacement,'why':txt(r.get('why'),600),'citations':citations(r.get('citations'),quotes)})
        structure=[]
        if ctx['kind']=='essay':
            for s in lists(raw.get('structure'),8):
                if not isinstance(s,dict):continue
                quote=txt(s.get('user_quote'),1200)
                if quote and quote in user:structure.append({'user_quote':quote,'claim':txt(s.get('claim'),500),'mechanism':txt(s.get('mechanism'),700),'fix':txt(s.get('fix'),800)})
        q=app.require('questions',row['question']['id'])
        out.append({'id':'slr_'+coach.digest([run_id,row['attempt_id']])[:20],'analysis_id':run_id,'attempt_id':row['attempt_id'],
                    'question_id':q['id'],'kind':ctx['kind'],'kind_label':ctx['kind_label'],'created_at':coach.stamp(),
                    'source_version':coach.version(app,q),'context_version':evidence_version(app,q),'adapter':ADAPTER,
                    'title':q['stem'][:220],'source':q.get('source',''),'context':ctx,'complete':complete,'points':points,
                    'score':score,'findings':findings,'reference_versions':refs,'comparison':txt(raw.get('comparison'),1600),
                    'rewrites':rewrites,'theme_type':theme,'structure':structure,'advice':[txt(v,700) for v in lists(raw.get('advice'),3)]})
        seen.add(row['attempt_id'])
    if source.keys()!=seen:raise app.uploads.error('模型未完整返回本批申论报告，本次未记为已分析，可重新确认后重试。',502)
    return out


def review_iter(app):
    for run in app.store.iter('learning_analyses'):
        for review in run.get('result',{}).get('shenlun_reviews',[]):yield review


def overview(app):
    questions={q['id']:q for q in app.store.all('questions') if is_shenlun(q)}
    counts={k:0 for k in KINDS};rows=[]
    for q in questions.values():
        ctx=context(app,q)
        if q['status']=='ready':counts[ctx['kind']]+=1
        rows.append({'id':q['id'],'title':q['stem'][:180],'status':q['status'],'context':ctx})
    feedback={}
    for f in app.store.iter('shenlun_feedback'):feedback.setdefault(f['finding_id'],f)
    latest={};history=[]
    for r in review_iter(app):
        history.append({'id':r['id'],'analysis_id':r['analysis_id'],'question_id':r['question_id'],'created_at':r['created_at']})
        if r['question_id'] not in latest:latest[r['question_id']]=copy.deepcopy(r)
    losses={}
    for r in latest.values():
        q=questions.get(r['question_id'])
        r['stale']=not q or coach.version(app,q)!=r['source_version'] or evidence_version(app,q)!=r['context_version']
        # A dismissal changes incremental evidence, but does not invalidate its report's material.
        if q and coach.version(app,q)==r['source_version']:
            base=context(app,q);base.pop('updated_at',None);recorded={k:v for k,v in r['context'].items() if k in base};recorded.pop('updated_at',None)
            r['stale']=any(recorded.get(k)!=base[k] for k in base)
        for f in r['findings']:
            f['feedback']=feedback.get(f['id']);f['dismissed']=bool((f['feedback'] or {}).get('dismissed'))
            if r['stale'] or f['dismissed']:continue
            loss=losses.setdefault(f['code'],{'code':f['code'],'label':f['label'],'occurrences':[]})
            loss['occurrences'].append({'finding_id':f['id'],'question_id':r['question_id'],'title':r['title'],'source':r['source'],
                                        'created_at':r['created_at'],'action':f['action'],'cause':f['cause']})
        if any(f['dismissed'] for f in r['findings']):
            r['score']={'available':False,'reason':'当前报告含已撤销判断，模拟分暂不采用；原结果保留在历史分析中。'}
        if r['stale']:
            r['score']={'available':False,'reason':'材料或题目条件已变更，原模拟分仅保留在历史分析中，待核对后重评。'}
        if r.get('transcription_pending'):
            attempt=app.require('attempts',r['attempt_id']);confirmed=confirmed_answer(app,attempt)
            r['transcription_confirmed']=bool(confirmed)
            r['confirmed_transcription_text']=confirmed['text'] if confirmed else ''
            r['draft_urls']=['/api/evidence/'+a['id'] for a in lists(attempt['response'].get('attachments'),3) if isinstance(a,dict) and re.fullmatch(r'img_[a-f0-9]{16}',str(a.get('id','')))]
    for loss in losses.values():
        loss['count']=len(loss['occurrences']);loss['state']='初现' if loss['count']==1 else '复发' if loss['count']==2 else '多题反复'
    import shenlun_dimensions
    return {'skill':status(),'inventory':counts,'questions':rows,'reviews':list(latest.values())[:30],
            'dimensions':shenlun_dimensions.overview(app),
            'losses':sorted(losses.values(),key=lambda l:-l['count']),'history':history[:50],
            'note':'失分类型按不同题目计次，同题重评不累加。模型原因属于建议，证据不足时保留暂不确定。'}


def finding_feedback(app,fid,body):
    finding=next((f for r in review_iter(app) for f in r['findings'] if f['id']==fid),None)
    if not finding:raise app.uploads.error('失分判断不存在。',404)
    if not isinstance(body.get('dismissed'),bool):raise app.uploads.error('请选择撤销或恢复。')
    reason=txt(body.get('reason'),1500).strip()
    if not reason:raise app.uploads.error('请简要说明原因，便于下次分析修正。')
    record={'id':'slfb_'+uuid.uuid4().hex[:20],'finding_id':fid,'question_id':finding['question_id'],
            'attempt_id':finding['attempt_id'],'code':finding['code'],
            'source_version':coach.version(app,app.require('questions',finding['question_id'])),
            'dismissed':body['dismissed'],'reason':reason,'created_at':coach.stamp()}
    app.store.put('shenlun_feedback',record)
    return record


PROMPT='''
answer_image_indexes是用户草稿，不是题干或标准答案。若本条shenlun.transcription_required=true，只在对应shenlun_reviews项返回attempt_id和transcription逐字转写草稿（不清楚标[字迹不清]）；不返回采点、分数、错因、能力或训练，先等待用户核对确认。用户已提供文字答案时以文字为准，草稿只能辅助理解。
申论专项报告与其他JSON字段合计控制在4500字左右。每题优先核对4到6个关键要点、2到3项实质问题，每段讲解简短。小题两版各自不超过题目字数要求，未给上限时各不超过250字；不输出大作文整篇范文。
本批含申论主观题，按shenlun_method中的相关题型方法节选完成有材料依据的个性化评改。题型、字数和满分以各条shenlun字段为准。unknown时不得擅自判大作文或给数值分。
适配约束优先：不要自动联网找答案；没有官方细则就明确为模型建议配点。不得将方法样本中的“已证实”当作官方规则。不得因不满足固定总括句、统一句式、领域分类、85%-95%字数、必须递进或模板公式而扣分。允许含义准确的同义表达，不为用原词而放弃概括；不生硬堆政策套话、名言。材料不全不认定遗漏，不生成完整参考作答或数字估分。无分值不默认40分。大作文只给论证与表达反馈，不给未经校准数字分。缺用户思路不能臆测知识盲区、粗心或耗时原因。
新增JSON字段shenlun_reviews数组：对new_evidence中每个带shenlun的attempt_id恰好给1项。短训练仍在task_reviews评价。每次最多2道申论报告，优先具体建议，控制总输出。
每项attempt_id；points数组(最多10项)，每项id(p1等)、label、citations数组{paragraph_id,quote}(逐字引用material_bundle中的段落或question题干)、verdict(covered/partial/missing/uncertain)、user_quote(确切作答原文，不能改写冒充原话；missing可空)、explanation、improve；小题且满分已知可提出max_score和awarded，所有子项max_score之和必须等于题目满分，awarded在0到max_score之间。程序只核算配点和，不接受模型报的总分；未知、部分材料、大作文不配数字分。采分清单如由你从材料拟定，必须说明是建议要点，不能称官方标准。
findings数组最多4项，每项code(从allowed_loss_codes选择)、point_ids(关联本项points的id)、user_quote、description(本题具体表现)、action(怎样练到哪个标准)、cause(知识盲区/技巧不熟/粗心大意/时间不够/暂不确定)、cause_quote(支持归因的用户思路原文；没有就暂不确定)。只写与材料和任务有关的实质问题，不用文风偏好制造错误。F2仅在本地over_limit/below_limit为真时用；A2与E2同义不双计；C5须确认为AB/ABC双主题，且实际缺互动机制而非仅未套模板。
reference_versions：仅完整材料小题给2项{ text,citations }，第一版按“上位概括+事实做法”紧凑归并（参考小马哥），第二版按题干要素分栏或配对（参考白鹭）；只使用本题已提供事实，必须给材料引文。两版不得只换措辞。若本题两版适合相同结构则如实在comparison说明，宁可只留一版。comparison比较结构、要点覆盖、字数风险及结合本次作答应该学哪一步，不能泛泛介绍名师。
rewrites最多2项：original(作答原句)、replacement、why、citations。说明原句漏了哪层“主体—做法—机制—效果”，给最小必要修改，不凭空补成效。
大作文额外theme_type(单主题/AB/ABC/多主题/待确认)，structure最多5项{user_quote,claim,mechanism,fix}；逐段判断论据是否证明主张、是否说明机制、是否回应题干，先尊重结构自洽，再给备用组织办法，不强制五段三分。
advice数组最多3条，每条直接对应这次作答的证据。旧报告与用户撤销意见用于修正，不重复分析已覆盖的无变更作答。能力与短训练仍按原JSON接口返回，stage优先business/points/expression，关联实际knowledge_points，把最关键的发现转成可作答的短步骤。
'''
