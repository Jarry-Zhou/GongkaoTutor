import copy
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from app import Application,UserError
import learning_analysis as la


class LearningAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Application(self.tmp.name)
        from test_app import AppTests
        self.qs=AppTests.seed(self,20)

    def tearDown(self):self.tmp.cleanup()

    def attempts(self,count=1,ids=None):
        spec={'kind':'practice','count':count,'minutes':30}
        if ids:spec['question_ids']=ids
        s=self.app.create_session(spec)
        for q in s['questions']:self.app.save_answer(s['id'],q['id'],{'value':['B'],'reason':'我将必要条件的方向反过来了'})
        return self.app.submit(s['id'])['attempts']

    def answer(self,system,data,**kwargs):
        return {'summary':'已有证据提示条件方向容易反转，需要继续验证。','common_causes':[{'cause':'方向反转','evidence_attempt_ids':[r['attempt_id'] for r in data['new_evidence']]+['fake'],
            'confidence':'有证据支持','fix':'从必要条件的后件开始列式。','verify':'用未见题复测。'}],
            'next_actions':['记录条件箭头'], 'question_notes':[{'question_id':r['question']['id'],'note':'已确认用户反转了本题必要条件方向。','can_reuse_without_image':True} for r in data['new_evidence']]}

    def run_analysis(self,**body):
        p=la.preview(self.app,body)
        return la.run(self.app,{**body,'confirmed':True,'plan_token':p['plan_token']})

    def test_122_preview_is_local_and_run_requires_confirmation(self):
        self.attempts()
        with patch.object(self.app,'model_call',side_effect=AssertionError('No consent')):
            self.assertEqual(la.preview(self.app,{})['pending_count'],1)
            with self.assertRaises(UserError):la.run(self.app,{})

    def test_123_first_result_is_durable_and_identical_request_never_calls_again(self):
        self.attempts(2);p=la.preview(self.app,{})
        with patch.object(self.app,'model_call',side_effect=self.answer) as model:
            first=la.run(self.app,{'confirmed':True,'plan_token':p['plan_token']})
            again=la.run(self.app,{'confirmed':True,'plan_token':p['plan_token']})
        self.assertEqual(model.call_count,1);self.assertTrue(again['reused']);self.assertEqual(first['id'],again['id'])
        restored=Application(self.tmp.name)
        with patch.object(restored,'model_call',side_effect=AssertionError('Saved result')):
            self.assertEqual(la.preview(restored,{})['latest']['id'],first['id'])

    def test_124_increment_only_sends_new_attempt_and_previous_conclusion(self):
        old=self.attempts(2)
        with patch.object(self.app,'model_call',side_effect=self.answer):first=self.run_analysis()
        new=self.attempts()[0]
        with patch.object(self.app,'model_call',side_effect=self.answer) as model:second=self.run_analysis()
        payload=model.call_args.args[1]
        self.assertEqual([r['attempt_id'] for r in payload['new_evidence']],[new['id']])
        self.assertEqual(payload['previous_conclusion']['summary'],first['result']['summary'])
        self.assertEqual(second['covered_count'],3);self.assertEqual(second['previous_id'],first['id'])
        self.assertEqual(self.app.store.count('learning_analyses'),2)

    def test_125_new_followup_is_a_revision_and_reuses_question_conclusion(self):
        a=self.attempts()[0]
        with patch.object(self.app,'model_call',side_effect=self.answer):self.run_analysis()
        d=self.app.store.get('diagnoses',a['id']);d['dialogue']=[{'role':'user','text':'现在明白B推出A。'}];self.app.store.put('diagnoses',d)
        p=la.preview(self.app,{});self.assertEqual((p['new_count'],p['revised_count']),(0,1))
        with patch.object(self.app,'model_call',side_effect=self.answer) as model:self.run_analysis()
        q=model.call_args.args[1]['new_evidence'][0]['question'];self.assertIn('previous_question_conclusion',q);self.assertNotIn('stem',q)

    def test_126_topic_and_global_entry_share_coverage(self):
        self.attempts()
        with patch.object(self.app,'model_call',side_effect=self.answer):self.run_analysis(point='必要条件')
        p=la.preview(self.app,{});self.assertEqual(p['pending_count'],0);self.assertEqual(p['covered_count'],1)

    def test_127_failed_model_does_not_advance_cursor_or_replace_previous_result(self):
        self.attempts()
        with patch.object(self.app,'model_call',side_effect=self.answer):first=self.run_analysis()
        self.attempts()
        with patch.object(self.app,'model_call',side_effect=UserError('Connection failed')):
            with self.assertRaises(UserError):self.run_analysis()
        p=la.preview(self.app,{});self.assertEqual(p['pending_count'],1);self.assertEqual(p['latest']['id'],first['id'])

    def test_128_stale_confirmation_is_rejected_before_api(self):
        self.attempts();p=la.preview(self.app,{});self.attempts()
        with patch.object(self.app,'model_call',side_effect=AssertionError('Stale scope')):
            with self.assertRaises(UserError):la.run(self.app,{'confirmed':True,'plan_token':p['plan_token']})

    def test_129_two_concurrent_clicks_share_one_model_result(self):
        self.attempts();p=la.preview(self.app,{});body={'confirmed':True,'plan_token':p['plan_token']}
        with patch.object(self.app,'model_call',side_effect=self.answer) as model:
            with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:la.run(self.app,body),range(2)))
        self.assertEqual(model.call_count,1);self.assertEqual(results[0]['id'],results[1]['id'])

    def test_130_empty_model_result_is_not_saved(self):
        self.attempts()
        with patch.object(self.app,'model_call',return_value={}):
            with self.assertRaises(UserError):self.run_analysis()
        self.assertEqual(la.preview(self.app,{})['pending_count'],1);self.assertEqual(self.app.store.count('learning_analyses'),0)

    def test_131_unknown_evidence_is_filtered_and_grades_are_untouched(self):
        self.attempts();before={t:self.app.store.all(t) for t in ('sessions','attempts','diagnoses')}
        with patch.object(self.app,'model_call',side_effect=self.answer):r=self.run_analysis()
        self.assertNotIn('fake',r['result']['common_causes'][0]['evidence_attempt_ids'])
        for t in before:self.assertEqual(before[t],self.app.store.all(t))

    def test_132_analysis_is_bounded_and_remaining_records_stay_pending(self):
        self.attempts(15)
        with patch.object(self.app,'model_call',side_effect=self.answer) as model:r=self.run_analysis()
        self.assertEqual(len(model.call_args.args[1]['new_evidence']),12);self.assertEqual(r['pending_count'],3)

    def test_133_legacy_topic_api_cannot_bypass_new_confirmation(self):
        self.attempts()
        with patch.object(self.app,'model_call',side_effect=AssertionError('Explicit confirmation needed')):
            with self.assertRaises(UserError):self.app.topic_explanation('必要条件',True)

    def test_134_duplicate_single_question_analysis_is_cached(self):
        a=self.attempts()[0]
        with patch.object(self.app,'model_call',return_value={'cause':'方向反转','explanation':'从B推出A','questions':[]}) as model:
            self.app.diagnosis(a,True);self.app.diagnosis(a,True)
        self.assertEqual(model.call_count,2) # First analysis + independent review only.

    def test_141_image_budget_limits_a_batch_before_any_api_call(self):
        self.app.store.put('settings',{'id':'model','base_url':'https://example.invalid','model':'mock','vision_model':'mock'})
        for q in self.qs:
            q.update(requires_image=True,reading_source={'material':[{'page':1,'text':'资料'}],'question':[{'page':1,'text':'题目'}]})
            self.app.store.put('questions',q)
        self.attempts(4);self.assertEqual(la.preview(self.app,{})['batch_count'],3)
        with patch('question_reading.model_images',return_value=['picture1','picture2']),patch.object(self.app,'model_call',side_effect=self.answer) as model:r=self.run_analysis()
        self.assertEqual(len(model.call_args.args[1]['_image_data']),6);self.assertEqual(r['pending_count'],1)

    def test_142_repeated_question_with_a_new_attempt_reuses_its_saved_note_and_image(self):
        self.app.store.put('settings',{'id':'model','base_url':'https://example.invalid','model':'mock','vision_model':'mock'})
        q=self.qs[0];q['requires_image']=True;self.app.store.put('questions',q)
        self.attempts(ids=[q['id']])
        with patch('question_reading.model_images',return_value=['cropped picture']) as image,patch.object(self.app,'model_call',side_effect=self.answer):self.run_analysis()
        self.assertEqual(image.call_count,1)
        self.attempts(ids=[q['id']])
        with patch('question_reading.model_images',side_effect=AssertionError('Already analyzed image')),patch.object(self.app,'model_call',side_effect=self.answer) as model:self.run_analysis()
        payload=model.call_args.args[1];self.assertEqual(payload['_image_data'],[])
        self.assertIn('previous_question_conclusion',payload['new_evidence'][0]['question'])

    def test_144_uncertain_figure_note_does_not_hide_images_for_a_new_attempt(self):
        self.app.store.put('settings',{'id':'model','base_url':'https://example.invalid','model':'mock','vision_model':'mock'})
        q=self.qs[0];q['requires_image']=True;self.app.store.put('questions',q)
        def uncertain(system,data,**kwargs):
            answer=self.answer(system,data,**kwargs)
            for note in answer['question_notes']:note['can_reuse_without_image']=False
            return answer
        self.attempts(ids=[q['id']])
        with patch('question_reading.model_images',return_value=['cropped picture']),patch.object(self.app,'model_call',side_effect=uncertain):self.run_analysis()
        self.attempts(ids=[q['id']])
        with patch('question_reading.model_images',return_value=['cropped picture']) as image,patch.object(self.app,'model_call',side_effect=uncertain):self.run_analysis()
        self.assertEqual(image.call_count,1)
