"""Offline Chinese/English OCR and page-at-a-time PDF rendering."""
from __future__ import annotations

import importlib.util
import json
import math
import re
import threading
from pathlib import Path

ENGINE_VERSION = 'rapidocr-3.10.0-ppocrv6-200dpi-v1'
MODEL_FILES = {'Det': 'PP-OCRv6_det_small.onnx', 'Cls': 'ch_ppocr_mobile_v2.0_cls_mobile.onnx',
               'Rec': 'PP-OCRv6_rec_small.onnx'}
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff'}
MAX_IMAGE_PIXELS = 40_000_000
_engine = None
_lock = threading.RLock()
PDF_LOCK = threading.RLock()  # PDFium is not thread safe, even across documents.


def status():
    required = ('rapidocr', 'onnxruntime', 'pypdfium2', 'PIL')
    missing = [name for name in required if importlib.util.find_spec(name) is None]
    spec = importlib.util.find_spec('rapidocr')
    folder = Path(spec.origin).parent/'models' if spec and spec.origin else None
    models = bool(folder and all((folder/name).is_file() for name in MODEL_FILES.values()))
    ready = not missing and models
    return {'available': ready, 'engine': 'RapidOCR / PP-OCRv6', 'local': True, 'default_mode': 'auto',
            'languages': ['简体中文', '英文'], 'loaded': _engine is not None,
            'message': '本地 OCR 已就绪，扫描页自动识别。' if ready else '本地 OCR 依赖或模型未就绪，请运行安装依赖脚本。'}


def get_engine(error):
    global _engine
    with _lock:
        if _engine is None:
            if not status()['available']:
                raise error('本地 OCR 引擎未就绪，请先运行项目中的安装依赖脚本，再重启知序。')
            from rapidocr import RapidOCR
            spec = importlib.util.find_spec('rapidocr')
            folder = Path(spec.origin).parent/'models'
            # Explicit local model paths prevent network downloads during imports.
            params = {f'{kind}.model_path': str(folder/name) for kind, name in MODEL_FILES.items()}
            params.update({'Global.log_level': 'error', 'Global.text_score': .4,
                           'Global.max_side_len': 3200, 'Det.limit_side_len': 1600, 'Det.limit_type': 'max',
                           'EngineConfig.onnxruntime.intra_op_num_threads': 2,
                           'EngineConfig.onnxruntime.inter_op_num_threads': 1})
            _engine = RapidOCR(params=params)
        return _engine


def meaningful(text):
    return len(re.findall(r'[\w\u3400-\u9fff]', text, flags=re.UNICODE))


def needs_ocr(page, text):
    count = meaningful(text)
    if count < 20 or text.count('\ufffd') > max(3, len(text)*.1):
        return True
    # Scans sometimes have a short selectable watermark/header on top of the image.
    if count < 250:
        try:
            resources = page.get('/Resources', {})
            resources = resources.get_object() if hasattr(resources, 'get_object') else resources
            objects = resources.get('/XObject', {})
            objects = objects.get_object() if hasattr(objects, 'get_object') else objects
            for ref in objects.values():
                obj = ref.get_object()
                if obj.get('/Subtype') == '/Image' and obj.get('/Width', 0) >= 500 and obj.get('/Height', 0) >= 500:
                    return True
        except (AttributeError, TypeError, KeyError):
            pass
    return False


def recognize(image, error):
    """Keep low-confidence lines visible rather than inventing corrections."""
    import numpy as np
    with _lock:
        engine = get_engine(error)
        result = engine(np.asarray(image.convert('RGB')))
        texts = list(result.txts or [])
        scores = [float(x) for x in (result.scores or [])]
        boxes = result.boxes
        layout_size = image.size
        # Classification handles upside-down lines; sparse sideways images get a rotation retry.
        if sum(meaningful(t) for t in texts) < 10:
            best = sum(meaningful(t)*s for t, s in zip(texts, scores))
            for angle in (90, 270):
                rotated = image.rotate(angle, expand=True)
                try:
                    other = engine(np.asarray(rotated.convert('RGB')))
                finally:
                    rotated.close()
                candidate = sum(meaningful(t)*float(s) for t, s in zip(other.txts or [], other.scores or []))
                if candidate > best:
                    texts, scores, best = list(other.txts or []), [float(s) for s in (other.scores or [])], candidate
                    boxes=other.boxes.copy() if other.boxes is not None else None
                    if boxes is not None:
                        x,y=boxes[:,:,0].copy(),boxes[:,:,1].copy()
                        boxes[:,:,0],boxes[:,:,1]=(image.width-y,x) if angle==90 else (y,image.height-x)
        return {'text': '\n'.join(texts), 'lines': len(texts),
                'layout_size':list(layout_size),
                'layout':[{'text':str(t),'box':[[round(float(x),2),round(float(y),2)] for x,y in b]} for t,b in zip(texts,boxes)] if boxes is not None else [],
                'confidence': round(sum(scores)/len(scores), 4) if scores else None,
                'low_confidence_lines': sum(s < .8 for s in scores), 'method': 'ocr'}


