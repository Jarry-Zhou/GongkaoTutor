"""Pinned national-exam data adapter. Downloads stay local; histories stay intact."""
import base64
import concurrent.futures
import copy
import hashlib
import html
from html.parser import HTMLParser
import io
import json
from functools import lru_cache
from pathlib import Path,PurePosixPath
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT/'banks/guokao/source.json'
LOCK=threading.RLock()
WORKERS={}
SAFE_TAGS={'p','br','table','thead','tbody','tr','th','td','sup','sub','strong','em','b','i','span','ul','ol','li'}
MODULES={'言语理解与表达':'言语理解'}


def stamp():return datetime.now(timezone.utc).isoformat()
def digest(obj):return hashlib.sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def git_sha(data):return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
@lru_cache(maxsize=1)
def spec():
    value=json.loads(SOURCE.read_text('utf-8'))
    if value['repository']!='https://github.com/ERRRC/xingcezhenti' or not re.fullmatch('[a-f0-9]{40}',value['commit']):
        raise ValueError('Unexpected source specification')
    return value


def safe_source_path(path):
    p=PurePosixPath(path)
    if p.is_absolute() or '..' in p.parts or '\\' in path or not path or len(path)>500:
        raise ValueError('Unsafe source path')
    return p


def walk(nodes):
    for node in nodes:
        yield node
        yield from walk(node.get('children',[]))


def plain(nodes):
    def text(node):
        if node['tag']=='text':return node['text']
        if node['tag']=='img':return '【图 '+node['label']+'】'
        if node['tag']=='missing':return '【来源图片缺失】'
        value=''.join(text(c) for c in node.get('children',[]))
        if node['tag'] in ('p','br','tr','li'):value+='\n'
        if node['tag'] in ('td','th'):value+='\t'
        return value
    return re.sub(r'\n{3,}','\n\n',''.join(text(n) for n in nodes)).strip()


class RichParser(HTMLParser):
    def __init__(self,resolver,role):
        super().__init__(convert_charrefs=True)
        self.nodes=[];self.stack=[self.nodes];self.tags=[];self.resolver=resolver;self.role=role
        self.images=0;self.missing=[];self.ignore=0

    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','iframe','object'):self.ignore+=1;return
        if self.ignore:return
        attrs=dict(attrs)
        if tag=='img':
            src=html.unescape(attrs.get('src',''));self.images+=1;label=self.role+'-'+str(self.images)
            if src.startswith('../'):src=src[3:]
            safe=bool(re.fullmatch(r'90-图片/(?:题目图|公式图)/[A-Za-z0-9_.-]+\.(?:png|jpg|jpeg|webp|gif)',src))
            asset=self.resolver(src) if safe else None
            if asset:self.stack[-1].append({'tag':'img',**asset,'label':label})
            else:self.missing.append(src);self.stack[-1].append({'tag':'missing','label':label})
        elif tag in SAFE_TAGS:
            node={'tag':tag,'children':[]}
            if tag in ('td','th'):
                for key in ('colspan','rowspan'):
                    if str(attrs.get(key,'')).isdigit():node[key]=max(1,min(20,int(attrs[key])))
            self.stack[-1].append(node)
            if tag!='br' and len(self.stack)<32:self.stack.append(node['children']);self.tags.append(tag)

    def handle_endtag(self,tag):
        if tag in ('script','style','iframe','object'):
            self.ignore=max(0,self.ignore-1);return
        if self.ignore:return
        if tag in self.tags:
            index=len(self.tags)-1-self.tags[::-1].index(tag)
            del self.tags[index:];del self.stack[index+1:]

    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if tag not in ('img','br'):self.handle_endtag(tag)

    def handle_data(self,text):
        if not self.ignore and text:self.stack[-1].append({'tag':'text','text':text})


def parse_rich(value,resolver,role):
    parser=RichParser(resolver,role);parser.feed(value);parser.close()
    return parser.nodes,parser.missing


