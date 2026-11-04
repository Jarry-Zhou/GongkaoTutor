import copy
import json
import tempfile
import unittest
import base64
from pathlib import Path
from unittest.mock import patch

from app import Application,UserError
import learning_analysis as la
import shenlun as sl
import learning_coach as coach


class ShenlunTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Application(self.tmp.name)
        rows=[{'stem':f'【原创验收{i}】请概括服务中心的主要做法。（20分）要求：不超过200字。',
               'type':'essay','module':'申论','knowledge_points':['材料要点提取与归并'],'answer':'','reference_optional':True,
               'material':'中心建立居民需求台账。\n医生进行定期走访并跟进高风险居民。'} for i in range(6)]
        b=self.app.preview_import({'rows':rows});self.app.commit_import(b['id']);self.qs=self.app.store.all('questions')

    def tearDown(self):self.tmp.cleanup()

    def attempt(self,q=None,value='中心建立台账。',**response):
        q=q or self.qs[0];s=self.app.create_session({'count':1,'minutes':30,'kind':'practice','question_ids':[q['id']]})
        self.app.save_answer(s['id'],q['id'],{'value':value,**response})
        return self.app.submit(s['id'])['attempts'][0]

    def answer(self,system,data,**kwargs):
        reviews=[]
        for r in data['new_evidence']:
            if not r.get('shenlun'):continue
            user=r['user_answer'];ps=r['material_bundle']['paragraphs']
            one={'paragraph_id':ps[0]['id'],'quote':ps[0]['text']};two={'paragraph_id':ps[-1]['id'],'quote':ps[-1]['text']}
            reviews.append({'attempt_id':r['attempt_id'],'total_score':999,
                'points':[{'id':'p1','label':'建立需求台账','citations':[one],'verdict':'covered','user_quote':user,'explanation':'已写台账','improve':'明确需求台账的用途','max_score':10,'awarded':10},
                          {'id':'p2','label':'医生定期跟进','citations':[two],'verdict':'missing','user_quote':'','explanation':'未表达跟进机制','improve':'补足主体与跟进关系','max_score':10,'awarded':0}],
                'findings':[{'code':'A1','point_ids':['p2'],'description':'遗漏医生跟进的关系','user_quote':'','action':'圈出材料中的主体和行为，再逐项核对。','cause':'知识盲区'}],
                'reference_versions':[{'text':'建立需求台账。安排医生定期走访并跟进高风险居民。','citations':[one,two]},
                                      {'text':'需求摸排：建台账。服务跟进：医生走访并重点照护。','citations':[one,two]}],
                'comparison':'第一版紧凑归并，第二版按需求与服务分层；本次先补全跟进关系。',
                'rewrites':[{'original':user,'replacement':'中心建立需求台账，医生定期走访并跟进高风险居民。','why':'补足谁做什么','citations':[one,two]}],
                'theme_type':'单主题','structure':[{'user_quote':user,'claim':'需求识别','mechanism':'由台账支持服务','fix':'交代台账如何用于跟进'}],
                'advice':['先补全材料要素，再压缩句子。']})
        return {'summary':'【模拟】根据本次申论回答核对材料。','common_causes':[],'abilities':[],
                'step_diagnostics':[],'training_tasks':[],'task_reviews':[],'shenlun_reviews':reviews}

    def analyze(self,model=None,**body):
        payload={'domain':'shenlun','shenlun_version':1,'coach_version':1,**body};p=la.preview(self.app,payload)
        with patch.object(self.app,'model_call',side_effect=model or self.answer) as m:
            result=la.run(self.app,{**payload,'confirmed':True,'plan_token':p['plan_token']})
        return result,m

    def test_pinned_package_is_intact_and_methods_load_by_kind(self):
        state=sl.status();self.assertTrue(state['ready']);self.assertEqual(state['commit'],'354341cdce1f357bb78c24f05a929a339cd7f4cf')
        small=sl.method_packet({'summary'});large=sl.method_packet({'essay'})
        self.assertTrue(small['sections']);self.assertTrue(large['sections'])
        self.assertFalse(any('yuan-dong' in s['source'] for s in small['sections']))
        self.assertFalse(any('xiaoma' in s['source'] for s in large['sections']))
        self.assertNotIn('B4',small['allowed_loss_codes']);self.assertNotIn('H2',small['allowed_loss_codes'])

    def test_router_recognizes_task_instead_of_essay_storage_type(self):
        cases={'请归纳有关做法。':'summary','谈谈你对这句话的理解。':'analysis','提出改进\n建议。':'proposal',
               '请写一份调研报告提纲。':'document','自选角度，自拟题目，写一篇文章。':'essay','依据资料作答。':'unknown'}
        for stem,kind in cases.items():self.assertEqual(sl.classify({'stem':stem,'type':'essay'}),kind)

    def test_question_points_default_one_is_not_real_essay_score(self):
        q=copy.deepcopy(self.qs[0]);q['stem']='请概括主要做法。';q['points']=1
        self.assertIsNone(sl.context(self.app,q)['max_score'])
        q['stem']='请概括主要做法。（15分）不超过250字。';ctx=sl.context(self.app,q)
        self.assertEqual((ctx['max_score'],ctx['word_max']),(15,250))

    def test_character_constraints_are_explicit_not_mechanical_percentages(self):
        q=copy.deepcopy(self.qs[0]);q['stem']='写一篇文章，1000—1200字。';ctx=sl.context(self.app,q)
        self.assertEqual((ctx['word_min'],ctx['word_max']),(1000,1200))
        q['stem']='写一篇文章，1000字左右。';self.assertIsNone(sl.context(self.app,q)['word_min'])
        self.assertEqual(sl.nonspace('台账，\n 医生。'),6)

    def test_context_save_changes_only_new_table_and_validates_ranges(self):
        q=self.qs[0];before={t:self.app.store.all(t) for t in ('questions','sessions','attempts','settings')}
        ctx=sl.save_context(self.app,q['id'],{'kind':'document','max_score':25,'word_min':100,'word_max':300})
        self.assertEqual((ctx['kind'],ctx['max_score'],ctx['score_source']),('document',25,'用户确认'))
        original=self.app.store.all('shenlun_contexts')
        for body in [{'word_min':400,'word_max':200},{'max_score':float('nan')},{'word_max':-1},{'kind':[]},{'max_score':True}]:
            with self.assertRaises(UserError):sl.save_context(self.app,q['id'],body)
        self.assertEqual(original,self.app.store.all('shenlun_contexts'))
        for table,rows in before.items():self.assertEqual(rows,self.app.store.all(table))

    def test_practice_filter_uses_local_task_classification(self):
        q=self.qs[0];sl.save_context(self.app,q['id'],{'kind':'essay'})
        pool=self.app.pool({'shenlun_only':True,'shenlun_kind':'essay'})
        self.assertEqual([r['id'] for r in pool],[q['id']])

    def test_score_is_program_sum_not_model_total_and_grades_are_immutable(self):
        self.attempt();before={t:self.app.store.all(t) for t in ('questions','sessions','attempts','diagnoses','documents','settings')}
        result,model=self.analyze();review=result['result']['shenlun_reviews'][0]
        self.assertEqual(review['score']['value'],10);self.assertEqual(review['score']['max_score'],20)
        self.assertEqual(len(review['reference_versions']),2);self.assertEqual(review['findings'][0]['cause'],'暂不确定')
        self.assertTrue(model.call_args.args[1]['shenlun_method']['sections'])
        for t,rows in before.items():self.assertEqual(rows,self.app.store.all(t))

    def test_bad_allocation_and_negative_awards_never_produce_score(self):
        self.attempt()
        for value in (11,-1,50):
            def invalid(system,data,**kw):
                out=self.answer(system,data);out['shenlun_reviews'][0]['points'][1]['awarded']=value
                return out
            p=la.preview(self.app,{'domain':'shenlun'})
            with patch.object(self.app,'model_call',side_effect=invalid):r=la.run(self.app,{'domain':'shenlun','confirmed':True,'plan_token':p['plan_token']})
            self.assertFalse(r['result']['shenlun_reviews'][0]['score']['available'])
            d=self.app.store.get('diagnoses',self.app.store.all('attempts')[0]['id']);d['feedback']='重新核对 '+str(value);self.app.store.put('diagnoses',d)

    def test_missing_maximum_and_unknown_kind_never_default_to_forty(self):
        q=self.qs[0];q['stem']='依材料作答。';self.app.store.put('questions',q);self.attempt(q)
        result,_=self.analyze();review=result['result']['shenlun_reviews'][0]
        self.assertFalse(review['score']['available']);self.assertEqual(review['reference_versions'],[])
        self.assertIsNone(review['context']['max_score'])
        self.assertTrue(all('awarded' not in p for p in review['points']))

    def test_essay_gets_argument_feedback_without_unvalidated_numeric_grade(self):
        q=self.qs[0];sl.save_context(self.app,q['id'],{'kind':'essay','max_score':40});self.attempt(q)
        result,_=self.analyze();review=result['result']['shenlun_reviews'][0]
        self.assertFalse(review['score']['available']);self.assertTrue(review['structure']);self.assertEqual(review['reference_versions'],[])
        self.assertTrue(all('awarded' not in p for p in review['points']))

    def test_partial_material_cannot_be_used_to_assert_omissions_or_score(self):
        q=self.qs[0];q['material']='中心建立居民需求台账。\n医生进行定期走访。\n'+'其他内容。\n'*8000;self.app.store.put('questions',q);self.attempt(q)
        result,_=self.analyze();review=result['result']['shenlun_reviews'][0]
        self.assertFalse(review['complete']);self.assertFalse(review['score']['available']);self.assertFalse(review['findings']);self.assertFalse(review['reference_versions'])
        self.assertTrue(all(p['verdict']=='uncertain' for p in review['points']))

    def test_fake_material_citations_do_not_complete_analysis(self):
        self.attempt();p=la.preview(self.app,{'domain':'shenlun'})
        def fake(system,data,**kw):
            out=self.answer(system,data)
            for point in out['shenlun_reviews'][0]['points']:point['citations']=[{'paragraph_id':'m1','quote':'虚构的内容'}]
            return out
        with patch.object(self.app,'model_call',side_effect=fake):
            with self.assertRaises(UserError):la.run(self.app,{'domain':'shenlun','confirmed':True,'plan_token':p['plan_token']})
        self.assertEqual(la.preview(self.app,{'domain':'shenlun'})['pending_count'],1);self.assertEqual(self.app.store.count('learning_analyses'),0)

    def test_fake_user_quotes_are_uncertain_and_cannot_count_as_loss(self):
        self.attempt()
        def fake(system,data,**kw):
            out=self.answer(system,data);r=out['shenlun_reviews'][0]
            r['points'][0]['user_quote']='编造的用户原话';r['findings'][0]['user_quote']='编造的用户原话'
            r['rewrites'][0]['original']='编造的用户原话';return out
        result,_=self.analyze(fake);review=result['result']['shenlun_reviews'][0]
        self.assertEqual(review['points'][0]['verdict'],'uncertain');self.assertFalse(review['score']['available']);self.assertFalse(review['findings']);self.assertFalse(review['rewrites'])

    def test_disproved_codes_false_word_violation_and_invented_cause_are_filtered(self):
        self.attempt()
        def fake(system,data,**kw):
            out=self.answer(system,data);r=out['shenlun_reviews'][0];f=r['findings'][0]
            r['findings']=[{**f,'code':code} for code in ('B4','H2','C1','D4','F2','A1')];return out
        result,_=self.analyze(fake);findings=result['result']['shenlun_reviews'][0]['findings']
        self.assertEqual([f['code'] for f in findings],['A1']);self.assertEqual(findings[0]['cause'],'暂不确定')

    def test_two_different_questions_recur_same_question_regrading_does_not(self):
        self.attempt();self.analyze();self.attempt();self.analyze()
        state=sl.overview(self.app);self.assertEqual(state['losses'][0]['count'],1);self.assertEqual(len(state['history']),2)
        self.attempt(self.qs[1]);self.analyze();state=sl.overview(self.app)
        self.assertEqual(state['losses'][0]['count'],2);self.assertEqual(state['losses'][0]['state'],'复发')

    def test_dismissal_restore_and_feedback_are_local_and_preserve_reports(self):
        self.attempt();self.analyze();self.attempt(self.qs[1]);self.analyze()
        before=self.app.store.all('learning_analyses');f=sl.overview(self.app)['reviews'][0]['findings'][0]
        with patch.object(self.app,'model_call',side_effect=AssertionError('No paid call')):
            sl.finding_feedback(self.app,f['id'],{'dismissed':True,'reason':'同义表达已包含这一点。'})
            self.assertEqual(sl.overview(self.app)['losses'][0]['count'],1)
            self.assertFalse(sl.overview(self.app)['reviews'][0]['score']['available'])
            sl.finding_feedback(self.app,f['id'],{'dismissed':False,'reason':'核对后确实漏了这一点。'})
            self.assertEqual(sl.overview(self.app)['losses'][0]['count'],2)
            self.assertTrue(sl.overview(self.app)['reviews'][0]['score']['available'])
        self.assertEqual(before,self.app.store.all('learning_analyses'));self.assertEqual(self.app.store.count('shenlun_feedback'),2)
        self.assertEqual(la.preview(self.app,{'domain':'shenlun'})['revised_count'],1)

    def test_material_revision_marks_only_affected_report_stale(self):
        self.attempt();self.attempt(self.qs[1]);self.analyze();q=self.qs[0];q['material']='新修订材料';self.app.store.put('questions',q)
        state=sl.overview(self.app);self.assertEqual(sum(r['stale'] for r in state['reviews']),1)
        self.assertEqual(state['losses'][0]['count'],1);self.assertEqual(la.preview(self.app,{'domain':'shenlun'})['revised_count'],1)

    def test_context_change_invalidates_confirmation_before_any_api(self):
        self.attempt();p=la.preview(self.app,{'domain':'shenlun'})
        sl.save_context(self.app,self.qs[0]['id'],{'max_score':25})
        with patch.object(self.app,'model_call',side_effect=AssertionError('Stale confirmation')):
            with self.assertRaises(UserError):la.run(self.app,{'domain':'shenlun','confirmed':True,'plan_token':p['plan_token']})

    def test_shared_global_ledger_does_not_send_unrelated_objective_records(self):
        self.attempt();b=self.app.preview_import({'rows':[{'stem':'原创客观题','options':{'A':'是','B':'否'},'answer':['A'],'module':'常识判断'}]});self.app.commit_import(b['id'])
        objective=next(q for q in self.app.store.all('questions') if q['module']=='常识判断')
        s=self.app.create_session({'count':1,'question_ids':[objective['id']]});self.app.save_answer(s['id'],objective['id'],{'value':['B']});self.app.submit(s['id'])
        self.assertEqual(la.preview(self.app,{'domain':'shenlun'})['new_count'],1)
        _,model=self.analyze();self.assertEqual(len(model.call_args.args[1]['new_evidence']),1)
        self.assertEqual(la.preview(self.app,{'shenlun_version':1})['new_count'],1)

    def test_no_new_evidence_reuses_saved_result_with_zero_calls(self):
        self.attempt();result,_=self.analyze();p=la.preview(self.app,{'domain':'shenlun'})
        with patch.object(self.app,'model_call',side_effect=AssertionError('Cache')):
            again=la.run(self.app,{'domain':'shenlun','confirmed':True,'plan_token':p['plan_token']})
        self.assertEqual(again['id'],result['id']);self.assertTrue(again['reused'])

    def test_new_answer_to_same_question_keeps_full_material_without_old_answer(self):
        self.attempt(value='第一次回答。');self.analyze();new=self.attempt(value='第二次回答。')
        _,model=self.analyze();rows=model.call_args.args[1]['new_evidence']
        self.assertEqual([r['attempt_id'] for r in rows],[new['id']]);self.assertEqual(rows[0]['material_bundle']['coverage'],'complete')
        self.assertNotIn('第一次回答。',json.dumps(rows,ensure_ascii=False))

    def test_missing_review_and_connection_failure_do_not_advance_ledger(self):
        self.attempt();p=la.preview(self.app,{'domain':'shenlun'})
        for result in ({'summary':'缺失报告','abilities':[],'step_diagnostics':[],'training_tasks':[],'task_reviews':[]},):
            with patch.object(self.app,'model_call',return_value=result):
                with self.assertRaises(UserError):la.run(self.app,{'domain':'shenlun','confirmed':True,'plan_token':p['plan_token']})
        self.assertEqual(la.preview(self.app,{'domain':'shenlun'})['pending_count'],1)

    def test_previews_are_local_and_consent_is_required(self):
        self.attempt()
        with patch.object(self.app,'model_call',side_effect=AssertionError('No consent')):
            sl.overview(self.app);p=la.preview(self.app,{'domain':'shenlun'})
            with self.assertRaises(UserError):la.run(self.app,{'domain':'shenlun','plan_token':p['plan_token']})

    def test_package_failure_stops_before_api_and_keeps_pending(self):
        self.attempt();p=la.preview(self.app,{'domain':'shenlun'})
        with patch('shenlun.method_packet',side_effect=ValueError('Integrity')),patch.object(self.app,'model_call',side_effect=AssertionError('Invalid package')):
            with self.assertRaises(UserError):la.run(self.app,{'domain':'shenlun','confirmed':True,'plan_token':p['plan_token']})
        self.assertEqual(la.preview(self.app,{'domain':'shenlun'})['pending_count'],1)

    def test_batch_is_bounded_and_unprocessed_answers_remain_pending(self):
        for q in self.qs[:4]:self.attempt(q)
        p=la.preview(self.app,{'domain':'shenlun'});self.assertEqual((p['batch_count'],p['pending_count']),(2,4))
        result,_=self.analyze();self.assertEqual(result['pending_count'],2)

    def test_legacy_single_question_ai_cannot_bypass_specialized_confirmation(self):
        a=self.attempt()
        with patch.object(self.app,'model_call',side_effect=AssertionError('Use new ledger')):
            with self.assertRaises(UserError):self.app.diagnosis(a,True)

    def test_export_and_restart_keep_new_records_without_credentials(self):
        self.attempt();self.analyze();sl.save_context(self.app,self.qs[0]['id'],{'word_max':150})
        restored=Application(self.tmp.name);current=sl.overview(restored)['reviews'][0]
        self.assertTrue(current['stale']);self.assertFalse(current['score']['available'])
        exported=restored.dispatch('GET','/api/export',{})
        self.assertIn('shenlun_contexts',exported);self.assertIn('shenlun_feedback',exported);self.assertNotIn('settings',exported)

    def test_dismissed_same_attempt_finding_is_not_silently_readded_by_model(self):
        self.attempt();self.analyze();f=sl.overview(self.app)['reviews'][0]['findings'][0]
        sl.finding_feedback(self.app,f['id'],{'dismissed':True,'reason':'同义表达已覆盖，撤销误判。'})
        result,_=self.analyze();self.assertFalse(result['result']['shenlun_reviews'][0]['findings'])
        self.assertFalse(sl.overview(self.app)['losses'])

    def image_attempt(self):
        self.app.store.put('settings',{'id':'model','base_url':'https://example.invalid','model':'mock','vision_model':'mock'})
        raw='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRzQAAAAASUVORK5CYII='
        attachment=self.app.dispatch('POST','/api/evidence',{'name':'验收草稿.png','data':raw})
        return self.attempt(value='',attachments=[attachment])

    def transcribe(self,system,data,**kwargs):
        out=self.answer(system,data)
        out['shenlun_reviews']=[{'attempt_id':r['attempt_id'],'transcription':'中心建立台账。'} for r in data['new_evidence']]
        return out

    def test_handwriting_first_transcribes_without_grade_or_loss(self):
        a=self.image_attempt();p=la.preview(self.app,{'domain':'shenlun'})
        self.assertEqual(p['answer_images'],1)
        result,model=self.analyze(self.transcribe);review=result['result']['shenlun_reviews'][0]
        self.assertTrue(review['transcription_pending']);self.assertFalse(review['score']['available']);self.assertFalse(review['findings'])
        payload=model.call_args.args[1];self.assertEqual(len(payload['_image_data']),1)
        self.assertEqual(payload['new_evidence'][0]['answer_image_indexes'],[1])
        self.assertEqual(payload['new_evidence'][0]['image_indexes'],[])

    def test_confirmed_transcription_is_new_evidence_and_reuses_without_old_image(self):
        a=self.image_attempt();self.analyze(self.transcribe);before=copy.deepcopy(self.app.store.get('attempts',a['id']))
        sl.confirm_transcription(self.app,a['id'],{'confirmed':True,'text':'中心建立台账。'})
        record=self.app.store.get('shenlun_transcriptions',a['id'])
        sl.confirm_transcription(self.app,a['id'],{'confirmed':True,'text':'中心建立台账。'})
        self.assertEqual(record,self.app.store.get('shenlun_transcriptions',a['id']))
        p=la.preview(self.app,{'domain':'shenlun'});self.assertEqual((p['revised_count'],p['answer_images']),(1,0))
        result,model=self.analyze();self.assertEqual(model.call_args.args[1]['new_evidence'][0]['user_answer'],'中心建立台账。')
        self.assertEqual(model.call_args.args[1]['_image_data'],[]);self.assertTrue(result['result']['shenlun_reviews'][0]['score']['available'])
        self.assertEqual(before,self.app.store.get('attempts',a['id']))

    def test_transcription_cannot_be_adopted_without_explicit_confirmation(self):
        a=self.image_attempt()
        with self.assertRaises(UserError):sl.confirm_transcription(self.app,a['id'],{'text':'默认不能确认'})
        self.assertEqual(self.app.store.count('shenlun_transcriptions'),0)

    def test_missing_handwritten_file_blocks_api_and_keeps_cursor(self):
        a=self.image_attempt();attachment=a['response']['attachments'][0]
        (self.app.store.folder/'evidence'/attachment['id']).unlink()
        p=la.preview(self.app,{'domain':'shenlun'})
        with patch.object(self.app,'model_call',side_effect=AssertionError('Missing original draft')):
            with self.assertRaises(UserError):la.run(self.app,{'domain':'shenlun','confirmed':True,'plan_token':p['plan_token']})
        self.assertEqual(self.app.store.count('learning_analyses'),0)

    def test_missing_transcription_does_not_mark_image_answer_covered(self):
        self.image_attempt();p=la.preview(self.app,{'domain':'shenlun'})
        with patch.object(self.app,'model_call',side_effect=self.answer):
            with self.assertRaises(UserError):la.run(self.app,{'domain':'shenlun','confirmed':True,'plan_token':p['plan_token']})
        self.assertEqual(la.preview(self.app,{'domain':'shenlun'})['pending_count'],1)


if __name__=='__main__':unittest.main()
