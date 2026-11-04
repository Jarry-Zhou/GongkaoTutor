import http.client
import io
import json
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import Application, Handler, UserError
from file_imports import CHUNK_BYTES, MAX_FILE_BYTES, FileImportManager


class BatchUploadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Application(self.tmp.name)
        self.manager = self.app.uploads

    def tearDown(self):
        self.manager.tasks.join()
        self.tmp.cleanup()

    def batch(self, sources):
        return self.manager.create({'files': [dict(name=name, size=len(data), purpose=purpose, last_modified=1)
            for name, data, purpose in sources]})

    def upload(self, batch, index, data, process=True):
        item = batch['files'][index]
        for offset in range(0, len(data), CHUNK_BYTES):
            block = data[offset:offset+CHUNK_BYTES]
            self.manager.write_chunk(batch['id'], item['id'], offset, len(block), io.BytesIO(block))
        if process:
            self.manager.enqueue(batch['id'], item['id'])

    def wait(self, batch):
        self.manager.tasks.join()
        return self.manager.require(batch['id'])['files']

    def question_data(self):
        return json.dumps([{'stem':'只有报名才可以考试，已经考试可以推出什么？',
            'options':{'A':'已报名','B':'未报名'},'answer':['A'],'module':'判断推理',
            'knowledge_points':['必要条件']}],ensure_ascii=False).encode()

    def test_37_mixed_batch_keeps_destinations_and_requires_question_confirmation(self):
        text='资料：只有A才B，表示B推出A。不要颠倒条件关系。'.encode()
        data=self.question_data()
        batch=self.batch([('知识.md',text,'document'),('题库.json',data,'question_bank')])
        self.upload(batch,0,text); self.upload(batch,1,data)
        files=self.wait(batch)
        self.assertEqual([f['status'] for f in files],['completed','preview_ready'])
        self.assertEqual(self.app.store.count('documents'),1)
        self.assertEqual(self.app.store.count('questions'),0)
        self.manager.commit(batch['id'],files[1]['id'])
        self.manager.commit(batch['id'],files[1]['id'])
        self.assertEqual(self.app.store.count('questions'),1)
        self.assertEqual(self.app.store.count('documents'),1)
        with self.assertRaises(UserError): self.manager.commit(batch['id'],files[0]['id'])

    def test_38_same_file_can_be_a_document_and_question_bank(self):
        data=self.question_data()
        batch=self.batch([('两用.json',data,'document'),('两用.json',data,'question_bank')])
        self.upload(batch,0,data); self.upload(batch,1,data)
        self.assertEqual([f['status'] for f in self.wait(batch)],['completed','preview_ready'])

    def test_39_resume_checks_offsets_and_rejects_incomplete_upload(self):
        data=b'0123456789'
        batch=self.batch([('resume.txt',data,'document')]); item=batch['files'][0]
        self.manager.write_chunk(batch['id'],item['id'],0,4,io.BytesIO(data[:4]))
        with self.assertRaises(UserError) as error:
            self.manager.write_chunk(batch['id'],item['id'],0,4,io.BytesIO(data[:4]))
        self.assertEqual(error.exception.details['expected_offset'],4)
        with self.assertRaises(UserError): self.manager.enqueue(batch['id'],item['id'])
        with self.assertRaises(UserError):
            self.manager.write_chunk(batch['id'],item['id'],4,6,io.BytesIO(b'bad'))
        self.assertEqual(self.manager.path_for(batch['id'],item['id']).stat().st_size,4)
        restarted=FileImportManager(self.app,UserError)
        restarted.write_chunk(batch['id'],item['id'],4,6,io.BytesIO(data[4:]))
        restarted.enqueue(batch['id'],item['id']); restarted.tasks.join()
        self.assertEqual(restarted.require(batch['id'],item['id'])[1]['status'],'completed')

    def test_40_limits_and_purpose_are_validated_before_upload(self):
        base={'name':'a.pdf','size':MAX_FILE_BYTES,'purpose':'document'}
        self.manager.create({'files':[base]})
        for invalid in [{**base,'size':MAX_FILE_BYTES+1},{**base,'size':0},{**base,'purpose':'auto'},
                        {**base,'name':'a.exe'}]:
            with self.assertRaises(UserError): self.manager.create({'files':[invalid]})
        with self.assertRaises(UserError): self.manager.create({'files':[base]*101})

    def test_41_failed_file_does_not_abort_batch_and_can_change_purpose(self):
        bad=b'not a question bank, just notes on learning'
        good='必要条件：只有A才B，B推出A。'.encode()
        batch=self.batch([('误选题库.txt',bad,'question_bank'),('知识.md',good,'document')])
        self.upload(batch,0,bad); self.upload(batch,1,good)
        files=self.wait(batch)
        self.assertEqual([f['status'] for f in files],['error','completed'])
        self.assertEqual(self.app.store.count('documents'),1)
        self.manager.retry(batch['id'],files[0]['id'],{'purpose':'document'})
        self.assertEqual(self.wait(batch)[0]['status'],'completed')
        self.assertEqual(self.app.store.count('documents'),2)
        self.assertEqual(self.app.store.count('questions'),0)

    def test_42_typed_deduplication_and_deleted_document_reimport(self):
        data='知识资料，非题库。必要条件B推出A。'.encode()
        batch=self.batch([('first.md',data,'document'),('second.md',data,'document')])
        self.upload(batch,0,data); self.upload(batch,1,data)
        files=self.wait(batch)
        self.assertEqual([f['status'] for f in files],['completed','skipped'])
        self.app.dispatch('DELETE','/api/documents/'+files[0]['document_id'],{})
        again=self.batch([('again.md',data,'document')]);self.upload(again,0,data)
        self.assertEqual(self.wait(again)[0]['status'],'completed')

    def test_43_large_document_summaries_are_bounded_and_indexed(self):
        text=('背景材料与方法笔记。\n'*160000)+'稀有关键词鹈鹕算法：先确认必要条件，再逆否。'
        doc=self.app.add_document({'title':'大正文','text':text})
        self.assertGreater(len(text),1500000)
        summaries=self.app.dispatch('GET','/api/documents',{})
        self.assertEqual(summaries[0]['char_count'],len(text))
        self.assertEqual(len(summaries[0]['text']),1200)
        self.assertTrue(any('鹈鹕算法' in s['text'] for s in self.app.sources('鹈鹕算法')))
        reloaded=Application(self.tmp.name)
        self.assertTrue(reloaded.sources('鹈鹕算法'))
        self.app.dispatch('DELETE','/api/documents/'+doc['id'],{})
        self.assertEqual(self.app.sources('鹈鹕算法'),[])

    def test_44_large_pdf_over_15mb_uses_binary_http_chunks(self):
        from pypdf import PdfReader, PdfWriter
        from reportlab.pdfgen import canvas
        buf=io.BytesIO(); c=canvas.Canvas(buf)
        c.drawString(40,700,'Necessary conditions: B implies A. Check the premise before applying a rule.')
        c.save(); writer=PdfWriter(clone_from=PdfReader(io.BytesIO(buf.getvalue())))
        writer.add_attachment('image-data.bin',b'\0'*(16*1024*1024))
        out=io.BytesIO();writer.write(out); data=out.getvalue()
        self.assertGreater(len(data),15*1024*1024)
        bank=self.question_data()+b' '*(16*1024*1024)
        batch=self.batch([('large.pdf',data,'document'),('large-bank.json',bank,'question_bank')]); item=batch['files'][0]
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.application=self.app
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            for file_index,content in enumerate([data,bank]):
                current=batch['files'][file_index]
                path=f"/api/file-imports/{batch['id']}/files/{current['id']}/content"
                for offset in range(0,len(content),CHUNK_BYTES):
                    client=http.client.HTTPConnection('127.0.0.1',server.server_port)
                    client.request('PUT',path,content[offset:offset+CHUNK_BYTES],{'Content-Type':'application/octet-stream','X-Upload-Offset':str(offset)})
                    response=client.getresponse(); body=json.loads(response.read())
                    self.assertEqual(response.status,200,body);client.close()
                self.manager.enqueue(batch['id'],current['id'])
            self.assertEqual([f['status'] for f in self.wait(batch)],['completed','preview_ready'])
            self.assertEqual(self.app.store.count('questions'),0)
            self.assertIn('B implies A',self.app.store.all('documents')[0]['text'])
            client=http.client.HTTPConnection('127.0.0.1',server.server_port)
            client.request('PUT',path,b'x',{'Origin':'https://example.com','Content-Type':'application/octet-stream','X-Upload-Offset':'0'})
            response=client.getresponse();response.read();self.assertEqual(response.status,403);client.close()
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_45_question_limit_rejects_without_truncation(self):
        data=json.dumps([{'stem':str(i),'answer':'text'} for i in range(5001)]).encode()
        batch=self.batch([('too-many.json',data,'question_bank')]);self.upload(batch,0,data)
        item=self.wait(batch)[0]
        self.assertEqual(item['status'],'error');self.assertIn('5000',item['error'])
        self.assertEqual(self.app.store.count('questions'),0)

    def test_46_forged_disk_path_and_invalid_chunk_are_rejected(self):
        with self.assertRaises(UserError): self.app.add_document({'_source_path':'C:/Windows/win.ini'})
        batch=self.batch([('note.md',b'123','document')]);item=batch['files'][0]
        with self.assertRaises(UserError): self.manager.path_for('../x',item['id'])
        with self.assertRaises(UserError):
            self.manager.write_chunk(batch['id'],item['id'],0,CHUNK_BYTES+1,io.BytesIO(b'x'))

    def test_47_restart_exposes_interrupted_parser_as_retryable(self):
        data=b'persisted source'
        batch=self.batch([('note.md',data,'document')]);self.upload(batch,0,data,False)
        item=batch['files'][0]
        self.manager.update(batch['id'],item['id'],status='parsing')
        restarted=Application(self.tmp.name)
        saved=restarted.uploads.require(batch['id'],item['id'])[1]
        self.assertEqual(saved['status'],'uploaded')
        restarted.uploads.retry(batch['id'],item['id'],{})
        restarted.uploads.tasks.join()
        self.assertEqual(restarted.store.count('documents'),1)


if __name__=='__main__': unittest.main()
