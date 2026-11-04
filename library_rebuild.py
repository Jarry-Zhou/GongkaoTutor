"""Rebuild from accepted page caches without rerunning OCR or calling a model."""
import hashlib
import re
from pathlib import Path
import book_import
import file_pages
import local_ocr


def attach_origins(rows,bid,fid,name):
    for row in rows:
        if row.get('module')=='判断推理':
            from app import classify
            c=classify(row,'判断推理')
            if row.get('requires_image'):row.update(subtype='图形推理',knowledge_points=['图形规律'])
            elif row['stem'].count('：')>=2 and len(row['stem'])<90:row.update(subtype='类比推理',knowledge_points=['词项关系辨析'])
            elif c['subtype']:row.update(subtype=c['subtype'],knowledge_points=c['knowledge_points'])
        if row.get('module')=='资料分析' and row.get('source_section','').startswith('刷题'):
            stem=row['stem']
            topic='综合分析' if re.search('可以推出|正确|说法|描述|有几条',stem) else '平均数' if re.search('平均|人均|每个',stem) else '比重与贡献率' if re.search('占|比重|贡献|拉动|百分点',stem) else '倍数' if re.search('几倍|倍数|多少倍|相当于',stem) else '增长率' if re.search('增长率|增速|增幅|增长最快|同比增长了',stem) else '增长量' if re.search('增量|增加|减少|下降了',stem) else '统计资料计算'
            row.update(subtype=topic,knowledge_points=[topic])
        pages=sorted(set(row.get('material_pages',[])+row.get('source_pages',[])))
        row['page_images']=[{'batch_id':bid,'file_id':fid,'page':n,'label':f"{row.get('source_section','')} · 第{row.get('source_number','')}题 · 原文件第{n}页"} for n in pages[:10]]
        row['display_original']=bool(row.get('requires_image') or '资料分析' in name)
        if row.get('reading_source') and (row.get('requires_image') or row.get('subtype')=='图形推理') and row.get('module')!='资料分析':
            row['reading_source']['presentation']='figure'
        row['origin_key']=hashlib.sha256((bid+fid+str(row.get('source_section',''))+':'+str(row.get('source_number',''))).encode()).hexdigest()
    return rows


def quote_span(text,quote):
    positions=[i for i,c in enumerate(text) if c.isalnum()];normalized=''.join(text[i] for i in positions)
    needle=''.join(c for c in quote if c.isalnum());start=normalized.find(needle)
    if start>=0 and needle:
        left,right=positions[start],positions[start+len(needle)-1]+1
        while left>0 and text[left-1] in '“‘"（(【[':left-=1
        while right<len(text) and text[right] in '。！？；：）)】]”’"．.':right+=1
        return left,right
    return None

def subjective_local(pages,verified_tasks=None):
    rows=[]
    for i,b in enumerate(book_import.subjective_blocks(pages)):
        text=b['text'];req=list(re.finditer('要求[：:]',text));pivot=req[-1].start() if req else len(text)
        starts=list(re.finditer(r'(?m)^[^\n]{0,100}(?:请你|请根据|请结合|请围绕|请就|请拟|请撰写|结合给定资料|围绕|谈谈|归纳概括|根据[“"「]?(?:给定)?资料|假如你|假设你|[“"「]给定资料)[^\n]*',text[:pivot]))
        if starts:start=starts[-1].start()
        elif req:
            prefix=text[:pivot].rstrip();boundary=prefix.rfind('\n\n');start=boundary+2 if boundary>=0 else max(0,prefix.rfind('。',0,max(0,len(prefix)-100))+1)
        else:continue
        stem=text[start:].strip();material=text[:start].strip()
        verified=(verified_tasks or {}).get(str(i+1),{})
        span=quote_span(text,verified.get('stem','')) if verified else None
        if span:start,end=span;stem=text[start:end].strip();material=text[:start].strip()
        if not req or len(stem)<25:continue
        subtype='文章写作' if re.search('写一篇.{0,10}文章|议论|自拟题目|1000字',stem) else '提出对策' if re.search('建议|对策|解决',stem) else '归纳概括' if re.search('概括|归纳',stem) else '综合分析'
        score=re.search(r'[（(](\d+)分[）)]',stem)
        rows.append({'stem':stem,'material':material,'type':'essay' if subtype=='文章写作' else 'short','answer':'','options':{},'reference_optional':True,'module':'申论','subtype':subtype,'knowledge_points':[subtype],
                     'points':int(score[1]) if score else 20,'score_basis':'原题分值' if score else '原题未标分值，练习默认20分，模考可自行设置','source_pages':b['pages'],'source_page':b['pages'][0],'source_number':i+1,'source_section':b['title']})
    return rows