HEADER=re.compile(r'(?m)^#{2,3}\s+第\s*(\d+)\s*题\s*<sub>qid\s+(\d+)\s*·\s*(.*?)</sub>\s*$|^##\s+材料\s+(\d+)\s*$')
OPTION=re.compile(r'(?ms)^-\s+\*\*([A-J])\*\*[.．]\s*(.*?)(?=^-\s+\*\*[A-J]\*\*[.．]|^\*\*答案|^\*\*官方解析|\Z)')


def parse_paper(text,path,commit,resolver):
    from app import normalize_question
    front=text.split('---',2)
    if len(front)<3:raise ValueError('Missing paper metadata: '+path)
    meta=dict(re.findall(r'^([^:\n]+):\s*"([^"]*)"',front[1],re.M))
    if meta.get('地区')!='国考':raise ValueError('Non-national paper rejected: '+path)
    required=('年份','模块','试卷','题数')
    if any(not meta.get(k) for k in required):raise ValueError('Incomplete paper metadata: '+path)
    marks=list(HEADER.finditer(text));material=[];material_missing=[];group='';rows=[]
    for index,mark in enumerate(marks):
        body=text[mark.end():marks[index+1].start() if index+1<len(marks) else len(text)].strip()
        body=re.sub(r'\n---\s*$','',body).strip()
        if mark[4]:
            material,material_missing=parse_rich(body,resolver,'material')
            group='gkg_'+digest([path,mark[4]])[:24]
            continue
        number,qid,point=mark[1],mark[2],mark[3].strip()
        options=list(OPTION.finditer(body));answer_mark=re.search(r'(?m)^\*\*答案\*\*[:：]\s*([^\n]*)',body)
        explanation_mark=re.search(r'(?m)^\*\*官方解析\*\*\s*$',body)
        first=min([o.start() for o in options]+[answer_mark.start() if answer_mark else len(body)])
        stem,missing=parse_rich(body[:first].strip(),resolver,'stem')
        option_nodes={};option_text={};ticks=[]
        for option in options:
            value=option[2].strip()
            if '✅' in value:ticks.append(option[1]);value=value.replace('✅','').rstrip()
            nodes,bad=parse_rich(value,resolver,'option-'+option[1]);missing+=bad
            option_nodes[option[1]]=nodes;option_text[option[1]]=plain(nodes)
        answer_value=answer_mark[1].strip() if answer_mark else ''
        answer=re.findall('[A-J]',answer_value) if re.fullmatch(r'[A-J、,，\s]+',answer_value) else []
        explanation,bad=parse_rich(body[explanation_mark.end():].strip() if explanation_mark else '',resolver,'explanation')
        rich={'stem':stem,'options':option_nodes,'material':copy.deepcopy(material),'explanation':explanation}
        has_images=any(n['tag']=='img' for field in [stem,material,*option_nodes.values()] for n in walk(field))
        raw={'stem':plain(stem),'options':option_text,'answer':answer,'explanation':plain(explanation),
            'module':MODULES.get(meta['模块'],meta['模块']),'subtype':point,'knowledge_points':[point or meta['模块']],
            'type':'multiple' if len(answer)>1 else 'single','material':plain(material),'difficulty':'未标注',
            'year':meta['年份'],'region':'国考','group_id':group,'whole_group':bool(group),'requires_image':has_images}
        q=normalize_question(raw,'国考真题 · '+meta['试卷'])
        q.update(id='gk_'+digest([path,qid])[:24],rich_content=rich,source_number=int(number),requires_image=has_images,
            true_exam={'repository':'https://github.com/ERRRC/xingcezhenti','commit':commit,'path':path,'qid':qid,
                'paper':meta['试卷'],'year':meta['年份'],'module_number':int(number),'kind':'来源整理/网友回忆版',
                'source_url':'https://github.com/ERRRC/xingcezhenti/blob/'+commit+'/'+urllib.parse.quote(path,safe='/')})
        # These are source image elements, not uncertain OCR crops.
        q['issues']=[s for s in q['issues'] if s!='图形可能缺失，请补充材料后核对' or not has_images]
        if missing or material_missing:q['issues'].append('来源题面或材料图片缺失，暂不进入练习')
        if ticks and set(ticks)!=set(answer):q['issues'].append('来源答案与选项勾选不一致，待核对')
        if len(set(o[1] for o in options))!=len(options):q['issues'].append('来源选项重复')
        q['source_warnings']=['解析图片缺失：'+p for p in bad]
        q['status']='review' if q['issues'] else 'ready'
        picture_ids=[n['asset'] for nodes in [stem,material,*option_nodes.values()] for n in walk(nodes) if n['tag']=='img']
        q['fingerprint']=digest([q['stem'],q['options'],q['material'],picture_ids])
        rows.append(q)
    if len(rows)!=int(meta['题数']):raise ValueError(f'Question count mismatch in {path}: {len(rows)} / {meta["题数"]}')
    if len({q['id'] for q in rows})!=len(rows):raise ValueError('Duplicate source qid in '+path)
    return rows


