"""Local, reproducible estimate drills. Separate from exam and AI evidence records."""
import random
import re
import threading
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

D = Decimal
TOLERANCE = D('3')
CENT = D('.01')
LOCK = threading.RLock()
FORMULA_VERSION = 1
KINDS = {
    'base_a': ('A 的基期量', '基期与增长量', '亿元', "A′ = A ÷ (1 + r₁)", '先把百分数换成增长倍数；正增长时基期应小于现期。'),
    'base_b': ('B 的基期量', '基期与增长量', '亿元', "B′ = B ÷ (1 + r₂)", '除以增长倍数，不是直接减去增长率。'),
    'increase_a': ('A 的增长量', '基期与增长量', '亿元', "ΔA = A × r₁ ÷ (1 + r₁)", '增长量也等于现期减基期；负增长时增长量为负。'),
    'increase_b': ('B 的增长量', '基期与增长量', '亿元', "ΔB = B × r₂ ÷ (1 + r₂)", '先估基期再相减，或直接算现期乘 r/(1+r)。'),
    'share_now': ('现期比重', '比重与比值', '%', '现期比重 = A ÷ B × 100%', 'A 是部分，B 是整体。直接填写百分数数值，如 21.92。'),
    'share_base': ('基期比重', '比重与比值', '%', "基期比重 = A′ ÷ B′ × 100%", '也可用现期比重 × (1+r₂)/(1+r₁)。'),
    'share_change': ('两期比重差', '比重与比值', '个百分点', '比重差 = A/B × (r₁−r₂)/(1+r₁) × 100', '现期比重减基期比重，单位是百分点；r₁小于r₂时结果为负。'),
    'ratio_growth': ('比值增长率', '比重与比值', '%', '比值增长率 = (r₁−r₂)/(1+r₂) × 100%', '这是比值的相对增长率，与两期比重差的百分点不同。'),
    'base_sum': ('基期和', '和差与间隔', '亿元', "基期和 = A′ + B′", '此处只把A、B当作两个数列求和，不视为不重叠的业务总量。'),
    'base_difference': ('基期差', '和差与间隔', '亿元', "基期差 = B′ − A′", '按B减A的顺序作差，先分别还原基期。'),
    'compound_growth': ('间隔增长率', '和差与间隔', '%', '间隔增长率 = r₁ + r₂ + r₁×r₂', '本项把r₁、r₂视为连续两段增长率；乘积不能在所有场景下都忽略。'),
    'sum_growth': ('和的增长率', '和差与间隔', '%', "和增长率 = (A+B)/(A′+B′) − 1", '不是两率的算术平均。正基期下结果应介于两项增长率之间。'),
    'difference_growth': ('差的增长率', '和差与间隔', '%', "差增长率 = (B−A)/(B′−A′) − 1", '先求现期差与基期差，再相除减1。不能直接用两项增长率相减。'),
}


def stamp(): return datetime.now(timezone.utc).isoformat()
def identifier(prefix): return prefix + uuid.uuid4().hex[:16]
def rounded(n): return n.quantize(CENT, rounding=ROUND_HALF_UP)
def fmt(n): return format(rounded(D(n)), 'f')


def values(p):
    a,b,r1,r2=(D(str(p[k])) for k in ('a','b','r1','r2'))
    x,y=r1/100,r2/100
    if not (0<a<b and -100<r1 and -100<r2): raise ValueError('Invalid drill parameters')
    a0,b0=a/(1+x),b/(1+y)
    if b0<=a0: raise ValueError('Invalid base difference')
    return {'base_a':a0,'base_b':b0,'increase_a':a-a0,'increase_b':b-b0,
        'share_now':a/b*100,'share_base':a0/b0*100,
        'share_change':(a/b-a0/b0)*100,'ratio_growth':(x-y)/(1+y)*100,
        'base_sum':a0+b0,'base_difference':b0-a0,
        'compound_growth':(x+y+x*y)*100,
        'sum_growth':((a+b)/(a0+b0)-1)*100,
        'difference_growth':((b-a)/(b0-a0)-1)*100}


def generate(level, rng=None):
    rng=rng or random.SystemRandom()
    for _ in range(1000):
        scale={'basic':1,'standard':1,'challenge':10}[level]
        b=D(rng.randint(250,1800))*scale
        a=rounded(b*D(rng.randint(12,70))/100)
        if level=='basic':
            r1,r2=(D(rng.choice([5,10,15,20,25,30,40,50])) for _ in range(2))
            a=D(int(a));b=D(int(b))
        else:
            r1,r2=(D(rng.randint(-150 if level=='challenge' else 10,550))/10 for _ in range(2))
        if r1==r2:continue
        p=dict(zip(('a','b','r1','r2'),map(str,(a,b,r1,r2))))
        try:v=values(p)
        except ValueError:continue
        if v['base_difference']<b*D('.12') or v['share_base']>95:continue
        if max(abs(n) for n in v.values())>100000:continue
        return p
    raise RuntimeError('Unable to generate valid drill')