def build_rows(pages,name,bid,fid):
    if '申论' in name:
        rows=subjective_local(pages);meta={'subjective':True,'key_pages':[]}
    else:
        rows,meta=book_import.parse_objective(pages,name)
        if not rows:
            from app import parse_text
            text,spans=book_import.join_pages(pages);rows=parse_text(text)
            for i,q in enumerate(rows):q.update(source_number=i+1,source_section='题目',source_pages=[p['page'] for p in pages])
    return attach_origins(rows,bid,fid,name),meta


def rebuild(manager,bid,fid,body=None):
    body=body or {};app=manager.app
    with manager.lock:
        batch,item=manager.require(bid,fid)
        if item['status'] in ('queued','parsing','deleting','deleted'):raise manager.error('请在当前文件解析结束且未删除时重建。',409)
        helper=app.page_assist.pages;source,_=helper.source(bid,fid);total=helper.count(bid,fid)
        old=manager.store.get('documents',item.get('document_id',''));old_pages=file_pages.split_pages(old['text']) if old else {}
        pages=[helper.read(bid,fid,n,old_pages,source) for n in range(1,total+1)]
        infos=[{k:v for k,v in p.items() if k in ('page','chars','method','confidence','low_confidence_lines','page_kind','error')} for p in pages]
        report=local_ocr.report(infos,item.get('ocr_mode','auto'))
        if item['purpose']=='document':
            text='\n\n'.join(f"[第 {p['page']} 页]\n"+p['text'] for p in pages)
            doc=app.add_document({'title':old['title'] if old else item['name'],'text':text},persist=False)
            if old:doc.update(id=old['id'],created_at=old['created_at'])
            doc.update(ocr=report,source_file={'batch_id':bid,'file_id':fid},page_quality=[{'page':p['page'],'page_kind':p.get('page_kind','content'),'method':p['method']} for p in pages])
            with manager.store.connect() as db:
                app.save_document(doc,db);batch,item=manager.require(bid,fid)
                item.update(status='completed',document_id=doc['id'],chars=len(text),chunks=len(doc['chunks']),ocr=report,error='',progress={'stage':'跨页资料已重建并入库'})
                manager.store.put('file_imports',batch,db)
            return {'document_id':doc['id'],'chars':len(text),'chunks':len(doc['chunks']),'ocr':report}
        tasks_path=source.with_suffix('.book-tasks.json')
        if '申论' in item['name'] and tasks_path.is_file():
            import json
            tasks=json.loads(tasks_path.read_text('utf-8'));rows=attach_origins(subjective_local(pages,tasks),bid,fid,item['name']);meta={'subjective':True,'key_pages':[]}
        else:rows,meta=build_rows(pages,item['name'],bid,fid)
        if not rows:raise manager.error('已保存逐页结果，但尚无完整作答题目。请检查作答要求或题干边界。')
        preview=app.preview_import({'rows':rows,'name':item['name']},persist=False);preview.update(book_meta=meta,ocr=report)
        previous=manager.store.get('imports',item.get('import_id',''))
        if previous and previous['status']=='preview':preview.update(id=previous['id'],created_at=previous['created_at'])
        with manager.store.connect() as db:
            manager.store.put('imports',preview,db);batch,item=manager.require(bid,fid)
            item.update(status='preview_ready',import_id=preview['id'],question_count=len(preview['items']),review_count=sum(q['status']=='review' for q in preview['items']),ocr=report,error='',progress={'stage':'跨页题目与书末答案已重建，可确认入库'})
            manager.store.put('file_imports',batch,db)
        return {'import_id':preview['id'],'total':len(preview['items']),'review':item['review_count'],'ocr':report}
