"""Local, cached page layout and precise material/question crops for reading."""
import hashlib
import json
import threading
import unicodedata
import re
import uuid
import base64
from difflib import SequenceMatcher

import file_pages
import local_ocr

VERSION = 4
_lock = threading.RLock()


def save_cache(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False),'utf-8');temp.replace(path)


def normalized(text):
    return ''.join(c.lower() for c in unicodedata.normalize('NFKC', text) if c.isalnum())


def page_layout(helper, bid, fid, page, source=None, renderer=None):
    if source is None:source, _ = helper.source(bid, fid)
    path = file_pages.page_path(source, page, 'page-layout')
    with _lock:
        if path.is_file():return json.loads(path.read_text('utf-8'))
        # New imports already include coordinates. Accepted text remains untouched.
        original = helper.read(bid, fid, page, source=source)
        cached=file_pages.page_path(source,page,'ocr-cache')
        if not original.get('layout') and cached.is_file():
            raw=json.loads(cached.read_text('utf-8'))
            if raw.get('layout') and raw.get('layout_size'):original=raw
        if original.get('layout') and original.get('layout_size'):
            result = {k:original[k] for k in ('layout','layout_size')}
        else:
            image = renderer.image(page-1) if renderer else helper.image(bid, fid, page)
            try:
                read = local_ocr.recognize(image, helper.error)
                result = {k:read[k] for k in ('layout','layout_size')}
            finally:image.close()
        file_pages.write_page(source, page, result, 'page-layout')
        return result


