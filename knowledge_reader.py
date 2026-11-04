"""Bounded document reading and search with original physical page provenance."""
import re
import file_pages
from book_import import clean_page

def read(app,key,body):
    doc=app.require('documents',key);pages=file_pages.split_pages(doc['text']) or {1:doc['text']}
    requested=body.get('page')
    if requested is None:
        requested=next((n for n,t in pages.items() if len(clean_page(t))>150 and re.search('。|！|？',t) and not re.search(r'目\s*录',t[:25])),next(iter(pages)))
    if isinstance(requested,bool) or not isinstance(requested,int) or requested not in pages:raise app.uploads.error('页码超出资料范围。')
    nonblank=[n for n,t in pages.items() if t.strip()]
    previous=max((n for n in nonblank if n<requested),default=None);following=min((n for n in nonblank if n>requested),default=None)
    quality={p['page']:p for p in doc.get('page_quality',[])};source=doc.get('source_file',{})
    sections=[]
    for n in [requested]+([following] if following else []):
        p=quality.get(n,{})
        url=f"/api/file-imports/{source['batch_id']}/files/{source['file_id']}/pages/{n}/image" if source else None
        sections.append({'page':n,'text':clean_page(pages[n]),'confirmed_blank':p.get('page_kind')=='blank','image_url':url})
    return {'id':key,'title':doc['title'],'page':requested,'total':max(pages),'previous':previous,'next':following,'sections':sections,'char_count':len(doc['text'])}

def search(app,key,body):
    doc=app.require('documents',key);query=str(body.get('query','')).strip()[:100];needle=re.sub(r'\s','',query)
    if not needle:raise app.uploads.error('请输入要查找的关键词。')
    results=[];seen=set();document_pages=file_pages.split_pages(doc['text']) or {1:doc['text']}
    for chunk in doc['chunks']:
        text=chunk['text'];positions=[i for i,c in enumerate(text) if not c.isspace()];flat=''.join(text[i] for i in positions);at=flat.find(needle)
        if at<0:continue
        refs=chunk.get('pages') or [int(n) for n in re.findall(r'\d+',str(chunk.get('page','')))[:1]] or [1]
        direct=next((n for n in refs if needle in re.sub(r'\s','',document_pages.get(n,''))),None)
        page=direct or refs[0]
        if page in seen:continue
        seen.add(page);offset=positions[at];results.append({'page':page,'label':f'[第 {direct} 页]' if direct else chunk.get('page',''),'text':text[max(0,offset-80):offset+250]})
        if len(results)>=20:break
    return {'query':query,'results':results,'limited':len(results)==20}
