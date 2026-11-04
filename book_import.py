"""Page-aware book reconstruction, chapter answer keys and shared materials."""
import re
import bisect
import hashlib
from difflib import SequenceMatcher

HEADING=r'(?:第[一二三四五六七八九十百\d]+[篇章练][^\n]*|练习题[一二三四五六七八九十百\d]+[^\n]*|专项刷题[一二三四五六七八九十百\d]+[^\n]*|练习\s*\d+[^\n]*|刷题\s*\d+[^\n]*|题本[一二三四五六七八九十百\d]+[^\n]*)'
QSTART=r'(?m)^[ \t]*(?:[【\[](?:例题|练习|题目)\s*(\d+)[】\]]|(?:(?:第\s*)?(\d+)\s*[.、．）)]))\s*'
KEY_RANGE=r'(\d+)\s*(?:[-~～—–至]\s*(\d+))?\s*[:：]\s*([A-Da-d\s]+)'

def title_key(title):
    return re.sub(r'[\s:：&（）()\[\]【】、，,.。·①②③④⑤⑥⑦⑧⑨⑩]','',title).strip()

def clean_page(text):
    lines=re.sub(r'(?m)^\s*#{1,5}\s*','',text.replace('\r','').replace('**','')).splitlines()
    lines=[s for s in lines if not re.fullmatch(r'\s*(?:超格学员专用|功崇惟志，业广惟勤。|每一个成功的背后.*|公考高照讲数资祝小可爱.*)\s*',s)]
    while lines and not lines[-1].strip():lines.pop()
    if lines and re.fullmatch(r'\s*\d{1,4}\s*',lines[-1]):lines.pop()
    return '\n'.join(lines).strip()

def join_pages(pages):
    parts=[];spans=[];offset=0
    for p in pages:
        t=clean_page(p.get('text',''))
        spans.append((offset,offset+len(t),p['page']))
        parts.append(t);offset+=len(t)+2
    return '\n\n'.join(parts),spans

def physical_pages(spans,start,end):
    return [n for a,b,n in spans if b>start and a<end and b>a]

def reading_spans(text,spans,start,end):
    """Exact accepted text anchors, used only to locate regions on the original page."""
    return [{'page':n,'text':text[max(start,a):min(end,b)].strip()}
            for a,b,n in spans if b>start and a<end and text[max(start,a):min(end,b)].strip()]

def answer_sections(pages):
    """Keep every occurrence tied to its chapter; never shift a malformed range."""
    text,_=join_pages(pages);heads=list(re.finditer('(?m)^'+HEADING,text))
    sections=[]
    if not heads:heads=[None]
    for i,h in enumerate(heads):
        start=h.start() if h else 0;end=heads[i+1].start() if i+1<len(heads) and heads[i+1] else len(text)
        body=text[start:end];answers={};issues=[];ambiguities={}
        for m in re.finditer(KEY_RANGE,body):
            first=int(m[1]);last=int(m[2] or m[1]);values=re.sub(r'\s','',m[3]).upper()
            if last<first or last-first+1!=len(values):issues.append('答案区间长度不符：'+m[0].strip());continue
            for n,value in zip(range(first,last+1),values):
                if n in answers and answers[n]!=value:issues.append('同一题号答案冲突：'+str(n))
                else:answers[n]=value
            alternative=re.match(r'\s*[（(]\s*([A-D])\s*[）)]',body[m.end():])
            if alternative:ambiguities[last]=values[-1]+'/'+alternative[1]
        if answers:sections.append({'title':h[0].strip() if h else '参考答案','answers':answers,'issues':issues,'ambiguities':ambiguities})
    return sections