def asset_path(app,key):
    if not isinstance(key,str) or not re.fullmatch('[a-f0-9]{64}',key):raise app.uploads.error('题库图片编号无效。',404)
    path=app.store.folder/'national-bank/assets'/key
    if not path.is_file():raise app.uploads.error('题库配图缺失，请修复真题下载。',404)
    return path


def image_mime(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'):return 'image/png'
    if data.startswith(b'\xff\xd8\xff'):return 'image/jpeg'
    if data.startswith(b'GIF8'):return 'image/gif'
    if data.startswith(b'RIFF') and data[8:12]==b'WEBP':return 'image/webp'
    raise ValueError('Unsupported bank image')


def _fetch_source(item,source,cache,seed=None):
    relative=safe_source_path(item['path']);path=cache.joinpath(*relative.parts);path.parent.mkdir(parents=True,exist_ok=True)
    candidates=[path]+([Path(seed).joinpath(*relative.parts)] if seed else [])
    for candidate in candidates:
        if candidate.is_file():
            data=candidate.read_bytes()
            if len(data)==item['size'] and git_sha(data)==item['sha']:
                if candidate!=path:path.write_bytes(data)
                return path
    url='https://raw.githubusercontent.com/ERRRC/xingcezhenti/'+source['commit']+'/'+urllib.parse.quote(item['path'],safe='/')
    for attempt in range(4):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'GongkaoTutor-national-bank'})
            with urllib.request.urlopen(req,timeout=45) as response:data=response.read(item['size']+1)
            if len(data)!=item['size'] or git_sha(data)!=item['sha']:raise ValueError('Source checksum mismatch: '+item['path'])
            temp=path.with_suffix(path.suffix+'.part');temp.write_bytes(data);temp.replace(path)
            return path
        except (urllib.error.URLError,TimeoutError):
            if attempt==3:raise
            time.sleep(attempt+1)


