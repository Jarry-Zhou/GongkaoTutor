"""Evidence-bound cross-question Shenlun dimensions inside the shared AI ledger."""
import copy
import re
from datetime import datetime,timezone
import learning_coach as coach
import shenlun

VERSION=1
DIMENSIONS={
    'structure':{'name':'层次划分','stage':'points','description':'区分总分、并列、因果与层级，按任务归并要点，而非机械套段。'},
    'thesis':{'name':'主旨凝练','stage':'expression','description':'提炼材料核心关系，形成准确、有对象、有内涵的概括或中心论点。'},
    'business':{'name':'业务熟悉度','stage':'business','description':'理解主体职责、业务概念、办理流程和运行机制；与材料误读、表达遗漏分开验证。'},
    'evidence':{'name':'材料要点提取','stage':'points','description':'定位题干范围，提取关键事实与限制条件，区分背景和可作答要点。'},
    'reasoning':{'name':'关系与论证','stage':'relation','description':'说清问题、原因、举措和效果的关系，用论据支持主张并解释机制。'},
    'expression':{'name':'表达规范','stage':'expression','description':'表达准确、简明、符合题目文体，减少空泛和冗余，不以文风偏好判错。'},
    'efficiency':{'name':'作答效率','stage':'expression','description':'用分步记录定位阅读、归并、提炼或成文的用时，缺少计时不猜测慢在哪。'}
}


def text(value,limit=900):return str(value or '')[:limit]
def rows(value,n=20):return value[:n] if isinstance(value,list) else []


def source_signature(app,kind,sid):
    if kind=='attempt':
        import learning_analysis
        a=app.store.get('attempts',sid)
        if not a:return None
        return learning_analysis.evidence_fingerprint(app,a,app.store.get('diagnoses',sid,{}),True)
    task=app.store.get('coach_tasks',sid)
    return coach.task_fingerprint(task) if task else None


def prepare(app,evidence,tasks,signatures):
    """Capture versions BEFORE the API request; concurrent edits must remain pending."""
    contexts={}
    for kind,entries in (('attempt',evidence),('training',tasks)):
        for entry in entries:
            if kind=='attempt':
                if not entry.get('shenlun') or entry['shenlun'].get('transcription_required'):continue
                q=entry['question'];sid=entry['attempt_id'];answer=str(entry.get('user_answer',''))
                process='\n'.join([str(entry.get('reason',''))]+list(entry.get('steps',{}).values())+entry.get('user_followups',[]))
                timing=[]
            else:
                q=entry.get('source_question',{});sid=entry.get('id');answer='\n'.join(a['text'] for a in entry.get('answers',[]))
                process=answer;timing=[{'stage_index':i,'seconds':a.get('duration_seconds',0),'prompt':entry['prompts'][i]}
                    for i,a in enumerate(entry.get('answers',[])) if i<len(entry.get('prompts',[]))]
                if not shenlun.is_shenlun(q):continue
            if not answer.strip():continue
            current=app.store.get('questions',q.get('id'))
            if not current:continue
            bundle=entry.get('material_bundle',{});quotes={p['id']:p['text'] for p in bundle.get('paragraphs',[])}
            quotes['question']=entry.get('shenlun',{}).get('requirement_text',q.get('stem',''))
            ref=kind+':'+sid
            contexts[ref]={'source_type':kind,'source_id':sid,'source_ref':ref,'question_id':q['id'],
                'module':q['module'],'point':q.get('knowledge_points',[''])[0] if q.get('knowledge_points') else '',
                'answer':answer,'process':process,'quotes':quotes,'complete':bundle.get('coverage')=='complete',
                'timing':timing,'hint_used':entry.get('hint_used',False),'title':current['stem'][:220],
                'source_version':coach.version(app,current),'context_version':shenlun.evidence_version(app,current),
                'signature':signatures.get((kind,sid)) or source_signature(app,kind,sid)}
    return contexts