def cached_recognize(image_factory, cache_dir, page_number, error):
    cache_file = cache_dir/f'page-{page_number:05d}.json' if cache_dir else None
    if cache_file and cache_file.is_file():
        try:
            saved = json.loads(cache_file.read_text('utf-8'))
            if saved.get('engine_version') == ENGINE_VERSION and isinstance(saved.get('text'), str):
                return saved
        except (ValueError, OSError):
            pass
    image = image_factory()
    try:
        result = recognize(image, error)
    finally:
        image.close()
    result['engine_version'] = ENGINE_VERSION
    if cache_file:
        cache_dir.mkdir(parents=True, exist_ok=True)
        temp = cache_file.with_suffix('.tmp')
        temp.write_text(json.dumps(result, ensure_ascii=False), 'utf-8')
        temp.replace(cache_file)
    return result


class PdfRenderer:
    def __init__(self, source, error):
        self.source, self.error, self.doc = source, error, None

    def image(self, index):
        try:
            import pypdfium2 as pdfium
        except ImportError:
            raise self.error('OCR 需要 PDF 渲染依赖，请运行安装依赖脚本。')
        with PDF_LOCK:
            if self.doc is None:
                if not isinstance(self.source, Path):
                    self.source.seek(0)
                self.doc = pdfium.PdfDocument(str(self.source) if isinstance(self.source, Path) else self.source)
            page = self.doc[index]
            try:
                width, height = page.get_size()
                scale = min(200/72, 3200/max(width, height), math.sqrt(12_000_000/(width*height)))
                bitmap = page.render(scale=scale)
                try:
                    return bitmap.to_pil().convert('RGB')
                finally:
                    bitmap.close()
            finally:
                page.close()

    def close(self):
        with PDF_LOCK:
            if self.doc is not None:
                self.doc.close()
                self.doc = None


def read_images(source, error, progress, cache_dir, max_pages):
    from PIL import Image, ImageOps
    image = Image.open(source)
    try:
        total = getattr(image, 'n_frames', 1)
        if total > max_pages:
            raise error('图片文件超过 5000 帧，请拆分后导入。')
        for index in range(total):
            progress(index, total, f'OCR 识别图片第 {index+1}/{total} 页')
            image.seek(index)
            if image.width*image.height > MAX_IMAGE_PIXELS:
                raise error('单张图片超过 4000 万像素，请缩小图片后导入。')
            def factory():
                oriented = ImageOps.exif_transpose(image)
                result = oriented.convert('RGB')
                if oriented is not image:
                    oriented.close()
                result.thumbnail((3200, 3200))
                return result
            from file_pages import override
            result = override(source,index+1) or cached_recognize(factory, cache_dir, index+1, error)
            yield index+1, total, result
    finally:
        image.close()


def report(pages, mode):
    ocr = [p for p in pages if p['method'] == 'ocr']
    empty = [p['page'] for p in pages if not p['chars'] and p.get('page_kind')!='blank']
    low = sum(p.get('low_confidence_lines', 0) for p in ocr)
    return {'engine': 'RapidOCR / PP-OCRv6', 'local': True, 'mode': mode,
            'total_pages': len(pages), 'ocr_pages': len(ocr), 'native_pages': sum(p['method']=='native' for p in pages),
            'model_pages': sum(p['method']=='model' for p in pages), 'blank_pages':[p['page'] for p in pages if p.get('page_kind')=='blank'], 'failed_pages':[p['page'] for p in pages if p['method'] in ('failed','unknown')],
            'low_confidence_lines': low, 'empty_pages': empty,
            'warnings': (['OCR 包含低置信度文字，请对照原件核对。'] if low else [])+
                        (['以下页未识别到文字，可能为空白、图表或不清晰：'+', '.join(map(str, empty[:50]))] if empty else []),
            'pages': pages}