def prepare(app,seed=None,progress=None,source=None):
    from PIL import Image
    source=source or spec();cache=app.store.folder/'national-bank/upstream';cache.mkdir(parents=True,exist_ok=True)
    files=source['notes']+source['images'];total=len(files)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        def fetch(item):return _fetch_source(item,source,cache,seed)
        for done,_ in enumerate(pool.map(fetch,files),1):
            if progress and (done%25==0 or done==total):progress('下载并校验',done,total)
    assets={};asset_dir=app.store.folder/'national-bank/assets';asset_dir.mkdir(parents=True,exist_ok=True)
    for index,item in enumerate(source['images'],1):
        path=cache.joinpath(*safe_source_path(item['path']).parts);data=path.read_bytes();mime=image_mime(data)
        with Image.open(io.BytesIO(data)) as im:
            width,height=im.size
            if width*height>40_000_000 or min(width,height)<=0:raise ValueError('Invalid image dimensions')
            im.verify()
        key=hashlib.sha256(data).hexdigest();target=asset_dir/key
        if not target.exists():target.write_bytes(data)
        assets[item['path']]={'asset':key,'width':width,'height':height,'mime':mime}
        if progress and index%250==0:progress('核验配图',index,len(source['images']))
    questions=[]
    for index,item in enumerate(source['notes'],1):
        text=cache.joinpath(*safe_source_path(item['path']).parts).read_text('utf-8')
        questions.extend(parse_paper(text,item['path'],source['commit'],assets.get))
        if progress and index%20==0:progress('解析题目',index,len(source['notes']))
    if len({q['id'] for q in questions})!=len(questions):raise ValueError('Duplicate question identifiers')
    report={'source_id':source['id'],'repository':source['repository'],'commit':source['commit'],
        'questions':len(questions),'ready':sum(q['status']=='ready' for q in questions),
        'review':sum(q['status']!='ready' for q in questions),'papers':len({q['true_exam']['paper'] for q in questions}),
        'unique_content':len({q['fingerprint'] for q in questions}),'images':len(assets),'prepared_at':stamp()}
    target=app.store.folder/'national-bank/prepared.json'
    temp=target.with_suffix('.tmp');temp.write_text(json.dumps({'questions':questions,'report':report},ensure_ascii=False),'utf-8');temp.replace(target)
    return questions,report


def visible_questions(app):
    state=app.store.get('bank_catalog','current',{});hidden=set(state.get('hidden_question_ids',[]))
    return [q for q in app.store.all('questions') if q['id'] not in hidden]


def install(app,questions,report,replace=False):
    from app import uid
    with LOCK,app.store.lock,app.store.connect() as db:
        current=app.store.get('bank_catalog','current',{})
        if current.get('source_commit')==report['commit'] and current.get('installed_question_ids')==[q['id'] for q in questions]:
            return {**current,'reused':True}
        old=visible_questions(app)
        if old and not replace:raise app.uploads.error('已有题库。请确认替换后再安装；原题与历史会归档保留。',409)
        previous_hidden=list(current.get('hidden_question_ids',[]))
        incoming={q['id'] for q in questions}
        # Existing source rows are not overwritten; user edits remain user edits.
        for q in questions:
            if not app.store.get('questions',q['id']):app.store.put('questions',q,db)
        hidden=sorted((set(previous_hidden)|{q['id'] for q in old})-incoming)
        event={'id':uid('bank_'),'kind':'install','created_at':stamp(),'previous_state':current,
            'previous_visible_ids':[q['id'] for q in old],'installed_ids':[q['id'] for q in questions],'report':report}
        state={'id':'current','source_commit':report['commit'],'active_install':event['id'],
            'installed_question_ids':[q['id'] for q in questions],'hidden_question_ids':hidden,'report':report}
        app.store.put('bank_catalog',event,db);app.store.put('bank_catalog',state,db)
        return {**state,'reused':False}


def restore(app):
    with LOCK,app.store.lock,app.store.connect() as db:
        state=app.store.get('bank_catalog','current',{});event=app.store.get('bank_catalog',state.get('active_install'),{})
        if not event or event.get('kind')!='install':raise app.uploads.error('暂无可恢复的旧题库。',409)
        previous=event.get('previous_state',{});hidden=set(previous.get('hidden_question_ids',[]))
        hidden.update(set(event['installed_ids'])-set(event['previous_visible_ids']))
        previous={**previous,'id':'current','hidden_question_ids':sorted(hidden),'restored_from':event['id'],'restored_at':stamp()}
        app.store.put('bank_catalog',previous,db)
        return status(app,override=previous)