def locate_region(accepted, region, layout, figure=False):
    """Align the full accepted page first so repeated table values stay in place."""
    page_text, needle = normalized(accepted), normalized(region)
    start = page_text.find(needle)
    if not needle or start < 0:raise ValueError('该区域无法与已确认的页面文字对应。')
    end = start + len(needle)
    tokens = layout['layout'];recognized = '';owners = []
    for i,line in enumerate(tokens):
        text = normalized(line['text']);recognized += text;owners.extend([i]*len(text))
    indexes = set();matched = 0;before=[];after=[]
    blocks=SequenceMatcher(None,page_text,recognized,autojunk=False).get_matching_blocks()
    for block in blocks:
        if not block.size:continue
        if block.a < start:
            last=min(start,block.a+block.size)-1
            before.append((last,owners[block.b+last-block.a]))
        if block.a+block.size > end:
            first=max(end,block.a)
            after.append((first,owners[block.b+first-block.a]))
        left,right = max(start,block.a),min(end,block.a+block.size)
        if left < right:
            matched += right-left
            indexes.update(owners[block.b+left-block.a:block.b+right-block.a])
    coverage = matched/len(needle)
    before=[p for p in before if p[1] not in indexes];after=[p for p in after if p[1] not in indexes]
    previous=tokens[max(before)[1]] if before else None
    following=tokens[min(after)[1]] if after else None
    width,height = layout['layout_size']
    if previous is None and start==0:
        headers=[l for l in tokens if '超格学员专用' in l['text'] and max(y for x,y in l['box'])<height*.2]
        previous=max(headers,key=lambda l:max(y for x,y in l['box'])) if headers else {'box':[[0,0]]}
    if following is None and end==len(page_text):
        footers=[l for l in tokens if re.fullmatch(r'\s*\d{1,4}\s*',l['text']) and min(y for x,y in l['box'])>height*.9]
        following=min(footers,key=lambda l:min(y for x,y in l['box'])) if footers else {'box':[[0,height]]}
    anchored=.1<=coverage<.8 and previous is not None and following is not None
    if (coverage < .55 and not anchored and not figure) or not indexes:raise ValueError('页面定位置信度不足，请查看原页核对。')
    selected = [tokens[i] for i in sorted(indexes)]
    top = min(y for l in selected for x,y in l['box'])
    bottom = max(y for l in selected for x,y in l['box'])
    if figure:
        # A figure has meaningful pixels between text anchors. Its bottom cannot
        # be inferred from the last successfully recognized glyph or choice label.
        if following is None:raise ValueError('未找到图形题的下边界，请查看原页核对。')
        lower=min(y for x,y in following['box'])
        next_text=page_text[end:end+100]
        # A line can be detected at the correct position while its transcription
        # is wholly garbled. Keep that line with its question, using its geometry.
        wide=[l for i,l in enumerate(tokens) if i not in indexes and
              max(x for x,y in l['box'])-min(x for x,y in l['box'])>width*.5]
        if previous is not None:
            upper=max(y for x,y in previous['box'])
            own_header=[min(y for x,y in l['box']) for l in wide if upper+2<min(y for x,y in l['box'])<top]
            if own_header:top=min(top,min(own_header))
        if next_text and not next_text.isdigit():
            next_header=[min(y for x,y in l['box']) for l in wide if bottom+2<min(y for x,y in l['box'])<lower]
            if next_header:lower=min(lower,min(next_header))
        for line in tokens:
            if not re.match(r'^\s*(?:[【\[]例题\s*\d+[】\]]|\d+\s*[.、．）)])\s*[【（(\u3400-\u9fff]',line['text']):continue
            candidate=normalized(line['text'])
            if min(y for x,y in line['box'])>top+height*.02 and SequenceMatcher(None,candidate[:45],next_text[:45],autojunk=False).ratio()>.65:
                lower=min(lower,min(y for x,y in line['box']))
        if lower<=top:raise ValueError('图形题边界顺序不明确，请查看原页核对。')
        top=max(0,top-height*.008);bottom=lower-height*.005
        return {'bbox':[75,round(top/height*1000,2),935,round(bottom/height*1000,2)],
                'coverage':round(coverage,3),'method':'figure_boundaries'}
    if anchored:
        # Garbled OCR and model-transcribed charts have different internal order.
        # Their neighboring, confirmed text still gives exact vertical boundaries.
        upper=max(y for x,y in previous['box']);lower=min(y for x,y in following['box'])
        if upper < lower and upper <= top+height*.03 and lower >= bottom-height*.03:
            top=upper+height*.003;bottom=lower-height*.003
        elif coverage < .55:raise ValueError('页面边界未能可靠对应，请查看原页核对。')
    # Include table rules, chart lines and whitespace, stopping before adjacent text.
    above = [max(y for x,y in l['box']) for i,l in enumerate(tokens) if i not in indexes and max(y for x,y in l['box']) < top-2]
    below = [min(y for x,y in l['box']) for i,l in enumerate(tokens) if i not in indexes and min(y for x,y in l['box']) > bottom+2]
    if not anchored:
        top -= min(height*.012,(top-max(above))/2 if above else height*.012)
        bottom += min(height*.012,(min(below)-bottom)/2 if below else height*.012)
    # Keep full column width, including sparse graphics, but discard page margins.
    body = [l for l in tokens if top <= sum(y for x,y in l['box'])/len(l['box']) <= bottom]
    left = min(x for l in body for x,y in l['box'])-width*.028
    right = max(x for l in body for x,y in l['box'])+width*.028
    bbox = [max(0,round(left/width*1000,2)),max(0,round(top/height*1000,2)),
            min(1000,round(right/width*1000,2)),min(1000,round(bottom/height*1000,2))]
    return {'bbox':bbox,'coverage':round(coverage,3),'method':'neighbor_anchors' if anchored else 'text_alignment'}


def region_asset(helper,bid,fid,span,source=None,renderer=None,figure=False):
    if source is None:source,_ = helper.source(bid,fid)
    page = span['page']
    key = hashlib.sha256((str(VERSION)+(':figure-v2' if figure else '')+span['text']).encode()).hexdigest()[:32]
    path = source.with_suffix('.reading-assets')/(f'{page:05d}-'+key+'.json')
    if path.is_file():
        saved=json.loads(path.read_text('utf-8'))
        if (helper.app.store.folder/'visuals'/(saved['id']+'.jpg')).is_file():return saved
    accepted = helper.read(bid,fid,page,source=source)['text']
    layout = page_layout(helper,bid,fid,page,source,renderer)
    bounds = locate_region(accepted,span['text'],layout,figure=figure)
    image = renderer.image(page-1) if renderer else helper.image(bid,fid,page)
    try:
        asset = helper.asset(image,bounds['bbox'])
        w,h = image.size;l,t,r,b = bounds['bbox']
        asset.update(page=page,width=round((r-l)*w/1000),height=round((b-t)*h/1000),**bounds)
    finally:image.close()
    save_cache(path,asset)
    return asset


