"""Persistent, typed batch imports with bounded-memory chunked uploads."""
from __future__ import annotations

import hashlib
import queue
import re
import shutil
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

MAX_FILE_BYTES = 500 * 1024 * 1024
CHUNK_BYTES = 8 * 1024 * 1024
MAX_BATCH_FILES = 100
MAX_TEXT_CHARS = 20_000_000
MAX_PDF_PAGES = 5000
MAX_QUESTIONS = 5000
EXTENSIONS = {'.pdf', '.docx', '.xlsx', '.txt', '.md', '.markdown', '.csv', '.tsv', '.json', '.jsonl'}
EXTENSIONS.update({'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff'})
ACTIVE_PARSE = {'queued', 'parsing'}
DELETABLE = {'waiting_upload', 'uploading', 'uploaded', 'queued', 'parsing', 'error'}


class ImportCancelled(Exception):
    """A user removed this file before its parsed result was committed."""


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class FileImportManager:
    def __init__(self, app, error_type):
        self.app, self.store, self.error = app, app.store, error_type
        self.folder = self.store.folder / 'file-imports'
        self.lock = threading.RLock()
        self.tasks = queue.Queue()
        self.worker = None
        # Uploaded sources and completed results survive process restarts.
        for batch in self.store.all('file_imports'):
            changed = False
            for item in batch['files']:
                if item['status'] == 'deleting':
                    item.update(status='deleted', error='', deleted_at=timestamp(), progress={'stage': '任务已删除，可恢复'})
                    changed = True
                if item['status'] in ACTIVE_PARSE:
                    item.update(status='uploaded', error='服务重启，可点击重试继续解析。')
                    changed = True
            if changed:
                self.store.put('file_imports', batch)

    @staticmethod
    def limits():
        return {'max_file_bytes': MAX_FILE_BYTES, 'chunk_bytes': CHUNK_BYTES, 'max_batch_files': MAX_BATCH_FILES,
                'max_text_chars': MAX_TEXT_CHARS, 'max_pdf_pages': MAX_PDF_PAGES, 'max_questions': MAX_QUESTIONS}

    def require(self, batch_id, file_id=None):
        if not re.fullmatch(r'up_[a-f0-9]{24}', batch_id):
            raise self.error('导入任务编号无效。', 404)
        batch = self.store.get('file_imports', batch_id)
        if not batch:
            raise self.error('导入任务不存在。', 404)
        if file_id is None:
            return batch
        item = next((f for f in batch['files'] if f['id'] == file_id), None)
        if item is None:
            raise self.error('该文件不属于当前任务。', 404)
        return batch, item

    def path_for(self, batch_id, file_id):
        if not re.fullmatch(r'up_[a-f0-9]{24}', batch_id) or not re.fullmatch(r'f_[a-f0-9]{24}', file_id):
            raise self.error('导入路径编号无效。')
        path = (self.folder / batch_id / (file_id + '.source')).resolve()
        if not path.is_relative_to(self.folder.resolve()):
            raise self.error('导入路径无效。')
        return path

    def create(self, payload):
        files = payload.get('files')
        if not isinstance(files, list) or not 1 <= len(files) <= MAX_BATCH_FILES:
            raise self.error(f'每批请选择 1—{MAX_BATCH_FILES} 个文件。')
        items, total = [], 0
        for raw in files:
            if not isinstance(raw, dict):
                raise self.error('文件列表格式无效。')
            name = str(raw.get('name', '')).replace('\\', '/').split('/')[-1].strip()
            if not name or len(name) > 240 or Path(name).suffix.lower() not in EXTENSIONS:
                raise self.error('请选择 PDF、DOCX、XLSX、文本、CSV 或 JSON 等支持的文件。')
            size = raw.get('size', 0)
            if isinstance(size, bool) or not isinstance(size, int) or size <= 0 or size > MAX_FILE_BYTES:
                raise self.error(f'“{name}”需为非空文件，单个文件上限 500 MB。')
            purpose = raw.get('purpose')
            if purpose not in ('document', 'question_bank'):
                raise self.error(f'请为“{name}”指定“知识资料”或“题库”，不会自动混存。')
            if raw.get('ocr_mode', 'auto') not in ('auto', 'force', 'off'):
                raise self.error('OCR 模式无效。')
            items.append({'id': 'f_' + uuid.uuid4().hex[:24], 'name': name, 'size': size, 'purpose': purpose,
                          'last_modified': raw.get('last_modified', 0), 'use_ai': bool(raw.get('use_ai')) if purpose == 'question_bank' else False,
                          'ocr_mode': raw.get('ocr_mode', 'auto'),
                          'status': 'waiting_upload', 'uploaded_bytes': 0, 'progress': {}, 'error': '', 'created_at': timestamp(), 'retries': 0})
            total += size
        self.folder.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(self.folder).free < total + 128 * 1024 * 1024:
            raise self.error('D 盘可用空间不足以接收这批文件，请减少本批文件或释放空间。', 409)
        batch = {'id': 'up_' + uuid.uuid4().hex[:24], 'created_at': timestamp(), 'total_bytes': total, 'files': items}
        (self.folder / batch['id']).mkdir()
        self.store.put('file_imports', batch)
        return batch

    def write_chunk(self, batch_id, file_id, offset, length, stream):
        if length <= 0 or length > CHUNK_BYTES:
            raise self.error('每个上传分片必须在 1 字节至 8 MB 之间。', 413)
        with self.lock:
            batch, item = self.require(batch_id, file_id)
            if item['status'] in ('deleted', 'deleting'):
                raise self.error('任务已删除，上传已停止。', 409)
            if item['status'] not in ('waiting_upload', 'uploading'):
                raise self.error('该文件已上传完成或进入处理阶段。', 409, {'expected_offset': item['uploaded_bytes']})
            expected = item['uploaded_bytes']
            if offset != expected:
                raise self.error('上传位置已更新，可从已保存位置继续。', 409, {'expected_offset': expected})
            if offset + length > item['size']:
                raise self.error('分片超过声明的文件大小。', 413)
            path = self.path_for(batch_id, file_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('r+b' if path.exists() else 'w+b') as target:
                target.seek(offset)
                remaining = length
                try:
                    while remaining:
                        block = stream.read(min(256 * 1024, remaining))
                        if not block:
                            raise self.error('上传连接中断，可重试该文件。', 400)
                        target.write(block)
                        remaining -= len(block)
                    target.flush()
                except Exception:
                    target.truncate(offset)
                    raise
            item['uploaded_bytes'] += length
            item['status'] = 'uploaded' if item['uploaded_bytes'] == item['size'] else 'uploading'
            item['error'] = ''
            self.store.put('file_imports', batch)
            return item

    def enqueue(self, batch_id, file_id):
        with self.lock:
            batch, item = self.require(batch_id, file_id)
            if item['status'] in ('deleted', 'deleting'):
                raise self.error('任务已删除，请先恢复后再继续。', 409)
            if item['status'] in ('queued', 'parsing', 'completed', 'preview_ready', 'skipped'):
                return item
            if item['uploaded_bytes'] != item['size']:
                raise self.error('文件尚未上传完整，请重新选择原文件继续上传。', 409)
            if not self.path_for(batch_id, file_id).is_file():
                raise self.error('上传源文件不存在，请重新创建导入任务。', 409)
            item.update(status='queued', error='', progress={'stage': '等待解析'}, run_token=uuid.uuid4().hex)
            self.store.put('file_imports', batch)
            self.tasks.put((batch_id, file_id, item['run_token']))
            if self.worker is None or not self.worker.is_alive():
                self.worker = threading.Thread(target=self.run, name='knowledge-file-import', daemon=True)
                self.worker.start()
            return item

    def update(self, batch_id, file_id, **changes):
        with self.lock:
            batch, item = self.require(batch_id, file_id)
            if item['status'] in ('deleted', 'deleting'):
                raise ImportCancelled()
            item.update(changes)
            self.store.put('file_imports', batch)
            return dict(item)

    def check_cancelled(self, batch_id, file_id):
        with self.lock:
            _, item = self.require(batch_id, file_id)
            if item['status'] in ('deleted', 'deleting'):
                raise ImportCancelled()

    def finish_deletion(self, batch_id, file_id):
        with self.lock:
            batch, item = self.require(batch_id, file_id)
            if item['status'] in ('deleted', 'deleting'):
                item.update(status='deleted', error='', deleted_at=item.get('deleted_at') or timestamp(), progress={'stage': '任务已删除，可恢复'})
                self.store.put('file_imports', batch)

    def remove(self, batch_id, file_id):
        with self.lock:
            batch, item = self.require(batch_id, file_id)
            if item['status'] in ('deleted', 'deleting'):
                return item
            if item['status'] not in DELETABLE:
                raise self.error('该文件已经解析完成，不能作为未解析任务删除。已入库数据保持不变。', 409)
            previous = item['status']
            item.update(status='deleting' if previous == 'parsing' else 'deleted', deleted_from=previous,
                        delete_requested_at=timestamp(), error='',
                        progress={'stage': '正在停止当前解析步骤' if previous == 'parsing' else '任务已删除，可恢复'})
            if previous != 'parsing':
                item['deleted_at'] = timestamp()
            self.store.put('file_imports', batch)
            return item

    def remove_pending(self, batch_id, payload):
        ids = payload.get('file_ids')
        if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_BATCH_FILES or any(not isinstance(key, str) for key in ids):
            raise self.error('请选择本批需要删除的未解析任务。')
        ids = list(dict.fromkeys(ids))
        with self.lock:
            batch = self.require(batch_id)
            known = {f['id'] for f in batch['files']}
            if not set(ids).issubset(known):
                raise self.error('删除列表包含不属于本批的文件。')
            removed, stopping, kept = [], [], []
            for file_id in ids:
                _, item = self.require(batch_id, file_id)
                if item['status'] not in DELETABLE | {'deleted', 'deleting'}:
                    kept.append(file_id)
                    continue
                result = self.remove(batch_id, file_id)
                (stopping if result['status'] == 'deleting' else removed).append(file_id)
            return {'deleted': removed, 'stopping': stopping, 'kept': kept}

    def restore(self, batch_id, file_id):
        with self.lock:
            batch, item = self.require(batch_id, file_id)
            if item['status'] == 'deleting':
                raise self.error('当前步骤尚未停止，请稍后恢复。', 409)
            if item['status'] != 'deleted':
                return item
            complete = item['uploaded_bytes'] == item['size']
            if complete and not self.path_for(batch_id, file_id).is_file():
                raise self.error('原上传副本不存在，请重新选择文件上传。', 409)
            item.update(status='uploaded' if complete else 'uploading' if item['uploaded_bytes'] else 'waiting_upload',
                        error='', progress={'stage': '任务已恢复'}, restored_at=timestamp())
            self.store.put('file_imports', batch)
            if complete:
                return self.enqueue(batch_id, file_id)
            return item

    def duplicate(self, purpose, digest, batch_id, file_id, ocr_mode='auto'):
        for batch in self.store.all('file_imports'):
            for item in batch['files']:
                if batch['id'] == batch_id and item['id'] == file_id:
                    continue
                if item['purpose'] == purpose and item.get('sha256') == digest and item['status'] in ('completed', 'skipped') and item.get('ocr_mode', 'off') == ocr_mode:
                    if purpose == 'document' and not self.store.get('documents', item.get('document_id', '')):
                        continue
                    return item
        return None

    def run(self):
        while True:
            try:
                batch_id, file_id, run_token = self.tasks.get(timeout=.2)
            except queue.Empty:
                with self.lock:
                    if self.tasks.empty():
                        self.worker = None
                        return
                continue
            try:
                with self.lock:
                    _, item = self.require(batch_id, file_id)
                    if item['status'] != 'queued' or item.get('run_token') != run_token:
                        continue
                    self.update(batch_id, file_id, status='parsing', progress={'stage': '检查文件内容'})
                path = self.path_for(batch_id, file_id)
                with path.open('rb') as source:
                    digest = hashlib.file_digest(source, 'sha256').hexdigest()
                self.update(batch_id, file_id, sha256=digest)
                previous = self.duplicate(item['purpose'], digest, batch_id, file_id, item.get('ocr_mode', 'auto'))
                if previous:
                    self.update(batch_id, file_id, status='skipped', document_id=previous.get('document_id'), import_id=previous.get('import_id'),
                                progress={'stage': '同用途的相同文件已导入'}, finished_at=timestamp())
                    continue
                last_progress = [0.0]
                def progress(done, total, stage='提取正文'):
                    self.check_cancelled(batch_id, file_id)
                    clock = time.monotonic()
                    if done == total or clock - last_progress[0] > .8:
                        self.update(batch_id, file_id, progress={'stage': stage, 'done': done, 'total': total})
                        last_progress[0] = clock
                payload = {'name': item['name'], '_source_path': path, '_progress': progress,
                           'ocr_mode': item.get('ocr_mode', 'auto'),
                           '_check_cancel': lambda: self.check_cancelled(batch_id, file_id),
                           '_metadata': lambda report: self.update(batch_id, file_id, ocr=report)}
                if item['purpose'] == 'document':
                    result = self.app.add_document(payload, persist=False)
                    changes = dict(status='completed', document_id=result['id'], chars=len(result['text']), chunks=len(result['chunks']),
                                   progress={'stage': '知识资料已入库'}, finished_at=timestamp())
                else:
                    result = self.app.preview_import({**payload, 'use_ai': item['use_ai']}, persist=False)
                    if not result['items']:
                        raise self.error('未识别到可作答题目。请检查题号、选项与答案排版，或在重试时使用模型辅助提取；不会将题库整本存入知识资料。')
                    changes = dict(status='preview_ready', import_id=result['id'], question_count=len(result['items']),
                                   review_count=sum(q['status'] == 'review' for q in result['items']), progress={'stage': '题目已提取，等待预览确认'})
                # A delete request and the final data commit cannot pass each other.
                with self.lock, self.store.connect() as db:
                    self.check_cancelled(batch_id, file_id)
                    if item['purpose'] == 'document':
                        self.app.save_document(result, db)
                    else:
                        self.store.put('imports', result, db)
                    batch, current = self.require(batch_id, file_id)
                    current.update(changes)
                    self.store.put('file_imports', batch, db)
            except ImportCancelled:
                self.finish_deletion(batch_id, file_id)
            except Exception as error:
                try:
                    self.update(batch_id, file_id, status='error', error=str(error)[:2000], progress={'stage': '处理失败，可单独重试'})
                except ImportCancelled:
                    self.finish_deletion(batch_id, file_id)
            finally:
                self.tasks.task_done()

    def retry(self, batch_id, file_id, payload):
        with self.lock:
            batch, item = self.require(batch_id, file_id)
            if item['status'] not in ('error', 'uploaded'):
                return item
            if 'purpose' in payload and payload['purpose'] in ('document', 'question_bank'):
                item['purpose'] = payload['purpose']
            if item['purpose'] == 'question_bank' and 'use_ai' in payload:
                item['use_ai'] = bool(payload['use_ai'])
            if 'ocr_mode' in payload:
                if payload['ocr_mode'] not in ('auto', 'force', 'off'):
                    raise self.error('OCR 模式无效。')
                item['ocr_mode'] = payload['ocr_mode']
            item['retries'] += 1
            self.store.put('file_imports', batch)
        return self.enqueue(batch_id, file_id)

    def commit(self, batch_id, file_id):
        with self.lock:
            batch, item = self.require(batch_id, file_id)
            if item['purpose'] != 'question_bank':
                raise self.error('知识资料不能按题库确认入库。')
            if item['status'] == 'completed':
                return item
            if item['status'] != 'preview_ready':
                raise self.error('题库尚未完成提取预览。', 409)
            result = self.app.commit_import(item['import_id'])
            item.update(status='completed', added=result['added'], skipped=result['skipped'], finished_at=timestamp(), progress={'stage': '题库已确认入库'})
            self.store.put('file_imports', batch)
            return item

    def dispatch(self, method, parts, body):
        if len(parts) == 2:
            if method == 'POST':
                return self.create(body)
            if method == 'GET':
                return self.store.all('file_imports')[:20]
        if len(parts) == 3 and method == 'GET':
            return self.require(parts[2])
        if len(parts) == 4 and parts[3] == 'delete-pending' and method == 'POST':
            return self.remove_pending(parts[2], body)
        if len(parts) == 5 and parts[3] == 'files' and method == 'DELETE':
            return self.remove(parts[2], parts[4])
        if len(parts) == 6 and parts[3] == 'files' and method == 'POST':
            batch_id, file_id, action = parts[2], parts[4], parts[5]
            if action == 'process':
                return self.enqueue(batch_id, file_id)
            if action == 'rebuild':
                from library_rebuild import rebuild
                return rebuild(self,batch_id,file_id,body)
            if action == 'retry':
                return self.retry(batch_id, file_id, body)
            if action == 'restore':
                return self.restore(batch_id, file_id)
            if action == 'commit':
                return self.commit(batch_id, file_id)
            if action == 'preview':
                _, item = self.require(batch_id, file_id)
                if item['purpose'] != 'question_bank' or not item.get('import_id'):
                    raise self.error('该文件没有题库预览。')
                return self.app.require('imports', item['import_id'])
        raise self.error('导入接口不存在。', 404)