def split_book(pages):
    total=len(pages);key_at=None
    for i,p in enumerate(pages):
        t=clean_page(p.get('text',''))
        if i>=1 and re.search(r'(?m)^(?:参考答案|答案对照表|答案及解析|答案速查|答案汇总)',t) and (re.search(KEY_RANGE,t) or p.get('page_kind')=='answer_key'):key_at=i;break
    # Covers and contents are not questions. Preserve them in the original page store.
    first=next((i for i,p in enumerate(pages) if i>=1 and (re.search(QSTART,clean_page(p.get('text',''))) or re.search(r'(?m)^训练[一二三四五六七八九十百\d]+',clean_page(p.get('text','')))) and not ('目录' in p.get('text','')[:20])),0)
    passage=next((i for i,p in enumerate(pages[:first]) if i>=1 and re.search(r'(?m)^[^\n]{0,12}根据[^\n]{0,25}(?:资料|材料)[^\n]{0,35}(?:完成|回答)[^\n]{0,20}题',clean_page(p.get('text',''))) and '目录' not in p.get('text','')[:20]),first)
    first=min(first,passage)
    return pages[first:key_at],pages[key_at:] if key_at is not None else []

def match_key(title,sections,index):
    if not sections:return None
    k=title_key(title)
    scores=[SequenceMatcher(None,k,title_key(s['title'])).ratio() for s in sections]
    n=max(range(len(scores)),key=scores.__getitem__)
    if scores[n]>.62:return sections[n]
    return sections[index] if index<len(sections) else None

def split_material_tail(value):
    # A new shared passage often follows the last D option before the next Q1/6/11.
    m=re.search(r'\n(?=(?:根据(?:下列|以下|所给|下述)|[一二三四五六七八九十]+[、．]|[（(][一二三四五六七八九十]+[）)]|20\d{2}年.{8}|\d{1,2}月.{12}))',value)
    if m:return value[:m.start()].strip(),value[m.start():].strip()
    # Model-verified pages keep paragraph breaks, which disambiguate the passage.
    m=re.search(r'\n\s*\n',value)
    if not m and len(value)>250:m=re.search(r'[。？！]\s*\n',value)
    return (value[:m.start()].strip(),value[m.start():].strip()) if m else (value.strip(),'')