def parse_answer(raw, unit):
    if not isinstance(raw,(str,int,float)) or isinstance(raw,bool): raise ValueError()
    raw=str(raw).strip().replace('−','-').replace('－','-').replace('＋','+')
    if len(raw)>40:raise ValueError()
    suffix=r'(?:个百分点|[%％])' if unit!='亿元' else '亿元'
    raw=re.sub(r'\s*'+suffix+r'\s*$','',raw).strip()
    if re.fullmatch(r'[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?',raw):raw=raw.replace(',','')
    if not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)',raw):raise ValueError()
    n=D(raw)
    if not n.is_finite() or abs(n)>D('1e9'):raise ValueError()
    return n


def grade(question,raw,skipped=False):
    kind=question['kind'];meta=KINDS[kind];p=question['parameters']
    reference=rounded(values(p)[kind]);n=None if skipped else parse_answer(raw,meta[2])
    error=None if n is None else n-reference
    direction=bool(n is not None and n*reference<0)
    a,b,r1,r2=(p[k] for k in ('a','b','r1','r2'))
    substitution={
        'base_a':f'{a} ÷ (1 + {r1}%)','base_b':f'{b} ÷ (1 + {r2}%)',
        'increase_a':f'{a} × {r1}% ÷ (1 + {r1}%)','increase_b':f'{b} × {r2}% ÷ (1 + {r2}%)',
        'share_now':f'{a} ÷ {b} × 100%',
        'share_base':f'({a} ÷ {b}) × (1 + {r2}%) ÷ (1 + {r1}%) × 100%',
        'share_change':f'({a} ÷ {b}) × ({r1}% − {r2}%) ÷ (1 + {r1}%) × 100',
        'ratio_growth':f'({r1}% − {r2}%) ÷ (1 + {r2}%) × 100%',
        'base_sum':f'{a} ÷ (1 + {r1}%) + {b} ÷ (1 + {r2}%)',
        'base_difference':f'{b} ÷ (1 + {r2}%) − {a} ÷ (1 + {r1}%)',
        'compound_growth':f'[{r1}/100 + {r2}/100 + ({r1}/100) × ({r2}/100)] × 100，结果用%表示',
        'sum_growth':f'[{a}+{b}] ÷ [{a}/(1+{r1}%) + {b}/(1+{r2}%)] − 1，再转成百分数',
        'difference_growth':f'[{b}−{a}] ÷ [{b}/(1+{r2}%) − {a}/(1+{r1}%)] − 1，再转成百分数',
    }[kind]
    return {'input':str(raw)[:40] if not skipped else '', 'skipped':skipped,
        'reference':fmt(reference),'lower':fmt(reference-TOLERANCE),'upper':fmt(reference+TOLERANCE),
        'error':str(error) if error is not None else None,
        'correct':bool(n is not None and reference-TOLERANCE<=n<=reference+TOLERANCE),
        'direction_warning':direction,'formula':meta[3],'substitution':substitution,'tip':meta[4],
        'at':stamp()}


def settle(s, at=None):
    at=time.time() if at is None else at
    if s['status']=='active':
        end=min(at,s['heartbeat_at']+30)
        s['elapsed']=round(s['elapsed']+max(0,end-s['segment_at']),3)
        s['segment_at']=at
        if at>s['heartbeat_at']+30:s['status']='paused'


def public(s):
    questions=[]
    for q in s['questions']:
        name,group,unit,formula,tip=KINDS[q['kind']]
        item={**q,'name':name,'group':group,'unit':unit,'hint_used':q['id'] in s['hints'],
            'draft':s['drafts'].get(q['id'],''),'result':s['results'].get(q['id'])}
        if item['hint_used']:item['hint']={'formula':formula,'tip':tip}
        questions.append(item)
    results=list(s['results'].values())
    return {k:s[k] for k in ('id','mode','level','types','status','created_at','finished_at','review_item','formula_version')} | {
        'questions':questions,'total':len(questions),'answered':len(results),
        'correct':sum(r['correct'] for r in results),'elapsed_seconds':round(s['elapsed'],1),
        'tolerance':3,'rule':'参考值保留两位小数后，按显示单位判定绝对误差≤3；不是相对误差3%。'}


def create(app,body):
    mode=body.get('mode','quick');level=body.get('level','standard');kinds=body.get('types',list(KINDS))
    if mode not in ('quick','table') or level not in ('basic','standard','challenge'):
        raise app.uploads.error('请选择有效的训练模式和难度。')
    if not isinstance(kinds,list) or not kinds or len(kinds)>13 or any(not isinstance(k,str) or k not in KINDS for k in kinds):
        raise app.uploads.error('请至少选择一种有效题型。')
    kinds=list(dict.fromkeys(kinds))
    raw_count=body.get('count',10)
    if isinstance(raw_count,bool) or str(raw_count) not in ('5','10','20','30'):
        raise app.uploads.error('单项速练题量支持5、10、20或30题。')
    count=int(raw_count);rng=random.SystemRandom();group=generate(level,rng)
    order=kinds.copy();questions=[]
    if mode=='quick':
        rng.shuffle(order)
        while len(order)<count:order+=kinds
        order=order[:count];rng.shuffle(order)
    for kind in order:
        questions.append({'id':identifier('cq_'),'kind':kind,'parameters':group if mode=='table' else generate(level,rng)})
    if mode=='quick':questions=questions[:count]
    t=time.time();s={'id':identifier('ctn_'),'mode':mode,'level':level,'types':kinds,
        'questions':questions,'results':{},'drafts':{},'hints':[], 'formula_version':FORMULA_VERSION,
        'created_at':stamp(),'finished_at':None,'status':'active','elapsed':0,'segment_at':t,'heartbeat_at':t,
        'review_item':None,'last_answer_elapsed':0}
    with LOCK:app.store.put('calculation_sessions',s)
    return public(s)