def validate_observations(app,answer,contexts,run_id):
    raw=answer.get('shenlun_dimension_observations')
    if not isinstance(raw,list):raise app.uploads.error('模型未返回申论维度证据，本次未记为已分析，旧结论保留。',502)
    observations={}
    for item in raw[:18]:
        if not isinstance(item,dict) or not isinstance(item.get('dimension'),str) or item['dimension'] not in DIMENSIONS:continue
        ref=item.get('source_ref');ctx=contexts.get(ref) if isinstance(ref,str) else None
        if not ctx:continue
        dim=item['dimension'];judgment=item.get('judgment')
        if judgment not in ('weak','adequate','uncertain'):continue
        quote=text(item.get('user_quote'),1200);process_quote=text(item.get('process_quote'),800)
        if quote and quote not in ctx['answer']+'\n'+ctx['process']:continue
        if process_quote and process_quote not in ctx['process']:process_quote=''
        cites=shenlun.citations(item.get('citations'),ctx['quotes'])
        claim=text(item.get('observation'),1200).strip()
        if not claim or (not quote and not cites):continue
        if not quote and (dim!='evidence' or not ctx['complete']):judgment='uncertain'
        if not cites and dim not in ('structure','expression','efficiency'):judgment='uncertain'
        if not ctx['complete'] and dim not in ('structure','expression','efficiency'):judgment='uncertain'
        if dim=='business' and (not process_quote or not cites):judgment='uncertain'
        timing=[]
        if dim=='efficiency':
            timing=[t for t in ctx['timing'] if isinstance(t['seconds'],(int,float)) and 0<t['seconds']<=3600]
            if len(timing)<2 or not process_quote:
                judgment='uncertain'
                if not timing:claim='尚无可核对的分步计时，不能从整题总用时定位具体耗时步骤。'
        observation={'id':'sdob_'+coach.digest([ref,dim,ctx['signature'],claim,judgment,quote])[:20],
            'analysis_id':run_id,'dimension':dim,'source_type':ctx['source_type'],'source_id':ctx['source_id'],'source_ref':ref,
            'question_id':ctx['question_id'],'module':ctx['module'],'point':ctx['point'],'title':ctx['title'],
            'judgment':judgment,'observation':claim,'user_quote':quote,'process_quote':process_quote,'citations':cites,
            'action':text(item.get('action'),1000),'verify':text(item.get('verify'),900),
            'verification_prompts':[text(v,600) for v in rows(item.get('verification_prompts'),3) if isinstance(v,str) and v.strip()],
            'reference':text(item.get('reference'),1200),'timing':timing,'hint_used':ctx['hint_used'],
            'material_complete':ctx['complete'],
            'source_version':ctx['source_version'],'context_version':ctx['context_version'],
            'source_signature':ctx['signature'],'created_at':coach.stamp()}
        observations[(ref,dim)]=observation
    if raw and not observations:raise app.uploads.error('申论维度引用无法核对，本次未记为已分析。',502)
    return list(observations.values())


def observations_and_conclusions(app,extra=None):
    observations=[];conclusions={}
    runs=list(extra or [])+list(app.store.iter('learning_analyses'))
    for run in runs:
        result=run.get('result',{})
        observations+=result.get('shenlun_dimension_observations',[])
        for conclusion in result.get('shenlun_dimension_conclusions',[]):conclusions.setdefault(conclusion['dimension'],copy.deepcopy(conclusion))
    return observations,conclusions


def active_observations(app,observations):
    questions={q['id']:q for q in app.store.all('questions')};signatures={};current=[];stale=[];seen=set()
    for ob in observations:
        # Latest judgment for the same written question supersedes earlier regrades.
        key=(ob['question_id'],ob['dimension'],ob['source_type'])
        if ob['source_type']=='training':key+=(ob['source_id'],)
        if key in seen:continue
        seen.add(key);q=questions.get(ob['question_id']);valid=False
        if q and shenlun.is_shenlun(q):
            source=(ob['source_type'],ob['source_id'])
            if source not in signatures:signatures[source]=source_signature(app,*source)
            valid=(coach.version(app,q)==ob['source_version'] and shenlun.evidence_version(app,q)==ob['context_version']
                   and signatures[source]==ob['source_signature'])
        (current if valid else stale).append(ob)
    return current,stale