def reading(app,q,renderer=None):
    helper = app.page_assist.pages
    spec = q.get('reading_source',{});refs = q.get('page_images',[])
    if not spec or not refs:raise helper.error('该题尚无可用的分区阅读信息。',409)
    bid,fid = refs[0]['batch_id'],refs[0]['file_id'];source,_ = helper.source(bid,fid)
    result = {'question_id':q['id'],'material':[],'question':[],'warnings':[]}
    for kind in ('material','question'):
        for span in spec.get(kind,[]):
            try:result[kind].append(region_asset(helper,bid,fid,span,source,renderer,figure=kind=='question' and spec.get('presentation')=='figure'))
            except (ValueError,OSError) as exc:result['warnings'].append({'kind':kind,'page':span['page'],'message':str(exc)})
    if len(result['material'])>1 and not any(w['kind']=='material' for w in result['warnings']):
        combined=continuous_material(helper,bid,fid,result['material'],source,renderer)
        if combined:result['material']=[combined]
    return result


def continuous_material(helper,bid,fid,assets,source,renderer=None):
    """Use one horizontal scale across page breaks, preserving table columns."""
    from PIL import Image
    key=hashlib.sha256(json.dumps([VERSION,assets],sort_keys=True).encode()).hexdigest()[:32]
    path=source.with_suffix('.reading-materials')/(key+'.json')
    if path.is_file():
        saved=json.loads(path.read_text('utf-8'))
        if (helper.app.store.folder/'visuals'/(saved['id']+'.jpg')).is_file():return saved
    left=min(a['bbox'][0] for a in assets);right=max(a['bbox'][2] for a in assets)
    parts=[]
    try:
        for a in assets:
            image=renderer.image(a['page']-1) if renderer else helper.image(bid,fid,a['page'])
            try:
                _,top,_,bottom=a['bbox'];w,h=image.size
                parts.append(image.crop((round(left*w/1000),round(top*h/1000),round(right*w/1000),round(bottom*h/1000))))
            finally:image.close()
        width=max(p.width for p in parts)
        sizes=[(width,round(p.height*width/p.width)) for p in parts]
        height=sum(h for w,h in sizes)
        if height>24000 or width*height>40_000_000:return None
        composite=Image.new('RGB',(width,height),'white');offset=0
        try:
            for part,size in zip(parts,sizes):
                resized=part.resize(size,Image.Resampling.LANCZOS)
                try:composite.paste(resized,(0,offset));offset+=size[1]
                finally:resized.close()
            result=helper.asset(composite)
        finally:composite.close()
        result.update(page=assets[0]['page'],pages=[a['page'] for a in assets],width=width,height=height,
                      segments=assets,coverage=min(a['coverage'] for a in assets),method='continuous_pages')
        save_cache(path,result)
        return result
    finally:
        for p in parts:p.close()


def presentation(app,q):
    """Improve historical display without modifying snapshots or recorded grades."""
    if q.get('reading_source'):return q
    current = app.store.get('questions',q['id'])
    if (current and current.get('reading_source') and current.get('origin_key')
            and current.get('origin_key') == q.get('origin_key')):
        return {**q,'reading_source':current['reading_source'],'reading_stem':current['stem'],
                'reading_material':current['material'],'requires_image':current.get('requires_image',False)}
    return q


def model_images(app,q,limit=6):
    """Only relevant, cropped assets can leave the local app, never full pages."""
    q=presentation(app,q);assets=[]
    if q.get('reading_source') and q.get('page_images'):
        data=reading(app,q)
        if data['warnings']:raise app.uploads.error('本题题图尚未可靠定位，请先核对原页后再使用 AI 分析。',409)
        assets=data['material']+data['question']
    elif q.get('visual'):assets=[q['visual']]
    elif q.get('display_original') or q.get('requires_image'):
        raise app.uploads.error('本题尚无单题裁图，暂不向模型发送整页图片。',409)
    if len(assets)>limit:raise app.uploads.error('本次相关题图较多，请缩小分析范围。',409)
    return ['data:image/jpeg;base64,'+base64.b64encode(app.page_assist.pages.asset_path(a['id']).read_bytes()).decode('ascii') for a in assets]