def parse_objective(pages,name=''):
    content,key_pages=split_book(pages);keys=answer_sections(key_pages)
    text,spans=join_pages(content);heads=list(re.finditer('(?m)^'+HEADING,text));matches=list(re.finditer(QSTART,text))
    # Numbered labels inside statistical tables are not question boundaries.
    if '【例题' in text:matches=[m for m in matches if m[1]]
    else:
        limit=max((max(s['answers']) for s in keys),default=1000)
        matches=[m for m in matches if 1<=int(m[1] or m[2])<=limit and not ('资料分析' in name and re.match(r'\d',text[m.end():]) and not re.search(r'[\u3400-\u9fff]',text[m.end():].split('\n',1)[0]))]
        if '资料分析' in name:
            matches=[m for i,m in enumerate(matches) if re.search(r'(?m)(?:^|\s)[A-D][.、．):：]|^[A-D]\s*$',text[m.end():matches[i+1].start() if i+1<len(matches) else len(text)])]
        matches=[m for m in matches if not re.match(r'\d',text[m.end():]) or re.search(r'[\u3400-\u9fff]|[,，、]',text[m.end():].split('\n',1)[0])]
        matches=[m for m in matches if not (m[0].rstrip().endswith('、') and re.match(r'\d+[、，,]',text[m.end():]))]
        matches=[m for m in matches if not any(abs(m.start()-a)<3 and a>0 and text[max(0,a-4):a].strip()[-1:] not in '。！？:：;；' and re.match(r'\d+\.\d+(?:米|%|％|万|亿|元)[。；，]',text[m.start():]) for a,b,n in spans)]
        matches=[m for m in matches if not (text[:m.start()].rstrip()[-1:] in '宽高长为约径是于达' and re.match(r'\d+\.\d+(?:米|%|％|万|亿|元)[。；，]',text[m.start():]))]
    rows=[];sections_seen=[];last_section='';last_num=0;section_index=-1;shared={};pending_material='';last_end=0
    for i,m in enumerate(matches):
        number=int(m[1] or m[2]);end=matches[i+1].start() if i+1<len(matches) else len(text)
        preceding=[h for h in heads if h.start()<m.start()]
        section=preceding[-1][0].strip() if preceding else '题目'
        # A chapter heading between this question and the next one belongs to neither stem nor D.
        next_head=next((h for h in heads if m.end()<h.start()<end),None)
        if next_head:end=next_head.start()
        if section!=last_section:
            section_index+=1;sections_seen.append(section);last_section=section;shared={};pending_material=''
        last_num=number
        raw_body=text[m.end():end];body_start=m.end()+len(raw_body)-len(raw_body.lstrip())
        body=raw_body.strip();inline=re.search(r'(?m)^[ \t]*(?:参考答案|正确答案|答案)\s*[:：]\s*([A-Da-d])\b',body)
        inline_explanation=re.search(r'(?m)^[ \t]*(?:参考解析|解析)\s*[:：]\s*([\s\S]*)',body)
        body_end=body_start+inline.start() if inline else end
        if inline:body=body[:inline.start()].rstrip()
        opts=list(re.finditer(r'(?m)(?:^|\s+)([A-D])[.、．）):：][ \t]*',body))
        opts=[o for o in opts if not ('、' in o[0] and re.match('[A-D]',body[o.end():]))]
        # A wrapped exam label such as “事业\nC）” is not an answer option.
        first_a=next((j for j,o in enumerate(opts) if o[1]=='A'),None)
        if first_a is not None:opts=opts[first_a:]
        # Figure choices are often printed as bare A B C D labels.
        if len({o[1] for o in opts})<4:
            bare=list(re.finditer(r'(?m)^[ \t]*([A-D])[ \t]*(?=\n|$)',body))
            if len({o[1] for o in bare})==4:opts=bare
        options={o[1]:body[o.end():opts[j+1].start() if j+1<len(opts) else len(body)].strip() for j,o in enumerate(opts)}
        stem=body[:opts[0].start()].strip() if opts else body
        if not stem:continue
        tail=''
        if 'D' in options:options['D'],tail=split_material_tail(options['D'])
        question_end=body_start+body.rfind(tail) if tail else body_end
        key=match_key(section,keys,section_index);answer=key['answers'].get(number) if key else None
        if answer is None and inline:answer=inline[1].upper()
        group=(number-1)//5 if '资料分析' in name or '篇章阅读' in section else None
        prefix=text[last_end:m.start()].strip() if m.start()>=last_end else ''
        if group is not None and group not in shared:
            material=(pending_material or prefix).strip()
            material=re.sub('(?m)^'+HEADING+r'\s*','',material).strip()
            marks=list(re.finditer(r'(?m)^[^\n]{0,12}根据[^\n]{0,25}(?:资料|材料)[^\n]{0,35}(?:完成|回答)[^\n]{0,20}题[。．.]?',text[:m.start()]))
            material_start=max(0,m.start()-len(material)-3)
            if marks:
                mark=marks[-1]
                # Only a heading for this five-question set can supply its passage.
                numbers=re.findall(r'\d+',mark[0])
                if numbers and int(numbers[0])==group*5+1:
                    material=text[mark.end():m.start()].strip();material_start=mark.end()
            shared[group]={'text':material,'start':material_start,'end':m.start()}
        material=shared[group]['text'] if group is not None else ''
        material_start=shared[group]['start'] if group is not None else m.start()
        material_end=shared[group]['end'] if group is not None else m.start()
        question_start=m.start()
        independent=bool('资料分析' in name and m[1])
        if independent:
            # Example collections have a fresh passage for EVERY question.
            ask=re.search(r'(?m)^\s*问\s*[:：]',stem)
            if ask:
                material=stem[:ask.start()].strip();material_start=body_start;material_end=body_start+ask.start()
                exam_label=re.match(r'^[（(][^）)]{1,80}[）)]\s*\n',material)
                if exam_label:
                    material=material[exam_label.end():].strip();material_start+=exam_label.end()
                question_start=body_start+ask.start();stem=stem[ask.end():].strip()
            else:material='';material_start=material_end=question_start
        source=physical_pages(spans,question_start,question_end)
        material_pages=physical_pages(spans,material_start,material_end) if material else []
        row={'stem':stem,'type':'single','options':{k:v or '图中'+k for k,v in options.items()},'answer':[answer] if answer else [],
             'module':module_for(name),'subtype':section,'knowledge_points':[re.sub(r'^(?:第[一二三四五六七八九十百\d]+[篇章练][：:]?|练习\s*\d+|刷题\s*\d+|题本[一二三四五六七八九十]+)','',section).strip() or section],
             'source_number':number,'source_section':section,'source_pages':source,'source_page':source[0] if source else 1,
             'material':material,'material_pages':material_pages,'group_id':hashlib.sha256((name+section+str(number if independent else group)).encode()).hexdigest()[:16] if group is not None else '',
             'whole_group':False,'answer_source':{'kind':'book_key','section':key['title'],'number':number,'pages':[p['page'] for p in key_pages]} if answer and key else {}}
        if key and number in key.get('ambiguities',{}):row['answer_ambiguity']='原书答案表同时标注 '+key['ambiguities'][number]+'，保留待核对，不参与计分抽题。'
        if inline and not key:row['answer_source']={'kind':'inline','number':number,'pages':physical_pages(spans,body_end,end)}
        if inline_explanation:row['explanation']=inline_explanation[1].strip()
        if not options:row['options']={k:'图中'+k for k in 'ABCD'};row['requires_image']=True
        if re.search(r'图形|问号处|三视图|折叠|平面图|如下图|如图所示|左边给定',stem) or any(v=='图中'+k for k,v in row['options'].items()):row['requires_image']=True
        row['reading_source']={'version':1,'material':reading_spans(text,spans,material_start,material_end) if material else [],
                               'question':reading_spans(text,spans,question_start,question_end),
                               'presentation':'figure' if row.get('requires_image') and '资料分析' not in name else 'material'}
        rows.append(row);pending_material=tail;last_end=end
    return rows,{'sections':sections_seen,'key_sections':keys,'key_pages':[p['page'] for p in key_pages],'content_pages':[p['page'] for p in content]}