def validate_conclusions(app,answer,observations,previous):
    raw=answer.get('shenlun_dimension_conclusions')
    if not isinstance(raw,list):raise app.uploads.error('模型未返回申论跨题维度结论，本次未记为已分析。',502)
    old_ob,old_con=observations_and_conclusions(app)
    current,_=active_observations(app,observations+old_ob)
    changed={o['dimension'] for o in observations}
    conclusions=dict(old_con)
    for item in raw[:7]:
        if not isinstance(item,dict) or not isinstance(item.get('dimension'),str) or item['dimension'] not in DIMENSIONS:continue
        dim=item['dimension']
        if dim not in changed:continue
        refs={v for v in rows(item.get('evidence_refs'),12) if isinstance(v,str)}
        support=[o for o in current if o['dimension']==dim and o['source_ref'] in refs]
        summary=text(item.get('summary'),1200).strip()
        if not support or not summary:continue
        conclusions[dim]={'dimension':dim,'summary':summary,'change':text(item.get('change'),900),
            'next_step':text(item.get('next_step'),900),'observation_ids':[o['id'] for o in support],
            'updated_at':coach.stamp()}
    return list(conclusions.values())


def overview(app,extra=None):
    all_ob,conclusions=observations_and_conclusions(app,extra)
    current,stale=active_observations(app,all_ob);active_ids={o['id'] for o in current};cards=[]
    for dim,meta in DIMENSIONS.items():
        obs=[o for o in current if o['dimension']==dim]
        written=[o for o in obs if o['source_type']=='attempt'];training=[o for o in obs if o['source_type']=='training']
        weak={o['question_id'] for o in written if o['judgment']=='weak'}
        adequate={o['question_id'] for o in written if o['judgment']=='adequate'}
        unresolved=[o for o in stale if o['dimension']==dim]
        history_weak=any(o['dimension']==dim and o['judgment']=='weak' for o in all_ob)
        state='证据不足'
        if obs:state='待验证'
        if weak:state='单题信号' if len(weak)==1 else '跨题反复'
        elif adequate:state='出现改善证据' if history_weak else '本批表现较好'
        if adequate and history_weak and written and written[0]['judgment']=='adequate':state='出现改善证据'
        if not obs and unresolved:state='待重新校验'
        conclusion=conclusions.get(dim);valid_conclusion=bool(conclusion and conclusion.get('observation_ids') and all(i in active_ids for i in conclusion['observation_ids']))
        cards.append({'dimension':dim,**meta,'state':state,'written_questions':len({o['question_id'] for o in written}),
            'weak_questions':len(weak),'adequate_questions':len(adequate),'training_records':len(training),
            'stale_records':len(unresolved),'observations':obs[:12],
            'conclusion':conclusion if valid_conclusion else None,'conclusion_pending':bool(conclusion and not valid_conclusion)})
    tasks=app.store.all('coach_tasks');available=[]
    for t in tasks:
        if t.get('dimension') not in DIMENSIONS:continue
        q=app.store.get('questions',t['question_id'])
        if q and coach.version(app,q)==t['source_version'] and (not t.get('dimension_context_version') or t['dimension_context_version']==shenlun.evidence_version(app,q)):
            available.append({'id':t['id'],'dimension':t['dimension'],'title':t['title'],'status':t['status']})
    return {'version':VERSION,'dimensions':cards,'tasks':available,
        'questions':len({o['question_id'] for o in current if o['source_type']=='attempt'}),
        'note':'维度判断来自实际作答和短训练。重复题不增加跨题次数；业务熟悉度需过程证据，效率需分步记录。状态不是能力分数。'}


def request_context(app):
    profile=overview(app)
    return {'version':VERSION,'definitions':{k:{'name':v['name'],'look_for':v['description']} for k,v in DIMENSIONS.items()},
        'previous_dimensions':[{'dimension':c['dimension'],'state':c['state'],'weak_questions':c['weak_questions'],
            'summary':(c['conclusion'] or {}).get('summary','')[:600],
            'evidence':[{'source_ref':o['source_ref'],'judgment':o['judgment'],'observation':o['observation'][:350],
                         'user_quote':o['user_quote'][:250]} for o in c['observations'][:2]]} for c in profile['dimensions']]}


