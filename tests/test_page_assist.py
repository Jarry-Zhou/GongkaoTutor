import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import Application,UserError,normalize_question
import file_pages


class PageAssistTests(unittest.TestCase):
    def setUp(self):
        from reportlab.pdfgen import canvas
        self.tmp=tempfile.TemporaryDirectory();self.app=Application(self.tmp.name);self.a=self.app.page_assist
        self.app.store.put('settings',{'id':'model','base_url':'https://example.com','model':'test-vision'})
        buf=io.BytesIO();c=canvas.Canvas(buf)
        for n in range(1,4):c.drawString(40,700,f'Original page {n}, necessary conditions and diagram content');c.showPage()
        c.save();data=buf.getvalue()
        batch=self.app.uploads.create({'files':[{'name':'pages.pdf','purpose':'document','size':len(data)}]})
        self.bid=batch['id'];self.fid=batch['files'][0]['id'];self.app.uploads.write_chunk(self.bid,self.fid,0,len(data),io.BytesIO(data))
        self.source=self.app.uploads.path_for(self.bid,self.fid)
        for n,text in [(1,'GOOD PAGE ONE'),(2,''),(3,'GOOD PAGE THREE')]:file_pages.write_page(self.source,n,{'text':text,'method':'ocr','low_confidence_lines':0})

    def tearDown(self):self.a.queue.join();self.app.uploads.tasks.join();self.tmp.cleanup()

    def job(self,pages=[2],mode='text',result=None):
        with patch.object(self.app,'model_call',return_value=result or {'text':'FIXED PAGE TWO','questions':[]}) as model:
            job=self.a.create(self.bid,self.fid,{'pages':pages,'mode':mode});self.a.queue.join()
        return self.a.require(job['id']),model

    def bank(self):
        batch,item=self.app.uploads.require(self.bid,self.fid);item['purpose']='question_bank';self.app.store.put('file_imports',batch)

    def test_73_selected_page_only_one_image_is_sent(self):
        job,model=self.job()
        self.assertEqual(model.call_count,1)
        data=model.call_args.args[1];self.assertEqual(data['page'],2);self.assertEqual(len(data['_image_data']),1)
        self.assertEqual(job['pages']['2']['status'],'ready')
        self.assertEqual(file_pages.page_path(self.source,1).read_text('utf-8').find('GOOD PAGE ONE')>=0,True)

    def test_74_apply_replaces_only_one_page_without_file_ocr(self):
        original='\n[第 1 页]\nGOOD PAGE ONE\n\n[第 2 页]\nBAD TWO\n\n[第 3 页]\nGOOD PAGE THREE\n'
        doc=self.app.add_document({'title':'Original document','text':original})
        self.app.uploads.update(self.bid,self.fid,status='completed',document_id=doc['id'])
        job,_=self.job()
        with patch.object(self.app,'read_file',side_effect=AssertionError('Whole file reparse forbidden')):
            applied=self.a.apply(job['id'],{'pages':[2],'reviewed':True})
        updated=self.app.store.get('documents',doc['id'])
        self.assertEqual(applied['document_id'],doc['id'])
        before=file_pages.split_pages(original);after=file_pages.split_pages(updated['text'])
        self.assertEqual(before[1],after[1]);self.assertEqual(before[3],after[3]);self.assertIn('FIXED PAGE TWO',after[2])
        self.assertEqual(self.app.store.count('documents'),1)

    def test_75_future_import_reads_accepted_override_without_local_ocr(self):
        job,_=self.job();self.a.apply(job['id'],{'pages':[2],'reviewed':True,'create_new':True})
        with patch('local_ocr.cached_recognize',side_effect=AssertionError('No scan OCR needed')):
            doc=self.app.add_document({'name':'pages.pdf','_source_path':self.source})
        self.assertIn('FIXED PAGE TWO',doc['text']);self.assertEqual(doc['ocr']['model_pages'],1)

    def test_76_failed_page_retry_does_not_repeat_other_pages(self):
        with patch.object(self.app,'model_call',side_effect=UserError('Provider unavailable')) as model:
            job=self.a.create(self.bid,self.fid,{'pages':[1,2]});self.a.queue.join();self.assertEqual(model.call_count,2)
        with patch.object(self.app,'model_call',return_value={'text':'Fixed only page 2'}) as model:
            self.a.retry(job['id'],{'pages':[2]});self.a.queue.join()
        updated=self.a.require(job['id']);self.assertEqual(model.call_count,1)
        self.assertEqual(updated['pages']['1']['status'],'error');self.assertEqual(updated['pages']['2']['status'],'ready')

    def test_77_local_crop_does_not_call_model_and_stays_in_preview(self):
        self.bank();job,model=self.job(mode='manual');self.assertEqual(model.call_count,0)
        q=job['pages']['2']['questions'][0]
        self.assertTrue(self.a.pages.asset_path(q['visual']['id']).is_file())
        applied=self.a.apply(job['id'],{'pages':[2],'reviewed':True})
        preview=self.app.require('imports',applied['import_id']);self.assertEqual(len(preview['items']),1)
        self.assertEqual(preview['items'][0]['status'],'review')
        self.assertEqual(self.app.store.count('questions'),0)
        self.a.commit(job['id']);self.assertEqual(self.app.store.count('questions'),1)

    def test_78_different_diagrams_are_not_deduplicated_as_same_question(self):
        raw={'stem':'观察图形','options':{'A':'图中A','B':'图中B'},'answer':'A','visual':{'id':'vis_'+'a'*32,'reviewed':True}}
        first=normalize_question(raw);second=normalize_question({**raw,'visual':{'id':'vis_'+'b'*32,'reviewed':True}})
        self.assertNotEqual(first['fingerprint'],second['fingerprint'])

    def test_79_invalid_crop_and_unreviewed_adoption_are_rejected(self):
        self.bank();job,_=self.job(mode='manual')
        with self.assertRaises(UserError):self.a.edit_question(job['id'],{'page':2,'index':0,'bbox':[800,0,200,500]})
        with self.assertRaises(UserError):self.a.apply(job['id'],{'pages':[2]})
        self.assertEqual(self.app.store.count('questions'),0)

    def test_80_invalid_selection_never_calls_model(self):
        with patch.object(self.app,'model_call') as model:
            for pages in [[],[0],[4],[True],list(range(1,12))]:
                with self.assertRaises(UserError):self.a.create(self.bid,self.fid,{'pages':pages})
        self.assertEqual(model.call_count,0)

    def test_81_deleted_file_cannot_be_sent_or_applied(self):
        job,_=self.job();self.app.uploads.remove(self.bid,self.fid)
        with self.assertRaises(UserError):self.a.create(self.bid,self.fid,{'pages':[2]})
        with self.assertRaises(UserError):self.a.apply(job['id'],{'pages':[2],'reviewed':True,'create_new':True})

    def test_82_busy_file_cannot_be_overwritten_by_repair(self):
        job,_=self.job();self.app.uploads.update(self.bid,self.fid,status='parsing')
        with self.assertRaises(UserError):self.a.apply(job['id'],{'pages':[2],'reviewed':True,'create_new':True})
        self.assertEqual(self.app.store.count('documents'),0)

    def test_83_apply_and_question_commit_are_idempotent(self):
        self.bank();job,_=self.job(mode='manual');body={'pages':[2],'reviewed':True}
        self.a.apply(job['id'],body);self.a.apply(job['id'],body);self.a.commit(job['id']);self.a.commit(job['id'])
        self.assertEqual(self.app.store.count('imports'),1);self.assertEqual(self.app.store.count('questions'),1)

    def test_84_visual_input_is_present_in_question_snapshot(self):
        self.bank();job,_=self.job(mode='manual')
        self.a.edit_question(job['id'],{'page':2,'index':0,'answer':'A','stem':'观察原图中的规律','bbox':[0,0,1000,600]})
        self.a.apply(job['id'],{'pages':[2],'reviewed':True});self.a.commit(job['id'])
        session=self.app.create_session({'kind':'practice','count':1,'minutes':10})
        self.assertIn('visual',session['questions'][0]);self.assertNotIn('answer',session['questions'][0])
        self.assertTrue(session['questions'][0]['visual']['reviewed'])

    def test_85_page_catalog_marks_empty_and_keeps_successful_text(self):
        data=self.a.pages.catalog(self.bid,self.fid)
        self.assertEqual([p['page'] for p in data['pages'] if p['problem']],[2])
        self.assertIn('GOOD PAGE ONE',data['pages'][0]['text_preview'])

    def test_86_model_answer_requires_explicit_human_entry(self):
        self.bank();job,_=self.job(mode='graphics',result={'text':'diagram','questions':[{'stem':'观察图形','bbox':[0,0,1000,700],'options':{'A':'图中A','B':'图中B'},'answer':['A']}]})
        q=job['pages']['2']['questions'][0]
        self.assertEqual(q['model_answer'],['A']);self.assertEqual(q['answer'],[])
        applied=self.a.apply(job['id'],{'pages':[2],'reviewed':True})
        candidate=self.app.require('imports',applied['import_id'])['items'][0]
        self.assertEqual(candidate['answer'],[]);self.assertEqual(candidate['status'],'review')

    def test_87_tiny_crop_is_rejected_without_writing_asset(self):
        self.bank();job,_=self.job(mode='manual')
        with self.assertRaises(UserError):self.a.edit_question(job['id'],{'page':2,'index':0,'bbox':[0,0,.01,.01]})

    def test_88_graphical_diagnosis_and_review_both_receive_original(self):
        self.bank();job,_=self.job(mode='manual')
        self.a.edit_question(job['id'],{'page':2,'index':0,'answer':'A'})
        self.a.apply(job['id'],{'pages':[2],'reviewed':True});self.a.commit(job['id'])
        self.app.store.put('settings',{'id':'model','base_url':'https://example.com','model':'text-main','vision_model':'test-vision','review_model':'text-review'})
        session=self.app.create_session({'kind':'practice','count':1,'minutes':10})
        qid=session['questions'][0]['id']
        self.app.save_answer(session['id'],qid,{'value':'B','reason':'我先数了圆形数量'})
        finished=self.app.submit(session['id'])
        with patch.object(self.app,'model_call',return_value={'explanation':'基于用户思路核对图形','questions':[]}) as model:
            self.app.diagnosis(finished['attempts'][0],use_ai=True)
        self.assertEqual(model.call_count,2)
        for call in model.call_args_list:
            self.assertEqual(len(call.args[1]['_image_data']),1)
            self.assertEqual(call.kwargs['model_override'],'test-vision')
            self.assertIn('我先数了圆形数量',call.args[1]['response']['reason'])

    def test_89_graphical_mode_does_not_fall_back_to_text_only_question(self):
        self.bank();job,_=self.job(mode='graphics',result={'text':'1. 图形题\nA. 第一项\nB. 第二项\n答案：A','questions':[]})
        with self.assertRaises(UserError):self.a.apply(job['id'],{'pages':[2],'reviewed':True})
        self.assertEqual(self.app.store.count('imports'),0)


if __name__=='__main__':unittest.main()