def status(app,override=None):
    source=spec();state=override if override is not None else app.store.get('bank_catalog','current',{})
    report=state.get('report',{});job=app.store.get('bank_catalog','job',{})
    return {'source_name':source['name'],'repository':source['repository'],'commit':source['commit'],'scope':source['scope'],
        'installed':state.get('source_commit')==source['commit'],'report':report,
        'archived':len(state.get('hidden_question_ids',[])),'can_restore':bool(state.get('active_install')),
        'job':{k:v for k,v in job.items() if k in ('status','phase','done','total','error','report')},
        'download_files':len(source['notes'])+len(source['images']),
        'download_bytes':sum(i['size'] for i in source['notes']+source['images'])}


def start_install(app,body):
    if body.get('confirmed') is not True:raise app.uploads.error('请先确认下载并替换题库。',409)
    key=str(app.store.path)
    with LOCK:
        if key in WORKERS and WORKERS[key].is_alive():return status(app)
        if app.store.get('bank_catalog','current',{}).get('source_commit')==spec()['commit']:return status(app)
        def update(phase,done,total):app.store.put('bank_catalog',{'id':'job','status':'running','phase':phase,'done':done,'total':total})
        def work():
            try:
                qs,report=prepare(app,progress=update);install(app,qs,report,replace=True)
                app.store.put('bank_catalog',{'id':'job','status':'completed','phase':'完成','report':report})
            except Exception as error:
                # Do not leak paths, user data, or upstream HTML into a status error.
                app.store.put('bank_catalog',{'id':'job','status':'failed','error':'下载、校验或解析未完成，原题库保留。可重试复用已下载文件。','phase':type(error).__name__})
        app.store.put('bank_catalog',{'id':'job','status':'running','phase':'准备','done':0,'total':len(spec()['notes'])+len(spec()['images'])})
        worker=threading.Thread(target=work,daemon=True);WORKERS[key]=worker;worker.start()
    return status(app)


def recover_job(app):
    row=app.store.get('bank_catalog','job',{})
    if row.get('status')=='running':
        app.store.put('bank_catalog',{**row,'status':'interrupted','error':'上次下载被中断，重新下载可复用已校验文件。'})


def image_roles(q):
    rich=q.get('rich_content') or {}
    question=[]
    for part in [rich.get('stem',[]),*rich.get('options',{}).values()]:question.extend(n for n in walk(part) if n['tag']=='img')
    material=[n for n in walk(rich.get('material',[])) if n['tag']=='img']
    return [('material',material),('question',question)]


def image_count(q):return sum(bool(images) for _,images in image_roles(q))


def model_images(app,q,limit=6):
    from PIL import Image,ImageDraw
    roles=[(kind,images) for kind,images in image_roles(q) if images]
    if len(roles)>limit:raise app.uploads.error('本次题图数量超限，请缩小分析范围。',409)
    out=[]
    for kind,nodes in roles:
        parts=[]
        try:
            for node in nodes:
                path=asset_path(app,node['asset'])
                with Image.open(path) as raw:image=raw.convert('RGB')
                image.thumbnail((1600,5000));parts.append((node['label'],image))
            width=max(im.width for _,im in parts)+24;height=sum(im.height+36 for _,im in parts)
            if height>20000 or width*height>30_000_000:raise app.uploads.error('本题图片过长，请先单题核对。',409)
            canvas=Image.new('RGB',(width,height),'white');draw=ImageDraw.Draw(canvas);y=0
            try:
                for label,image in parts:
                    draw.text((12,y+6),kind+' / '+label,fill='black');canvas.paste(image,(12,y+28));y+=image.height+36
                buf=io.BytesIO();canvas.save(buf,'JPEG',quality=92)
                out.append('data:image/jpeg;base64,'+base64.b64encode(buf.getvalue()).decode('ascii'))
            finally:canvas.close()
        finally:
            for _,image in parts:image.close()
    return out