def attach_training(app,observations,abilities,tasks):
    """Turn the model's specific verification questions into existing local short tasks."""
    known={a['id']:a for a in abilities}
    for ob in observations:
        if ob['judgment']=='adequate' or not ob['verify'].strip() or not ob['action'].strip():continue
        meta=DIMENSIONS[ob['dimension']]
        aid='ab_'+coach.digest([ob['module'],ob['point'],ob['dimension']])[:16]
        previous=known.get(aid,{})
        ids=list(previous.get('evidence_attempt_ids',[]))
        if ob['source_type']=='attempt':ids=list(dict.fromkeys(ids+[ob['source_id']]))
        else:
            parent=app.store.get('coach_tasks',ob['source_id'],{})
            if parent.get('attempt_id'):ids=list(dict.fromkeys(ids+[parent['attempt_id']]))
        if not ids:continue
        versions={**previous.get('question_versions',{}),ob['question_id']:ob['source_version']}
        a={'id':aid,'name':'申论 · '+meta['name'],'stage':meta['stage'],'dimension':ob['dimension'],
            'module':ob['module'],'point':ob['point'],'hypothesis':ob['observation'],'fix':ob['action'],
            'confidence':'待验证' if ob['judgment']=='uncertain' else '有作答证据','evidence_attempt_ids':ids,
            'question_versions':versions,'created_at':previous.get('created_at',coach.stamp()),'updated_at':coach.stamp()}
        known[aid]=a
        if not ob['material_complete']:continue
        if len(tasks)>=3 or any(t.get('dimension')==ob['dimension'] and t['question_id']==ob['question_id'] for t in tasks):continue
        prompts=ob['verification_prompts'] or [ob['verify']]
        tasks.append({'id':'ct_'+coach.digest([ob['id'],prompts])[:20],'analysis_id':ob['analysis_id'],
            'ability_id':aid,'dimension':ob['dimension'],'point':ob['point'],'module':ob['module'],'stage':meta['stage'],
            'dimension_context_version':ob['context_version'],
            'question_id':ob['question_id'],'attempt_id':ids[-1],'source_version':ob['source_version'],
            'title':meta['name']+' · 针对性验证','prompts':prompts,'reference':ob['reference'],
            'hint':ob['action'],'status':'ready','answers':[],'hint_used':False,'created_at':coach.stamp()})
    return list(known.values()),tasks


PROMPT='''
申论纳入本次综合AI薄弱点分析，不只给单题采点。shenlun_dimensions提供七维定义和上次已保存的维度结论。把新作答、新补充、短训练与旧结论整合；比较跨题重复、已有改善和待验证原因，不重发或重新分析未变更旧错题。
对本批有证据的维度返回shenlun_dimension_observations数组（最多10项，优先2-4个关键维度，不凑齐七项）。每项dimension为structure/thesis/business/evidence/reasoning/expression/efficiency；source_ref使用dimension_sources给出的attempt:作答id或training:任务id；judgment为weak/adequate/uncertain；observation具体描述个人表现；user_quote逐字引用用户答案或思路；process_quote仅逐字引用用户思路、业务步骤或短训练回答；citations引用该来源材料的{paragraph_id,quote}；action给可执行改法；verify给一个能区分原因的短问题；verification_prompts可给1-3个顺序步骤，reference给材料支持的建议对照。
业务熟悉度必须区分“不理解业务概念、主体职责、办理流程、机制”与“读漏材料、表达遗漏”。仅漏点或写得空不能证明业务不熟，没有业务过程证据只能提出待验证假设。主旨凝练不等于必须写总括句。层次划分不等于必须递进或固定分段。效率没有分步计时就不能说用户慢在某一步；短任务的页面停留时间也不是经过校准的速度标准，必须保留比较和原因的不确定性。
未确认手写转写、不作答、材料不足，不据此定个人能力。部分材料只能评价已可见表达，不能认定内容遗漏或已掌握。短训练与原题反复修改不等于独立迁移。
同时返回shenlun_dimension_conclusions数组：只更新有新证据的维度，每项dimension、summary（跨题的具体个人判断，不是模块课程）、evidence_refs（新证据或previous_dimensions里存在的source_ref）、change（何处反复/改善/待验证）、next_step。其他维度保留原结论。不编证据，不生成未经校准的能力分数。可简化重复的abilities/training_tasks：程序能将维度的具体verify自动接入能力档案与短训练。
整份JSON继续控制长度，申论深度报告本批最多一题。维度观察每项不超过180字、结论每项不超过150字，优先最有证据的关键问题，避免将原报告整段复述。
'''
