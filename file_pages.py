"""Persist page text independently, so individual pages can be repaired."""
import hashlib
import io
import json
import re
from pathlib import Path

import local_ocr


def page_path(source, page, kind='page-text'):
    return source.with_suffix('.'+kind)/f'page-{page:05d}.json'


def write_page(source, page, result, kind='page-text'):
    if not isinstance(source, Path):
        return
    path=page_path(source,page,kind);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(result,ensure_ascii=False),'utf-8');temp.replace(path)


def override(source, page):
    if isinstance(source,Path):
        path=page_path(source,page,'page-overrides')
        if path.is_file():return json.loads(path.read_text('utf-8'))
    return None


def split_pages(text):
    matches=list(re.finditer(r'(?m)^\[第 (\d+) 页\][ \t]*\n',text))
    return {int(m[1]):text[m.end():matches[i+1].start() if i+1<len(matches) else len(text)] for i,m in enumerate(matches)}


def replace_pages(text, replacements):
    matches=list(re.finditer(r'(?m)^\[第 (\d+) 页\][ \t]*\n',text))
    for i in range(len(matches)-1,-1,-1):
        m=matches[i]
        if int(m[1]) in replacements:
            end=matches[i+1].start() if i+1<len(matches) else len(text)
            text=text[:m.end()]+replacements[int(m[1])].rstrip()+'\n\n'+text[end:]
    return text


class FilePages:
    def __init__(self,manager):self.m=manager;self.app=manager.app;self.error=manager.error

    def source(self,bid,fid):
        _,item=self.m.require(bid,fid)
        if item['status'] in ('deleted','deleting'):raise self.error('请先恢复已删除的任务。',409)
        source=self.m.path_for(bid,fid)
        if not source.is_file():raise self.error('上传副本不存在，请重新上传。',409)
        return source,item

    def count(self,bid,fid):
        source,item=self.source(bid,fid);ext=Path(item['name']).suffix.lower()
        if ext=='.pdf':
            from pypdf import PdfReader
            with source.open('rb') as stream:
                reader=PdfReader(stream)
                if reader.is_encrypted and not reader.decrypt(''):raise self.error('请先解除 PDF 打开密码。')
                count=len(reader.pages)
        elif ext in local_ocr.IMAGE_EXTENSIONS:
            from PIL import Image
            with Image.open(source) as image:count=getattr(image,'n_frames',1)
        else:raise self.error('逐页辅助目前支持 PDF 和图片。')
        if not 1<=count<=5000:raise self.error('文件页数超出 1—5000 页范围。')
        return count

    def read(self,bid,fid,page,doc_pages=None,source=None):
        if source is None:source,item=self.source(bid,fid)
        for kind in ('page-overrides','page-text','ocr-cache'):
            path=page_path(source,page,kind)
            if path.is_file():
                result=json.loads(path.read_text('utf-8'));return {**result,'page':page,'chars':len(result.get('text','').strip())}
        if doc_pages is None:
            _,item=self.m.require(bid,fid)
            doc=self.app.store.get('documents',item.get('document_id',''))
            doc_pages=split_pages(doc['text']) if doc else {}
        if page in doc_pages:return {'page':page,'method':'native','text':doc_pages[page],'chars':len(doc_pages[page].strip())}
        return {'page':page,'method':'unknown','text':'','chars':0,'error':'该页尚无可用的逐页结果'}

    def catalog(self,bid,fid):
        total=self.count(bid,fid);source,item=self.source(bid,fid)
        doc=self.app.store.get('documents',item.get('document_id',''))
        doc_pages=split_pages(doc['text']) if doc else {}
        infos={p['page']:p for p in item.get('ocr',{}).get('pages',[])}
        rows=[]
        for n in range(1,total+1):
            result=self.read(bid,fid,n,doc_pages,source)
            info={**infos.get(n,{}),**result};text=info.pop('text','')
            info.update(text_preview=text[:240],problem=info.get('page_kind')!='blank' and (not info['chars'] or bool(info.get('error')) or bool(info.get('low_confidence_lines'))))
            rows.append(info)
        cfg=self.app.config();model=cfg.get('vision_model') or cfg.get('model')
        return {'file_id':fid,'name':item['name'],'purpose':item['purpose'],'status':item['status'], 'pages':rows,'total':total,
                'model':model,'provider':cfg.get('base_url',''),'has_model':bool(model and cfg.get('base_url')),
                'can_apply':item['status'] not in ('queued','parsing')}

    def image(self,bid,fid,page):
        total=self.count(bid,fid)
        if isinstance(page,bool) or not isinstance(page,int) or not 1<=page<=total:raise self.error('页码超出文件范围。')
        source,item=self.source(bid,fid)
        if Path(item['name']).suffix.lower()=='.pdf':
            renderer=local_ocr.PdfRenderer(source,self.error)
            try:return renderer.image(page-1)
            finally:renderer.close()
        from PIL import Image,ImageOps
        with Image.open(source) as image:
            image.seek(page-1)
            if image.width*image.height>local_ocr.MAX_IMAGE_PIXELS:raise self.error('单张图片过大，请先缩小。')
            result=ImageOps.exif_transpose(image).convert('RGB');result.thumbnail((3200,3200));return result

    def asset(self,image,bbox=None):
        if bbox is not None:
            if not isinstance(bbox,list) or len(bbox)!=4 or any(isinstance(n,bool) or not isinstance(n,(int,float)) for n in bbox):raise self.error('裁剪范围应包含左、上、右、下四个数值。')
            left,top,right,bottom=bbox
            if not (0<=left<right<=1000 and 0<=top<bottom<=1000):raise self.error('裁剪范围需在 0—100% 内，右下边界应大于左上边界。')
            bounds=(round(left*image.width/1000),round(top*image.height/1000),round(right*image.width/1000),round(bottom*image.height/1000))
            if bounds[2]-bounds[0]<2 or bounds[3]-bounds[1]<2:raise self.error('裁剪范围过小，请保留完整题干、图形及选项。')
            cropped=image.crop(bounds)
        else:cropped=image.copy()
        try:
            buf=io.BytesIO();cropped.save(buf,'JPEG',quality=92);data=buf.getvalue()
        finally:cropped.close()
        key='vis_'+hashlib.sha256(data).hexdigest()[:32]
        folder=self.app.store.folder/'visuals';folder.mkdir(exist_ok=True)
        path=folder/(key+'.jpg')
        if not path.exists():path.write_bytes(data)
        return {'id':key,'mime':'image/jpeg'}

    def asset_path(self,key):
        if not re.fullmatch(r'vis_[a-f0-9]{32}',key):raise self.error('图片编号无效。',404)
        path=self.app.store.folder/'visuals'/(key+'.jpg')
        if not path.is_file():raise self.error('图片不存在。',404)
        return path
