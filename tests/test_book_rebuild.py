import unittest,json
from unittest.mock import patch
from app import normalize_question,UserError
import file_pages,book_import,local_ocr

class BookRebuildTests(unittest.TestCase):
    def setUp(self):
        from test_page_assist import PageAssistTests
        PageAssistTests.setUp(self)

    def tearDown(self):
        self.a.queue.join();self.app.uploads.tasks.join();self.tmp.cleanup()

    def bank_pages(self):
        batch,item=self.app.uploads.require(self.bid,self.fid);item['purpose']='question_bank';self.app.store.put('file_imports',batch)
        texts=['1. 哪项符合完整条件？','A. 正确项\nB. 错误项','参考答案\n1：A']
        for n,t in enumerate(texts,1):file_pages.write_page(self.source,n,{'text':t,'method':'ocr','low_confidence_lines':0})

    def job(self,text,kind='content'):
        with patch.object(self.app,'model_call',return_value={'text':text,'page_kind':kind,'questions':[]}):
            j=self.a.create(self.bid,self.fid,{'pages':[2],'mode':'text'});self.a.queue.join()
        return self.a.require(j['id'])

    def test_90_blank_page_marker_does_not_consume_next_page(self):
        d=file_pages.split_pages('[第 1 页]\n第一段\n\n[第 2 页]\n\n[第 3 页]\n第三段')
        self.assertEqual(d[2].strip(),'');self.assertEqual(d[3],'第三段')

    def test_91_document_chunks_bridge_page_boundary_and_skip_blank(self):
        chunks=book_import.document_chunks('[第 1 页]\n本段前半句\n[第 2 页]\n\n[第 3 页]\n接着后半句。')
        self.assertIn('前半句接着后半句',chunks[0]['text']);self.assertEqual(chunks[0]['pages'],[1,3])

    def test_92_answer_ranges_inline_and_en_dash_are_not_shifted(self):
        keys=book_import.answer_sections([{'page':7,'text':'参考答案\n第一篇 练习\n1–3：ABC 4-5：DA（B）'}])
        self.assertEqual(keys[0]['answers'],{1:'A',2:'B',3:'C',4:'D',5:'A'})
        self.assertEqual(keys[0]['ambiguities'],{5:'A/B'})

    def test_93_book_questions_merge_continuation_and_end_key(self):
        rows,meta=book_import.parse_objective([{'page':1,'text':'封面'},{'page':2,'text':'第一篇 测试\n1. 完整的题干前半'},{'page':3,'text':'后半？\nA. 正确\nB. 错误'},{'page':4,'text':'参考答案\n第一篇 测试\n1：A'}])
        self.assertEqual(len(rows),1);self.assertIn('后半',rows[0]['stem']);self.assertEqual(rows[0]['answer'],['A']);self.assertEqual(rows[0]['source_pages'],[2,3])

    def test_94_chapter_number_resets_keep_distinct_answers(self):
        rows,_=book_import.parse_objective([{'page':1,'text':'封面'},{'page':2,'text':'第一篇 甲\n1. 甲题？\nA. 甲\nB. 乙\n第二篇 乙\n1. 乙题？\nA. 甲\nB. 乙'},{'page':3,'text':'参考答案\n第一篇 甲\n1：A\n第二篇 乙\n1：B'}])
        self.assertEqual([q['answer'] for q in rows],[['A'],['B']])

    def test_95_blank_confirmation_can_update_and_clear_false_failure(self):
        j=self.job('','blank');self.a.apply(j['id'],{'pages':[2],'reviewed':True})
        c=self.a.pages.catalog(self.bid,self.fid);self.assertFalse(c['pages'][1]['problem'])
        doc=self.app.store.all('documents')[0];self.assertEqual(doc['ocr']['blank_pages'],[2]);self.assertNotIn(2,doc['ocr']['empty_pages'])

    def test_96_bank_text_repair_rebuilds_using_other_cached_pages(self):
        self.bank_pages();j=self.job('A. 正确项\nB. 错误项')
        with patch.object(self.app,'read_file',side_effect=AssertionError('No full OCR')):
            adopted=self.a.apply(j['id'],{'pages':[2],'reviewed':True})
        preview=self.app.require('imports',adopted['import_id']);self.assertEqual(len(preview['items']),1)
        self.assertEqual(preview['items'][0]['answer'],['A']);self.assertEqual(preview['items'][0]['status'],'ready')

    def test_97_subjective_without_reference_can_be_practiced_and_stays_pending(self):
        p=self.app.preview_import({'rows':[{'stem':'根据资料归纳措施。要求不超过200字。','material':'可核验给定材料','type':'short','reference_optional':True,'answer':'','points':20}]})
        self.app.commit_import(p['id']);s=self.app.create_session({'kind':'practice','count':1});qid=s['questions'][0]['id']
        self.app.save_answer(s['id'],qid,{'value':'我的回答'});result=self.app.submit(s['id'])
        self.assertEqual(result['pending_score'],20);self.assertIsNone(result['attempts'][0]['correct'])

    def test_98_graphical_questions_same_stem_keep_different_origins(self):
        raw={'stem':'选择符合规律的图形','options':{'A':'图中A','B':'图中B'},'answer':'A','page_images':[{'batch_id':self.bid,'file_id':self.fid,'page':1}]}
        q=normalize_question({**raw,'origin_key':'first'});other=normalize_question({**raw,'origin_key':'second'})
        self.assertNotEqual(q['fingerprint'],other['fingerprint'])

    def test_99_disputed_book_answer_is_localized_and_not_in_exam(self):
        q=normalize_question({'stem':'有歧义的一题','options':{'A':'甲','B':'乙'},'answer':'A','answer_ambiguity':'原答案 A/B'})
        self.app.store.put('questions',q);self.assertEqual(self.app.pool({}),[])

    def test_100_rebuild_keeps_question_id_and_updates_origin_instead_of_duplicate(self):
        raw={'stem':'原题','options':{'A':'甲','B':'乙'},'answer':'A','origin_key':'stable'}
        p=self.app.preview_import({'rows':[raw]});self.app.commit_import(p['id']);old=self.app.store.all('questions')[0]
        p=self.app.preview_import({'rows':[{**raw,'stem':'校正后的原题','answer':'B'}]});self.app.commit_import(p['id'])
        qs=self.app.store.all('questions');self.assertEqual(len(qs),1);self.assertEqual(qs[0]['id'],old['id']);self.assertEqual(qs[0]['answer'],['B'])

    def test_101_empty_page_markers_cannot_create_fake_knowledge(self):
        with self.assertRaises(UserError):self.app.add_document({'text':'[第 1 页]\n\n[第 2 页]\n'})

    def test_102_classifier_batches_outputs_to_avoid_one_large_response(self):
        rows=[{'stem':'数量条件'+str(n),'options':{'A':'1','B':'2'},'answer':'A'} for n in range(41)]
        with patch.object(self.app,'model_call',return_value={'classifications':[]}) as model:self.app.preview_import({'rows':rows,'use_ai':True})
        self.assertEqual(model.call_count,3);self.assertTrue(all(len(c.args[1]['questions'])<=20 for c in model.call_args_list))

    def test_103_missing_document_can_be_created_from_accepted_pages(self):
        j=self.job('第二页修正正文');result=self.a.apply(j['id'],{'pages':[2],'reviewed':True})
        self.assertTrue(result['document_id']);self.assertEqual(self.app.store.count('documents'),1)

    def test_104_verified_subjective_quote_is_anchored_to_current_material(self):
        from library_rebuild import subjective_local
        rows=subjective_local([{'page':1,'text':'封面'},{'page':2,'text':'训练一\n资料1\n完整的跨页给定材料。\n\n请你根据资料1概括做法。（2025年）\n要求：准确，不超过200字。\n额外的页脚'}],{'1':{'stem':'请你根据资料1概括做法。(2025年)\n要求：准确，不超过200字。'}})
        self.assertEqual(len(rows),1);self.assertNotIn('页脚',rows[0]['stem']);self.assertIn('给定材料',rows[0]['material'])

    def test_105_explicit_answer_confirmation_can_resolve_book_ambiguity(self):
        q=normalize_question({'stem':'核对题','options':{'A':'甲','B':'乙'},'answer':'A','answer_ambiguity':'原答案A/B'})
        self.app.store.put('questions',q)
        updated=self.app.dispatch('PATCH','/api/questions/'+q['id'],{'answer':'B'})
        self.assertEqual(updated['status'],'ready');self.assertNotIn('answer_ambiguity',updated)

    def test_106_knowledge_reader_includes_next_nonblank_page_and_search_cross_page(self):
        doc=self.app.add_document({'title':'跨页知识','text':'[第 1 页]\n必要条件的前半句\n[第 2 页]\n\n[第 3 页]\n接着后半句。'})
        data=self.app.dispatch('POST','/api/documents/'+doc['id']+'/read',{'page':1})
        self.assertEqual([p['page'] for p in data['sections']],[1,3])
        result=self.app.dispatch('POST','/api/documents/'+doc['id']+'/search',{'query':'前半句接着后半句'})
        self.assertEqual(len(result['results']),1);self.assertIn('1—3',result['results'][0]['label'])

    def test_107_knowledge_reader_rejects_out_of_range_and_does_not_truncate_fulltext(self):
        doc=self.app.add_document({'title':'长知识','text':'[第 1 页]\n'+'完整段落。'*600})
        data=self.app.dispatch('POST','/api/documents/'+doc['id']+'/read',{'page':1})
        self.assertGreater(len(data['sections'][0]['text']),1200)
        with self.assertRaises(UserError):self.app.dispatch('POST','/api/documents/'+doc['id']+'/read',{'page':2})

    def test_108_search_opens_exact_matching_page_inside_a_cross_page_chunk(self):
        doc=self.app.add_document({'title':'跨多页知识','text':'[第 1 页]\n前文内容。\n[第 2 页]\n中间内容。\n[第 3 页]\n真正的必要条件出现在这一页。'})
        result=self.app.dispatch('POST','/api/documents/'+doc['id']+'/search',{'query':'必要条件'})
        self.assertEqual(result['results'][0]['page'],3);self.assertEqual(result['results'][0]['label'],'[第 3 页]')