def module_for(name):
    for a,b in [('言语','言语理解'),('数量','数量关系'),('资料','资料分析'),('判断推理','判断推理'),('常识','常识判断'),('申论','申论')]:
        if a in name:return b
    return '未分类'

def subjective_blocks(pages):
    content,_=split_book(pages);text,spans=join_pages(content)
    starts=list(re.finditer(r'(?m)^训练[一二三四五六七八九十百\d]+[^\n]*',text));blocks=[]
    for i,m in enumerate(starts):
        end=starts[i+1].start() if i+1<len(starts) else len(text)
        block=text[m.end():end].strip()
        # Exclude a following chapter title from the preceding exercise.
        h=re.search(r'(?m)^第[一二三四五六七八九十百]+章',block)
        if h:block=block[:h.start()].strip()
        if len(block)>40 and re.search('要求|请|根据|结合',block):blocks.append({'title':m[0],'text':block,'pages':physical_pages(spans,m.start(),end)})
    return blocks

def document_chunks(text):
    from file_pages import split_pages
    pages=split_pages(text)
    if not pages:return [{'id':i//1000+1,'page':'','pages':[],'text':text[i:i+1200].strip()} for i in range(0,len(text),1000) if text[i:i+1200].strip()]
    joined='';spans=[]
    for n,raw in pages.items():
        body=clean_page(raw)
        if not body:continue
        continuation=bool(joined and joined[-1] not in '。！？：；.!?:;' and not re.match(r'(?:第.+[章节]|\d+[.、]|[一二三四五六七八九十]+[、．]|[A-D][.、])',body))
        if joined:joined+=' ' if continuation and joined[-1].isascii() else '' if continuation else '\n\n'
        start=len(joined);joined+=body;spans.append((start,len(joined),n))
    chunks=[]
    for offset in range(0,len(joined),1000):
        body=joined[offset:offset+1200].strip();refs=physical_pages(spans,offset,offset+1200)
        if body:chunks.append({'id':len(chunks)+1,'page':'[第 '+('—'.join(map(str,[refs[0],refs[-1]])) if len(refs)>1 else str(refs[0]))+' 页]','pages':refs,'text':body})
    return chunks