def action(app,sid,verb,body):
    with LOCK:
        s=app.require('calculation_sessions',sid);settle(s)
        byid={q['id']:q for q in s['questions']}
        if verb=='read':pass
        elif verb=='draft':
            drafts=body.get('values',{})
            if not isinstance(drafts,dict):raise app.uploads.error('草稿格式无效。')
            for qid,value in drafts.items():
                if qid in byid and qid not in s['results'] and isinstance(value,str):s['drafts'][qid]=value[:40]
        elif verb=='heartbeat':
            if s['status']=='active':s['heartbeat_at']=time.time()
        elif verb=='pause':
            if s['status']=='active':s['status']='paused'
        elif verb=='start':
            if s['status'] in ('paused','review'):
                if s['status']=='review':s['last_answer_elapsed']=s['elapsed']
                s.update(status='active',segment_at=time.time(),heartbeat_at=time.time(),review_item=None)
        elif verb=='hint':
            qid=body.get('question_id')
            if qid not in byid:raise app.uploads.error('训练题目不存在。',404)
            if qid not in s['hints']:s['hints'].append(qid)
        elif verb in ('answer','skip','check'):
            qid=body.get('question_id')
            if s['status']=='finished' or (verb in ('answer','skip') and qid in s['results']):return public(s)
            if s['status']!='active':
                app.store.put('calculation_sessions',s)
                raise app.uploads.error('训练已暂停，请继续计时后提交。',409)
            pending=[q for q in s['questions'] if q['id'] not in s['results']]
            if s['mode']=='quick':
                if verb=='check' or qid!=pending[0]['id']:raise app.uploads.error('请提交当前训练题。',409)
                requests=[(pending[0],body.get('value',''),verb=='skip')]
            else:
                if verb!='check' or not isinstance(body.get('values'),dict):raise app.uploads.error('请提交本组计算结果。')
                requests=[(q,body['values'].get(q['id'],''),not str(body['values'].get(q['id'],'')).strip()) for q in pending]
            graded={}
            for q,raw,skip in requests:
                try:r=grade(q,raw,skip)
                except (ValueError,InvalidOperation):raise app.uploads.error('请输入有限数值；百分数直接填数值，如21.92，不能填算式。')
                r['hint_used']=q['id'] in s['hints']
                r['duration_seconds']=round(max(0,s['elapsed']-s['last_answer_elapsed']),1) if s['mode']=='quick' else None
                graded[q['id']]=r
            s['results'].update(graded);s['last_answer_elapsed']=s['elapsed']
            s['review_item']=qid if s['mode']=='quick' else None
            s['status']='finished' if len(s['results'])==len(s['questions']) else 'review'
            if s['status']=='finished':s['finished_at']=stamp()
        elif verb=='finish':
            if s['status']!='finished':s.update(status='finished',finished_at=stamp(),review_item=None)
        else:raise app.uploads.error('未找到计算训练操作。',404)
        app.store.put('calculation_sessions',s)
        return public(s)


def overview(app):
    with LOCK:
        sessions=app.store.all('calculation_sessions');stats=defaultdict(lambda:{'answered':0,'correct':0,'skipped':0,'hinted':0})
        total=correct=0;elapsed=0
        for s in sessions:
            if s['status']=='active':
                settle(s);app.store.put('calculation_sessions',s)
            elapsed+=s['elapsed']
            for q in s['questions']:
                r=s['results'].get(q['id'])
                if r is None:continue
                x=stats[q['kind']];x['answered']+=1;x['correct']+=r['correct'];x['skipped']+=r['skipped'];x['hinted']+=r['hint_used']
                total+=1;correct+=r['correct']
        recent=[{'id':s['id'],'mode':s['mode'],'status':s['status'],'created_at':s['created_at'],
            'total':len(s['questions']),'answered':len(s['results']),'correct':sum(r['correct'] for r in s['results'].values()),
            'elapsed_seconds':round(s['elapsed'],1)} for s in sessions[:20]]
        return {'types':[{'id':k,'name':m[0],'group':m[1],'unit':m[2],'formula':m[3],'tip':m[4],**stats[k]} for k,m in KINDS.items()],
            'total':total,'correct':correct,'elapsed_seconds':round(elapsed,1),'recent':recent,
            'tolerance':3,'rule':'绝对误差≤3：亿元题±3亿元，百分数题±3个百分点；边界也达标。'}
