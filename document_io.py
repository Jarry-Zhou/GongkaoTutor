"""Read uploaded files from disk without base64 expansion or loading PDF images."""
import base64
import csv
import io
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from file_imports import MAX_FILE_BYTES, MAX_TEXT_CHARS, MAX_PDF_PAGES, MAX_QUESTIONS
import local_ocr
import file_pages


def read_source_file(payload, parse_questions, error, purpose='question_bank'):
    name = str(payload.get('name', '题库.json')).replace('\\', '/').split('/')[-1]
    path = payload.get('_source_path')
    if path is not None:
        if not isinstance(path, Path):
            raise error('内部源文件句柄无效；请通过文件上传入口导入。')
        if path.stat().st_size > MAX_FILE_BYTES:
            raise error('单个文件上限为 500 MB。')
        source = path
    else:
        try:
            data = base64.b64decode(payload.get('data', ''), validate=True)
        except ValueError:
            raise error('文件编码无效。')
        if len(data) > 15 * 1024 * 1024:
            raise error('旧版单请求入口最多 15 MB；请使用批量文件上传入口，支持单文件 500 MB。')
        source = io.BytesIO(data)
    suffix = Path(name).suffix.lower()
    progress = payload.get('_progress') if callable(payload.get('_progress')) else lambda *args: None
    mode = payload.get('ocr_mode', 'auto')
    if mode not in ('auto', 'force', 'off'):
        raise error('OCR 模式无效，请选择自动、全部页面或关闭。')
    cache_dir = source.with_suffix('.ocr-cache') if isinstance(source, Path) else None

    def save_report(pages):
        payload['_ocr_report'] = local_ocr.report(pages, mode)
        if callable(payload.get('_metadata')):
            payload['_metadata'](payload['_ocr_report'])

    def check_text(text):
        if len(text) > MAX_TEXT_CHARS:
            raise error('提取正文超过 2000 万字符，请按章节拆分；不会截断或遗漏内容后入库。')
        return text

    def read_text():
        if isinstance(source, Path):
            with source.open('rb') as stream:
                raw = stream.read(MAX_TEXT_CHARS * 4 + 1)
            if len(raw) > MAX_TEXT_CHARS * 4:
                raise error('文本正文过大，请按章节拆分；PDF 中的图片体积不受这个正文限制。')
        else:
            raw = source.getvalue()
        try:
            return check_text(raw.decode('utf-8-sig'))
        except UnicodeDecodeError:
            try:
                return check_text(raw.decode('gb18030'))
            except UnicodeDecodeError:
                raise error('无法解码文本，请使用 UTF-8、PDF、DOCX 或 XLSX 文件。')

    if suffix in ('.xlsx', '.docx'):
        with zipfile.ZipFile(source) as archive:
            if sum(item.file_size for item in archive.infolist()) > 512 * 1024 * 1024:
                raise error('文档解压后超过 512 MB，请按章节拆分。')
        if not isinstance(source, Path):
            source.seek(0)

    if suffix == '.xlsx':
        try:
            import openpyxl
        except ImportError:
            raise error('缺少 Excel 解析依赖，请运行安装依赖脚本。')
        workbook = openpyxl.load_workbook(source, read_only=True, data_only=True)
        try:
            iterator = workbook.active.iter_rows(values_only=True)
            header = next(iterator, None)
            if not header:
                return name, [], ''
            if purpose == 'document':
                lines = [' | '.join(str(x or '') for x in header)]
                chars = len(lines[0])
                for index, row in enumerate(iterator):
                    line = ' | '.join(str(x if x is not None else '') for x in row)
                    chars += len(line) + 1
                    if chars > MAX_TEXT_CHARS:
                        raise error('表格提取正文超过 2000 万字符，请拆分工作表。')
                    lines.append(line)
                    progress(index+1, max(index+1, workbook.active.max_row or 0), '读取表格')
                return name, [], '\n'.join(lines)
            headers = [str(x or '').strip() for x in header]
            rows = []
            for row in iterator:
                if any(v is not None for v in row):
                    rows.append(dict(zip(headers, row)))
                if len(rows) > MAX_QUESTIONS:
                    raise error('单个题库识别超过 5000 题，请拆分后导入；未截断入库。')
            return name, rows, ''
        finally:
            workbook.close()

    if suffix == '.pdf':
        try:
            from pypdf import PdfReader
        except ImportError:
            raise error('缺少 PDF 解析依赖，请运行安装依赖脚本。')
        stream = source.open('rb') if isinstance(source, Path) else source
        renderer = local_ocr.PdfRenderer(source, error)
        try:
            reader = PdfReader(stream)
            if reader.is_encrypted and not reader.decrypt(''):
                raise error('PDF 有打开密码，请先解除密码后导入。')
            total = len(reader.pages)
            if total > MAX_PDF_PAGES:
                raise error('单份 PDF 超过 5000 页，请按章节拆分。')
            parts, chars, pages = [], 0, []
            for index, page in enumerate(reader.pages):
                progress(index, total, f'检查 PDF 第 {index+1}/{total} 页')
                saved_override = file_pages.override(source,index+1)
                try:
                    native = '' if saved_override else page.extract_text() or ''
                except Exception:
                    if mode == 'off':
                        raise error(f'第 {index+1} 页文字层提取失败，请改用全部页面 OCR。')
                    native = ''
                if saved_override:
                    body=saved_override['text'];info={k:v for k,v in saved_override.items() if k!='text'}
                elif mode != 'off' and (mode == 'force' or local_ocr.needs_ocr(page, native)):
                    progress(index, total, f'OCR 识别 PDF 第 {index+1}/{total} 页')
                    try:
                        result = local_ocr.cached_recognize(lambda: renderer.image(index), cache_dir, index+1, error)
                    except Exception as failure:
                        if callable(payload.get('_check_cancel')):payload['_check_cancel']()
                        if not local_ocr.status()['available']:raise
                        result={'text':'','method':'failed','lines':0,'confidence':None,'low_confidence_lines':0,'error':str(failure)[:400]}
                    body = result['text']
                    info = {k: result[k] for k in ('method', 'lines', 'confidence', 'low_confidence_lines','error') if k in result}
                else:
                    body, info = native, {'method': 'native'}
                pages.append({'page': index+1, 'chars': len(body.strip()), **info})
                file_pages.write_page(source,index+1,{'text':body,**info})
                text = f'\n[第 {index+1} 页]\n' + body
                chars += len(text)
                if chars > MAX_TEXT_CHARS:
                    raise error('PDF 提取正文超过 2000 万字符，请按章节拆分。')
                parts.append(text)
                progress(index+1, total, 'PDF 页面已处理')
            text = '\n'.join(parts)
            save_report(pages)
        finally:
            renderer.close()
            stream.close()
        if not local_ocr.meaningful(re.sub(r'\[第 \d+ 页\]', '', text)):
            raise error('PDF 未识别到可用文字。请检查扫描清晰度或更换 OCR 模式，空白页与纯图形不能生成正文。')
    elif suffix in local_ocr.IMAGE_EXTENSIONS:
        if mode == 'off':
            raise error('图片资料需要 OCR，请在重试时选择自动识别或全部页面 OCR。')
        parts, pages, chars = [], [], 0
        for page_number, total, result in local_ocr.read_images(source, error, progress, cache_dir, MAX_PDF_PAGES):
            body = result['text']
            chars += len(body)+30
            if chars > MAX_TEXT_CHARS:
                raise error('图片识别正文超过 2000 万字符，请拆分文件。')
            parts.append(f'\n[第 {page_number} 页]\n'+body)
            pages.append({'page': page_number, 'chars': len(body.strip()), **{k: result[k] for k in ('method','lines','confidence','low_confidence_lines')}})
            file_pages.write_page(source,page_number,result)
            progress(page_number, total, '图片 OCR 已完成')
        text = '\n'.join(parts)
        save_report(pages)
        if not local_ocr.meaningful(re.sub(r'\[第 \d+ 页\]', '', text)):
            raise error('OCR 未识别到可用文字，请检查图片清晰度、方向和内容。')
    elif suffix == '.docx':
        parts, chars = [], 0
        with zipfile.ZipFile(source) as archive:
            with archive.open('word/document.xml') as document:
                for _, element in ET.iterparse(document, events=('end',)):
                    if element.tag.endswith('}p'):
                        line = ''.join(node.text or '' for node in element.iter() if node.tag.endswith('}t'))
                        chars += len(line)+1
                        if chars > MAX_TEXT_CHARS:
                            raise error('Word 提取正文超过 2000 万字符，请拆分文档。')
                        parts.append(line)
                        element.clear()
        text = '\n'.join(parts)
    else:
        text = read_text()

    if purpose == 'document':
        return name, [], text
    if suffix in ('.json', '.jsonl'):
        try:
            rows = [json.loads(line) for line in text.splitlines() if line.strip()] if suffix == '.jsonl' else json.loads(text)
            rows = rows.get('questions', [rows]) if isinstance(rows, dict) else rows
            if not isinstance(rows, list):
                raise ValueError()
        except ValueError:
            raise error('JSON 格式无效，应为题目数组或含 questions 数组的对象。')
    elif suffix in ('.csv', '.tsv'):
        rows = []
        for row in csv.DictReader(io.StringIO(text), delimiter='\t' if suffix == '.tsv' else ','):
            rows.append(row)
            if len(rows) > MAX_QUESTIONS:
                raise error('单个题库识别超过 5000 题，请拆分后导入。')
    else:
        rows = parse_questions(text)
        if suffix in ('.pdf',*local_ocr.IMAGE_EXTENSIONS) and isinstance(source,Path):
            import file_pages as page_store
            from library_rebuild import build_rows
            page_texts=page_store.split_pages(text)
            rebuilt,meta=build_rows([{'page':n,'text':t} for n,t in page_texts.items()],name,source.parent.name,source.stem)
            if rebuilt and (meta.get('key_sections') or meta.get('subjective') or any(q.get('reading_source') for q in rebuilt)):rows=rebuilt
    if len(rows) > MAX_QUESTIONS:
        raise error('单个题库识别超过 5000 题，请拆分后导入。')
    return name, rows, text
