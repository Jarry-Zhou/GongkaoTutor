import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import Application, UserError
import local_ocr


@unittest.skipUnless(local_ocr.status()['available'], 'Install requirements-dev.txt to test local OCR')
class OCRTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PIL import Image, ImageDraw, ImageFont
        cls.image=Image.new('RGB',(1600,2200),'white')
        draw=ImageDraw.Draw(cls.image)
        font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',44)
        for i,text in enumerate(['1. 只有完成报名，才能参加考试。','小林已参加考试，可以推出什么？',
                                  'A. 小林已经报名','B. 小林没有报名','答案：A','解析：参加考试推出完成报名。']):
            draw.text((100,150+i*90),text,font=font,fill='black')
        buf=io.BytesIO();cls.image.save(buf,'PDF',resolution=200);cls.scan=buf.getvalue()
        buf=io.BytesIO();cls.image.save(buf,'PNG');cls.png=buf.getvalue()

    @classmethod
    def tearDownClass(cls): cls.image.close()

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.app=Application(self.root/'data')

    def tearDown(self):
        self.app.uploads.tasks.join()
        self.tmp.cleanup()

    def payload(self, name='scan.pdf', data=None, **extra):
        path=self.root/name;path.write_bytes(data if data is not None else self.scan)
        return {'name':name,'_source_path':path,**extra}

    def fake(self,text='识别正文，只有完成报名才能参加考试。',low=0):
        return {'text':text,'method':'ocr','lines':2,'confidence':.7 if low else .99,'low_confidence_lines':low}

    def test_48_real_scan_document_is_searchable_with_page_provenance(self):
        result=self.app.add_document(self.payload())
        self.assertIn('完成报名',result['text'])
        self.assertEqual(result['ocr']['ocr_pages'],1)
        self.assertEqual(result['chunks'][0]['page'],'[第 1 页]')
        self.assertTrue(self.app.sources('报名考试'))
        summary=self.app.dispatch('GET','/api/documents',{})[0]
        self.assertEqual(summary['ocr']['ocr_pages'],1)
        self.assertEqual(self.app.store.count('questions'),0)

    def test_49_real_scan_question_bank_stays_in_preview(self):
        result=self.app.preview_import(self.payload())
        self.assertEqual(len(result['items']),1)
        q=result['items'][0]
        self.assertEqual(q['answer'],['A'])
        self.assertIn('已经报名',q['options']['A'])
        self.assertEqual(result['ocr']['ocr_pages'],1)
        self.assertEqual(self.app.store.count('documents'),0)
        self.assertEqual(self.app.store.count('questions'),0)
        self.app.commit_import(result['id'])
        self.assertEqual(self.app.store.count('questions'),1)

    def test_50_real_image_import_runs_without_network_or_model_api(self):
        with patch('requests.sessions.Session.request',side_effect=AssertionError('Network forbidden')), \
             patch.object(self.app,'model_call',side_effect=AssertionError('No model API for OCR')):
            result=self.app.add_document(self.payload('scan.png',self.png))
        self.assertIn('完成报名',result['text'])
        self.assertEqual(result['ocr']['ocr_pages'],1)

    def test_51_native_pages_do_not_run_ocr_in_auto_mode(self):
        from reportlab.pdfgen import canvas
        buf=io.BytesIO();c=canvas.Canvas(buf)
        c.drawString(30,700,'Native text is long enough. Necessary conditions: B implies A.');c.save()
        with patch('local_ocr.recognize',side_effect=AssertionError('Native text should be preserved')):
            doc=self.app.add_document(self.payload(data=buf.getvalue()))
        self.assertIn('Native text',doc['text'])
        self.assertEqual(doc['ocr']['ocr_pages'],0)

    def test_52_force_mode_recognizes_even_existing_text_layers(self):
        from reportlab.pdfgen import canvas
        buf=io.BytesIO();c=canvas.Canvas(buf)
        c.drawString(30,700,'Native text with a corrupt or incomplete layer but sufficient characters');c.save()
        with patch('local_ocr.recognize',return_value=self.fake()) as recognizer:
            doc=self.app.add_document(self.payload(data=buf.getvalue(),ocr_mode='force'))
        self.assertEqual(recognizer.call_count,1)
        self.assertIn('识别正文',doc['text'])

    def test_53_off_mode_rejects_scans_and_images_explicitly(self):
        for payload in [self.payload(ocr_mode='off'),self.payload('scan.png',self.png,ocr_mode='off')]:
            with self.assertRaises(UserError) as error:self.app.add_document(payload)
            self.assertIn('OCR',str(error.exception))
        self.assertEqual(self.app.store.count('documents'),0)

    def test_54_mixed_pdf_keeps_native_scan_and_blank_page_numbers(self):
        from pypdf import PdfReader,PdfWriter
        from reportlab.pdfgen import canvas
        buf=io.BytesIO();c=canvas.Canvas(buf);c.drawString(30,700,'Native text page: use the correct implication direction to solve the question.');c.save()
        writer=PdfWriter();writer.append(PdfReader(io.BytesIO(buf.getvalue())))
        writer.append(PdfReader(io.BytesIO(self.scan)));writer.add_blank_page(576,792)
        output=io.BytesIO();writer.write(output)
        doc=self.app.add_document(self.payload(data=output.getvalue()))
        self.assertEqual([p['method'] for p in doc['ocr']['pages']],['native','ocr','ocr'])
        self.assertEqual(doc['ocr']['empty_pages'],[3])
        self.assertIn('[第 2 页]',doc['text'])
        self.assertIn('完成报名',doc['text'])

    def test_55_page_cache_is_reused_after_interruption(self):
        from pypdf import PdfReader,PdfWriter
        writer=PdfWriter();writer.append(PdfReader(io.BytesIO(self.scan)));writer.append(PdfReader(io.BytesIO(self.scan)))
        output=io.BytesIO();writer.write(output);payload=self.payload(data=output.getvalue())
        with patch('local_ocr.recognize',side_effect=[self.fake(),RuntimeError('Interrupted')]):
            partial=self.app.add_document(payload)
        self.assertEqual(partial['ocr']['failed_pages'],[2])
        self.assertEqual(partial['ocr']['empty_pages'],[2])
        with patch('local_ocr.recognize',return_value=self.fake()) as recognizer:
            doc=self.app.add_document(payload)
        self.assertEqual(recognizer.call_count,1)
        self.assertEqual(doc['ocr']['ocr_pages'],2)

    def test_56_low_confidence_question_is_marked_for_review(self):
        text='1. 只有完成报名才能考试，已考试可推出什么？\nA. 已报名\nB. 未报名\n答案：A'
        with patch('local_ocr.recognize',return_value=self.fake(text,1)):
            preview=self.app.preview_import(self.payload())
        self.assertEqual(preview['items'][0]['status'],'review')
        self.assertIn('OCR',preview['items'][0]['issues'][-1])
        self.assertTrue(preview['ocr']['warnings'])

    def test_57_blank_ocr_does_not_create_a_fake_document(self):
        with patch('local_ocr.recognize',return_value=self.fake('')):
            with self.assertRaises(UserError): self.app.add_document(self.payload())
        self.assertEqual(self.app.store.count('documents'),0)

    def test_58_batch_scan_metadata_and_purposes_remain_separate(self):
        manager=self.app.uploads
        batch=manager.create({'files':[{'name':'scan.pdf','size':len(self.scan),'purpose':purpose,'ocr_mode':'auto'}
                                      for purpose in ['document','question_bank']]})
        for item in batch['files']:
            manager.write_chunk(batch['id'],item['id'],0,len(self.scan),io.BytesIO(self.scan))
            manager.enqueue(batch['id'],item['id'])
        manager.tasks.join();items=manager.require(batch['id'])['files']
        self.assertEqual([i['status'] for i in items],['completed','preview_ready'])
        self.assertEqual([i['ocr']['ocr_pages'] for i in items],[1,1])
        self.assertEqual(self.app.store.count('documents'),1)
        self.assertEqual(self.app.store.count('questions'),0)

    def test_59_ocr_mode_is_validated_and_retry_can_enable_it(self):
        manager=self.app.uploads
        with self.assertRaises(UserError):manager.create({'files':[{'name':'scan.pdf','size':1,'purpose':'document','ocr_mode':'cloud'}]})
        batch=manager.create({'files':[{'name':'scan.pdf','size':len(self.scan),'purpose':'document','ocr_mode':'off'}]})
        item=batch['files'][0]
        manager.write_chunk(batch['id'],item['id'],0,len(self.scan),io.BytesIO(self.scan));manager.enqueue(batch['id'],item['id']);manager.tasks.join()
        self.assertEqual(manager.require(batch['id'],item['id'])[1]['status'],'error')
        manager.retry(batch['id'],item['id'],{'ocr_mode':'auto'});manager.tasks.join()
        self.assertEqual(manager.require(batch['id'],item['id'])[1]['status'],'completed')

    def test_60_engine_status_does_not_expose_local_paths_or_credentials(self):
        info=self.app.dispatch('GET','/api/ocr/status',{})
        self.assertTrue(info['available']);self.assertTrue(info['local'])
        raw=json.dumps(info)
        self.assertNotIn(str(self.root),raw);self.assertNotIn('api_key',raw)

    def test_61_scan_with_selectable_watermark_still_uses_ocr(self):
        from pypdf import PdfReader,PdfWriter
        from pypdf.generic import NameObject
        from reportlab.pdfgen import canvas
        stamp=io.BytesIO();c=canvas.Canvas(stamp,pagesize=(576,792))
        c.drawString(20,20,'Selectable watermark, not the scanned page content');c.save()
        page=PdfReader(io.BytesIO(self.scan)).pages[0]
        page.merge_page(PdfReader(io.BytesIO(stamp.getvalue())).pages[0])
        writer=PdfWriter();writer.add_page(page)
        # Some producers store page resources in an indirect PDF object.
        resources=writer.pages[0]['/Resources']
        writer.pages[0][NameObject('/Resources')]=writer._add_object(resources)
        output=io.BytesIO();writer.write(output)
        doc=self.app.add_document(self.payload(data=output.getvalue()))
        self.assertEqual(doc['ocr']['ocr_pages'],1)
        self.assertIn('完成报名',doc['text'])


if __name__=='__main__':unittest.main()
