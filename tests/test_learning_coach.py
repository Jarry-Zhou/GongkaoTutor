import copy
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

from app import Application,UserError
import test_app
import learning_analysis as la
import learning_coach as coach


class CoachTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Application(self.tmp.name)
        self.qs=test_app.AppTests.seed(self,12)

    def tearDown(self):self.tmp.cleanup()

    def attempt(self,q=None,value='B',**kwargs):
        q=q or self.qs[0]
        s=self.app.create_session({'kind':'practice','question_ids':[q['id']],'count':1,'minutes':30})
        self.app.save_answer(s['id'],q['id'],{'value':[value],'reason':'把必要条件方向反过来了',**kwargs})
        return self.app.submit(s['id'])['attempts'][0]

    def answer(self,system,data,**kwargs):
        rows=data['new_evidence'];abilities=[];tasks=[];diags=[]
        for row in rows:
            q=row['question'];point=q['knowledge_points'][0]
            abilities.append({'name':'必要条件方向识别','stage':'relation','module':q['module'],'point':point,
                'hypothesis':'条件方向需要核验','fix':'先写B→A并用题干核对','evidence_attempt_ids':[row['attempt_id'],'fake']})
            tasks.append({'ability_name':'必要条件方向识别','stage':'relation','point':point,'attempt_id':row['attempt_id'],
                          'title':'用一步验证方向','prompts':['写出箭头关系','说明依据'],'reference':'B→A','hint':'从已成立的后件开始'})
            diags.append({'attempt_id':row['attempt_id'],'stage':'relation','observation':'方向假设','user_quote':'必要条件方向',
                'citations':[{'paragraph_id':'question','quote':'只有完成报名才能考试'},{'paragraph_id':'m1','quote':'虚构引文'}],
                'minimal_rewrite':'先看后件','explanation':'由已参加考试推出报名','next_question':'谁是必要条件？'})
        reviews=[{'task_id':r['id'],'answer_quote':r['answers'][0]['text'],'assessment':'pass','feedback':'箭头与条件对应。','next_step':'换未见题复测'} for r in data['coach_evidence']]
        return {'summary':'依据实际过程提出可检验假设。','common_causes':[], 'abilities':abilities,
                'training_tasks':tasks,'step_diagnostics':diags,'task_reviews':reviews}

    def analyze(self):
        p=la.preview(self.app,{})
        with patch.object(self.app,'model_call',side_effect=self.answer):
            return la.run(self.app,{'confirmed':True,'plan_token':p['plan_token']})

    def trained(self):
        self.attempt();self.analyze();t=self.app.store.all('coach_tasks')[0]
        coach.task_action(self.app,t['id'],'start',{})
        for i in range(len(t['prompts'])):coach.task_action(self.app,t['id'],'answer',{'stage_index':i,'text':'B推出A，因为A是必要条件'})
        return self.app.store.get('coach_tasks',t['id'])

    def test_arithmetic_is_bounded_and_checks_claim_not_semantics(self):
        r=coach.arithmetic('120/(1+20%)','100');self.assertEqual(r['value'],100);self.assertTrue(r['matches_claim'])
        self.assertFalse(coach.arithmetic('120/2','61')['matches_claim'])
        for expr in ['__import__("os")','(1).__class__','1/0','1e999','9**999','[1]*99','a+1','1+'*150+'1']:
            self.assertFalse(coach.arithmetic(expr)['available'],expr)

    def test_optional_steps_are_preserved_and_no_api_is_implicit(self):
        with patch.object(self.app,'model_call',side_effect=AssertionError('No consent')):
            a=self.attempt(steps={'relation':'B→A','formula':'120/2','result':'60','not_allowed':'bad'})
            p=la.preview(self.app,{});coach.overview(self.app)
        self.assertEqual(a['response']['steps'],{'relation':'B→A','formula':'120/2','result':'60'})
        self.assertEqual(p['pending_count'],1)

    def test_analysis_creates_linked_hypothesis_and_hides_training_reference(self):
        a=self.attempt();before={t:self.app.store.all(t) for t in ('questions','attempts','sessions','diagnoses')}
        r=self.analyze();ability=r['result']['abilities'][0];task=self.app.store.all('coach_tasks')[0]
        self.assertEqual(ability['evidence_attempt_ids'],[a['id']]);self.assertNotIn('state',ability)
        self.assertEqual(task['ability_id'],ability['id'])
        public=coach.task_public(self.app,task)
        self.assertNotIn('reference',public);self.assertNotIn('hint',public)
        self.assertNotIn('answer',public['question']);self.assertNotIn('explanation',public['question'])
        self.assertNotIn('reference',coach.overview(self.app)['tasks'][0])
        for t,rows in before.items():self.assertEqual(rows,self.app.store.all(t))

    def test_quotes_are_literal_and_unknown_citations_are_discarded(self):
        self.attempt();r=self.analyze();d=r['result']['step_diagnostics'][0]
        self.assertEqual(len(d['citations']),1);self.assertEqual(d['citations'][0]['paragraph_id'],'question')
        self.assertEqual(d['evidence_status'],'有过程证据')

    def test_partial_essay_has_explicit_coverage_and_no_full_assessment_task(self):
        q=self.qs[0];q.update(type='essay',module='申论',material='部门推进协同治理。\n'*5000,answer='',reference_optional=True)
        self.app.store.put('questions',q)
        s=self.app.create_session({'question_ids':[q['id']],'count':1,'kind':'practice','minutes':10})
        self.app.save_answer(s['id'],q['id'],{'value':'加强治理','reason':'必要条件方向'})
        self.app.submit(s['id']);r=self.analyze();d=r['result']['step_diagnostics'][0]
        self.assertEqual(d['coverage'],'partial');self.assertFalse(d['minimal_rewrite'])
        self.assertEqual(self.app.store.count('coach_tasks'),0)

    def test_material_tail_is_available_for_complete_essays(self):
        q={'type':'essay','material':('首段说明。\n'*1000)+'末段关键业务措施。'}
        b=coach.material_bundle(q)
        self.assertEqual(b['coverage'],'complete');self.assertIn('末段关键业务措施',b['paragraphs'][-1]['text'])

    def test_source_revision_invalidates_only_affected_attempt_without_regrading(self):
        a=self.attempt();b=self.attempt(self.qs[1]);self.analyze()
        before=copy.deepcopy(self.app.store.all('attempts'));q=self.qs[0];q['answer']=['B'];self.app.store.put('questions',q)
        p=la.plan(self.app,{});self.assertEqual([r[0]['id'] for r in p['pending']],[a['id']])
        state=coach.overview(self.app);self.assertEqual(state['abilities'][0]['state'],'待重新校验')
        with self.assertRaises(UserError):coach.retest(self.app,{'ability_id':state['abilities'][0]['id']})
        self.assertEqual(before,self.app.store.all('attempts'))

    def test_version_change_rechecks_cached_question_memory(self):
        self.attempt();self.analyze();q=self.qs[0];q['material']='新补充证据';self.app.store.put('questions',q)
        p=la.preview(self.app,{})
        with patch.object(self.app,'model_call',side_effect=self.answer) as model:
            la.run(self.app,{'confirmed':True,'plan_token':p['plan_token']})
        self.assertIn('stem',model.call_args.args[1]['new_evidence'][0]['question'])
        self.assertTrue(model.call_args.args[1]['new_evidence'][0]['source_changed_since_answer'])

    def test_stages_pause_resume_idempotency_and_hint_flag(self):
        self.attempt();self.analyze();tid=self.app.store.all('coach_tasks')[0]['id']
        with patch('learning_coach.time.time',return_value=100):coach.task_action(self.app,tid,'start',{})
        with patch('learning_coach.time.time',return_value=110):coach.task_action(self.app,tid,'pause',{})
        coach.task_action(self.app,tid,'draft',{'text':'草稿'})
        with patch('learning_coach.time.time',return_value=1000):coach.task_action(self.app,tid,'start',{})
        coach.task_action(self.app,tid,'hint',{})
        with patch('learning_coach.time.time',return_value=1005):r=coach.task_action(self.app,tid,'answer',{'stage_index':0,'text':'B→A'})
        self.assertEqual(r['answers'][0]['duration_seconds'],15);self.assertTrue(r['hint_used']);self.assertIn('hint',r)
        again=coach.task_action(self.app,tid,'answer',{'stage_index':0,'text':'重复提交'})
        self.assertEqual(len(again['answers']),1)
        done=coach.task_action(self.app,tid,'answer',{'stage_index':1,'text':'A为必要条件'})
        self.assertEqual(done['status'],'answered');self.assertIn('reference',done)

    def test_task_only_review_is_confirmed_incremental_and_restart_durable(self):
        t=self.trained();p=la.preview(self.app,{})
        self.assertEqual((p['batch_count'],p['task_count']),(0,1))
        with patch.object(self.app,'model_call',side_effect=AssertionError('No confirm')):
            with self.assertRaises(UserError):la.run(self.app,{'plan_token':p['plan_token']})
        with patch.object(self.app,'model_call',side_effect=self.answer) as model:
            result=la.run(self.app,{'confirmed':True,'plan_token':p['plan_token']})
        self.assertEqual(model.call_args.args[1]['new_evidence'],[])
        self.assertEqual(result['result']['task_reviews'][0]['task_id'],t['id'])
        restored=Application(self.tmp.name)
        self.assertEqual(la.preview(restored,{})['pending_count'],0)
        self.assertEqual(coach.overview(restored)['tasks'][0]['review']['assessment'],'pass')
        self.assertEqual(coach.overview(restored)['abilities'][0]['state'],'训练中')

    def test_invalid_or_failed_reviews_never_consume_pending_task(self):
        self.trained();prior=la.latest(self.app)['id'];p=la.preview(self.app,{})
        for response in [{'summary':'未引用回答','task_reviews':[]},{'summary':'伪造引用','task_reviews':[{'task_id':'fake','answer_quote':'伪造'}]}]:
            with patch.object(self.app,'model_call',return_value=response):
                with self.assertRaises(UserError):la.run(self.app,{'confirmed':True,'plan_token':p['plan_token']})
            self.assertEqual(la.latest(self.app)['id'],prior);self.assertEqual(la.preview(self.app,{})['task_count'],1)

    def test_stale_task_is_not_sent_and_cannot_be_continued(self):
        t=self.trained();q=self.qs[0];q['material']='修订原文';self.app.store.put('questions',q)
        self.assertEqual(la.preview(self.app,{})['task_count'],0)
        with self.assertRaises(UserError):coach.task_action(self.app,t['id'],'start',{})
        self.assertTrue(coach.overview(self.app)['tasks'][0]['stale'])

    def retest_answer(self,ability,value='A',hinted=False):
        s=coach.retest(self.app,{'ability_id':ability['id']});qid=s['questions'][0]['id']
        self.app.save_answer(s['id'],qid,{'value':[value],'hinted':hinted})
        return self.app.submit(s['id'])['attempts'][0]

    def test_retest_uses_unseen_matching_question_and_reuses_active_session(self):
        self.attempt();self.analyze();a=coach.overview(self.app)['abilities'][0]
        one=coach.retest(self.app,{'ability_id':a['id']});again=coach.retest(self.app,{'ability_id':a['id']})
        self.assertEqual(one['id'],again['id']);self.assertNotEqual(one['questions'][0]['id'],self.qs[0]['id'])
        self.assertEqual(one['spec']['knowledge'],a['point']);self.assertNotIn('answer',one['questions'][0])

    def test_two_same_day_correct_retests_do_not_claim_stability(self):
        self.attempt();self.analyze();a=coach.overview(self.app)['abilities'][0]
        self.retest_answer(a);self.retest_answer(a)
        result=coach.overview(self.app)['abilities'][0]
        self.assertEqual(result['state'],'暂时改善');self.assertFalse(result['due'])

    def test_delayed_independent_success_then_new_error_changes_state(self):
        self.attempt();self.analyze();a=coach.overview(self.app)['abilities'][0]
        first=self.retest_answer(a);second=self.retest_answer(a)
        second['created_at']=(datetime.fromisoformat(first['created_at'])+timedelta(days=1,seconds=1)).isoformat()
        self.app.store.put('attempts',second)
        self.assertEqual(coach.overview(self.app)['abilities'][0]['state'],'较稳定')
        third=self.retest_answer(a,'B');third['created_at']=(datetime.fromisoformat(second['created_at'])+timedelta(seconds=2)).isoformat();self.app.store.put('attempts',third)
        self.assertEqual(coach.overview(self.app)['abilities'][0]['state'],'复测中')

    def test_hint_success_does_not_advance_independent_mastery(self):
        self.attempt();self.analyze();a=coach.overview(self.app)['abilities'][0]
        self.retest_answer(a,hinted=True)
        self.assertEqual(coach.overview(self.app)['abilities'][0]['independent_successes'],0)

    def test_no_matching_inventory_does_not_fallback_to_random(self):
        self.attempt();self.analyze();a=coach.overview(self.app)['abilities'][0]
        for q in self.qs[1:]:q['status']='review';self.app.store.put('questions',q)
        with self.assertRaises(UserError):coach.retest(self.app,{'ability_id':a['id']})

    def test_malformed_model_ids_and_false_user_quotes_are_rejected(self):
        a=self.attempt();q=coach.current_question(self.app,a)
        row={'attempt_id':a['id'],'question':la.short_question(q),'reason':'真实过程','user_answer':'B',**coach.evidence_context(self.app,a,q)}
        structured,tasks=coach.structured_result(self.app,{'abilities':[{'stage':[]},{'stage':'relation','evidence_attempt_ids':['fake'],'name':'假设'}],
            'step_diagnostics':[{'attempt_id':[]},{'attempt_id':a['id'],'stage':{},'user_quote':'编造用户的话','citations':[{'paragraph_id':{},'quote':'abc'}]}],
            'training_tasks':[{'ability_id':[],'attempt_id':[]}]},None,[row])
        self.assertFalse(structured['abilities']);self.assertFalse(tasks)
        self.assertEqual(structured['step_diagnostics'][0]['evidence_status'],'待验证')

    def test_task_ledger_export_and_preview_have_no_hidden_reference(self):
        self.trained();export=self.app.dispatch('GET','/api/export',{})
        self.assertIn('coach_tasks',export);self.assertNotIn('settings',export)
        self.assertNotIn('coach_covered',la.preview(self.app,{})['latest'])

    def test_completed_task_answer_retries_do_not_rewrite_history(self):
        t=self.trained();original=copy.deepcopy(t)
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _:coach.task_action(self.app,t['id'],'answer',{'stage_index':0,'text':'重复'}),range(2)))
        self.assertEqual(self.app.store.get('coach_tasks',t['id']),original)

    def test_repeat_training_has_new_history_and_reuses_active_repeat(self):
        t=self.trained();one=coach.task_action(self.app,t['id'],'retry',{});two=coach.task_action(self.app,t['id'],'retry',{})
        self.assertEqual(one['id'],two['id']);self.assertNotEqual(one['id'],t['id'])
        self.assertEqual(one['answers'],[]);self.assertNotIn('reference',one)
        self.assertEqual(self.app.store.get('coach_tasks',t['id']),t)

    def test_adaptive_priority_uses_current_state_not_lifetime_wrong_count(self):
        self.attempt();self.analyze();ability=coach.overview(self.app)['abilities'][0]
        key=(ability['module'],ability['point']);self.assertEqual(coach.priority(self.app)[key],4)
        first=self.retest_answer(ability);second=self.retest_answer(ability)
        second['created_at']=(datetime.fromisoformat(first['created_at'])+timedelta(days=1,seconds=1)).isoformat();self.app.store.put('attempts',second)
        self.assertEqual(coach.priority(self.app)[key],0)

    def test_old_unrelated_ability_histories_are_not_resent_to_model(self):
        self.attempt();run=self.analyze();ability=run['result']['abilities'][0]
        previous=la.latest(self.app)
        self.assertEqual(coach.previous_abilities(previous,[],[]),[])
        result=coach.previous_abilities(previous,[],[({'ability_id':ability['id']},'fp')])
        self.assertEqual(result[0]['id'],ability['id']);self.assertNotIn('question_versions',result[0])

    def test_objective_option_quote_is_not_process_evidence(self):
        a=self.attempt(reason='');q=coach.current_question(self.app,a)
        row={'attempt_id':a['id'],'question':la.short_question(q),'reason':'','user_answer':['B'],**coach.evidence_context(self.app,a,q)}
        result,_=coach.structured_result(self.app,{'step_diagnostics':[{'attempt_id':a['id'],'user_quote':'B','observation':'方向反了'}]},None,[row])
        self.assertEqual(result['step_diagnostics'][0]['evidence_status'],'待验证')

    def test_corrected_retest_marks_review_then_clears_only_after_analysis(self):
        self.attempt();self.analyze();ability=coach.overview(self.app)['abilities'][0]
        r=self.retest_answer(ability)
        q=self.app.store.get('questions',r['question_id']);q['answer']=['B'];self.app.store.put('questions',q)
        state=coach.overview(self.app)['abilities'][0]
        self.assertEqual(state['state'],'待重新校验');self.assertEqual(state['independent_successes'],0)
        self.analyze();state=coach.overview(self.app)['abilities'][0]
        self.assertFalse(state['stale_question_ids']);self.assertEqual(state['independent_successes'],0)

    def test_new_ui_rejects_incomplete_coaching_schema_without_advancing(self):
        self.attempt();p=la.preview(self.app,{})
        with patch.object(self.app,'model_call',return_value={'summary':'只有旧版总结'}):
            with self.assertRaises(UserError):la.run(self.app,{'coach_version':1,'confirmed':True,'plan_token':p['plan_token']})
        self.assertEqual(la.preview(self.app,{})['pending_count'],1);self.assertEqual(self.app.store.count('learning_analyses'),0)


if __name__=='__main__':unittest.main()
