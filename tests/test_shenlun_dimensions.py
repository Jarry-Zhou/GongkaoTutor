import copy
import tempfile
import unittest
from unittest.mock import patch
from app import Application,UserError
import learning_analysis as la
import learning_coach as coach
import shenlun
import shenlun_dimensions as sd
import test_shenlun


class DimensionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Application(self.tmp.name)
        rows=[{'stem':f'【维度验收{i}】概括中心的服务做法。（20分）不超过200字。','type':'essay','module':'申论',
            'knowledge_points':['材料要点提取与归并'],'answer':'','reference_optional':True,
            'material':'中心建立居民需求台账。\n医生进行定期走访并跟进高风险居民。'} for i in range(5)]
        b=self.app.preview_import({'rows':rows});self.app.commit_import(b['id']);self.qs=self.app.store.all('questions')
        self.judgments={'structure':'weak','thesis':'weak','business':'weak','efficiency':'weak'}

    def tearDown(self):self.tmp.cleanup()

    def attempt(self,q=None,**response):
        q=q or self.qs[0];s=self.app.create_session({'kind':'practice','count':1,'minutes':30,'question_ids':[q['id']]})
        self.app.save_answer(s['id'],q['id'],{'value':'加强服务。\n中心建立台账，各方继续努力。',**response})
        return self.app.submit(s['id'])['attempts'][0]

    def answer(self,system,data,**kwargs):
        result=test_shenlun.ShenlunTests.answer(None,system,data);observations=[]
        evidence={r['attempt_id']:r for r in data['new_evidence']};tasks={r['id']:r for r in data['coach_evidence']}
        for source in data['dimension_sources']:
            kind,sid=source['source_ref'].split(':',1)
            row=evidence[sid] if kind=='attempt' else tasks[sid]
            value=str(row['user_answer']) if kind=='attempt' else '\n'.join(a['text'] for a in row['answers'])
            process='\n'.join([row.get('reason','')]+list(row.get('steps',{}).values())) if kind=='attempt' else value
            p=row['material_bundle']['paragraphs'][0]
            for dim,judgment in self.judgments.items():
                observations.append({'dimension':dim,'source_ref':source['source_ref'],'judgment':judgment,
                    'observation':'【模拟】'+sd.DIMENSIONS[dim]['name']+'需结合具体表达验证。',
                    'user_quote':value.splitlines()[0],'process_quote':process[:80],
                    'citations':[{'paragraph_id':p['id'],'quote':p['text']}],
                    'action':'先区分主体与做法，再用一句话概括关系。','verify':'请指出本题的主体和行为如何对应。',
                    'verification_prompts':['写出本题主体。','用一句话说明做法与对象的关系。'],
                    'reference':'根据已提供材料核对主体、行为和服务对象。'})
        conclusions=[]
        for dim in self.judgments:
            previous=next((x for x in data['shenlun_dimensions']['previous_dimensions'] if x['dimension']==dim),{})
            refs=[o['source_ref'] for o in observations if o['dimension']==dim]+[e['source_ref'] for e in previous.get('evidence',[])]
            conclusions.append({'dimension':dim,'summary':'【模拟】从已记录作答中比较该维度具体表现。','evidence_refs':refs,
                'change':'保留旧结论，结合本批表现验证。','next_step':'用新材料完成同一步骤。'})
        result.update(shenlun_dimension_observations=observations,shenlun_dimension_conclusions=conclusions)
        result['task_reviews']=[{'task_id':t['id'],'answer_quote':t['answers'][0]['text'],'assessment':'pass',
            'feedback':'【模拟】已收到短训练回答。','next_step':'换新题验证。'} for t in data['coach_evidence']]
        return result

    def analyze(self,model=None,**extra):
        body={'shenlun_version':1,'shenlun_dimensions_version':1,'coach_version':1,**extra};p=la.preview(self.app,body)
        with patch.object(self.app,'model_call',side_effect=model or self.answer) as m:
            result=la.run(self.app,{**body,'confirmed':True,'plan_token':p['plan_token']})
        return result,m

    def card(self,dim):return next(c for c in sd.overview(self.app)['dimensions'] if c['dimension']==dim)

    def test_empty_profile_has_seven_dimensions_without_invented_weaknesses(self):
        profile=sd.overview(self.app);self.assertEqual(len(profile['dimensions']),7)
        self.assertEqual(profile['questions'],0);self.assertTrue(all(c['state']=='证据不足' and c['conclusion'] is None for c in profile['dimensions']))

    def test_global_analysis_contains_shenlun_and_objective_without_cross_attribution(self):
        self.attempt();b=self.app.preview_import({'rows':[{'stem':'原创客观题','module':'判断推理','options':{'A':'是','B':'否'},'answer':['A']}]});self.app.commit_import(b['id'])
        q=next(q for q in self.app.store.all('questions') if q['type']=='single');s=self.app.create_session({'count':1,'question_ids':[q['id']]})
        self.app.save_answer(s['id'],q['id'],{'value':['B']});self.app.submit(s['id'])
        result,model=self.analyze();payload=model.call_args.args[1]
        self.assertEqual(len(payload['new_evidence']),2);self.assertEqual(len(payload['dimension_sources']),1)
        self.assertEqual(result['result']['shenlun_dimension_profile']['questions'],1)
        self.assertEqual(self.card('structure')['state'],'单题信号')

    def test_business_without_process_evidence_is_only_a_hypothesis(self):
        self.attempt();self.analyze();card=self.card('business')
        self.assertEqual(card['state'],'待验证');self.assertEqual(card['weak_questions'],0)
        self.assertEqual(card['observations'][0]['judgment'],'uncertain')

    def test_explicit_business_process_can_support_a_business_signal(self):
        self.attempt(steps={'business':'我认为医生只负责开药，不需要走访。'});self.analyze();card=self.card('business')
        self.assertEqual(card['state'],'单题信号');self.assertTrue(card['observations'][0]['process_quote'])

    def test_total_duration_cannot_locate_a_slow_step(self):
        self.attempt(duration_seconds=700,reason='我觉得总结写得很慢。');self.analyze();card=self.card('efficiency')
        self.assertEqual(card['observations'][0]['judgment'],'uncertain')
        self.assertIn('尚无可核对的分步计时',card['observations'][0]['observation'])

    def test_new_question_integrates_prior_dimensions_without_old_full_question(self):
        first=self.attempt();self.analyze();new=self.attempt(self.qs[1]);result,model=self.analyze()
        payload=model.call_args.args[1];self.assertEqual([r['attempt_id'] for r in payload['new_evidence']],[new['id']])
        previous=next(c for c in payload['shenlun_dimensions']['previous_dimensions'] if c['dimension']=='structure')
        self.assertEqual(previous['evidence'][0]['source_ref'],'attempt:'+first['id'])
        self.assertEqual(self.card('structure')['weak_questions'],2);self.assertEqual(self.card('structure')['state'],'跨题反复')
        self.assertEqual(len(result['result']['shenlun_dimension_profile']['dimensions']),7)

    def test_same_question_repeated_answers_count_as_one_question(self):
        self.attempt();self.analyze();self.attempt();self.analyze()
        card=self.card('structure');self.assertEqual(card['weak_questions'],1);self.assertEqual(card['written_questions'],1)
        self.assertEqual(self.app.store.count('learning_analyses'),2)

    def test_better_new_answer_records_improvement_without_claiming_mastery(self):
        self.attempt();self.analyze();self.judgments={'structure':'adequate'};self.attempt(self.qs[1]);self.analyze()
        card=self.card('structure');self.assertEqual(card['state'],'出现改善证据');self.assertEqual(card['weak_questions'],1)
        self.assertEqual(card['adequate_questions'],1);self.assertNotIn('掌握',card['state'])

    def test_revision_invalidates_only_affected_evidence_and_old_summary(self):
        self.attempt();self.analyze();self.attempt(self.qs[1]);self.analyze();before=copy.deepcopy(self.app.store.all('learning_analyses'))
        q=self.qs[0];q['material']='材料已经修订。';self.app.store.put('questions',q)
        card=self.card('structure');self.assertEqual(card['written_questions'],1);self.assertEqual(card['stale_records'],1)
        self.assertTrue(card['conclusion_pending']);self.assertIsNone(card['conclusion'])
        self.assertEqual(before,self.app.store.all('learning_analyses'))

    def test_revised_followup_invalidates_old_dimension_without_regrading(self):
        a=self.attempt();self.analyze();old=copy.deepcopy(self.app.store.get('attempts',a['id']))
        d=self.app.store.get('diagnoses',a['id']);d['dialogue']=[{'role':'user','text':'这次我其实先按主体分了三组。'}];self.app.store.put('diagnoses',d)
        self.assertEqual(self.card('structure')['state'],'待重新校验');self.assertEqual(old,self.app.store.get('attempts',a['id']))

    def test_verification_prompts_create_dimension_tagged_short_training(self):
        self.attempt();result,_=self.analyze();tasks=self.app.store.all('coach_tasks')
        self.assertTrue(tasks);self.assertTrue(all(t['dimension'] in sd.DIMENSIONS for t in tasks))
        self.assertTrue(result['result']['shenlun_dimension_profile']['tasks'])
        t=tasks[0];public=coach.task_public(self.app,t);self.assertNotIn('reference',public)

    def test_training_feedback_is_evidence_without_inflating_written_question_count(self):
        self.attempt();self.analyze();t=next(t for t in self.app.store.all('coach_tasks') if t['dimension']=='structure')
        coach.task_action(self.app,t['id'],'start',{})
        for i in range(len(t['prompts'])):coach.task_action(self.app,t['id'],'answer',{'stage_index':i,'text':'我按主体区分中心和医生，再对应具体行为。'})
        self.analyze();card=self.card('structure')
        self.assertEqual(card['written_questions'],1);self.assertEqual(card['training_records'],1);self.assertEqual(card['state'],'单题信号')

    def test_context_correction_disables_old_dimension_training(self):
        self.attempt();self.analyze();t=self.app.store.all('coach_tasks')[0]
        shenlun.save_context(self.app,t['question_id'],{'max_score':25})
        self.assertTrue(coach.task_public(self.app,t)['stale'])
        with self.assertRaises(UserError):coach.task_action(self.app,t['id'],'start',{})
        self.assertFalse(sd.overview(self.app)['tasks'])

    def test_model_missing_dimensions_keeps_prior_result_and_new_record_pending(self):
        self.attempt();old,_=self.analyze();self.attempt(self.qs[1])
        with self.assertRaises(UserError):self.analyze(lambda system,data,**kw:test_shenlun.ShenlunTests.answer(None,system,data))
        self.assertEqual(la.latest(self.app)['id'],old['id'])
        self.assertEqual(la.preview(self.app,{'shenlun_version':1,'shenlun_dimensions_version':1})['new_count'],1)

    def test_foreign_sources_and_fabricated_quotes_are_not_accepted(self):
        self.attempt()
        def fake(system,data,**kw):
            out=self.answer(system,data)
            for o in out['shenlun_dimension_observations']:o['source_ref']='attempt:unknown'
            return out
        with self.assertRaises(UserError):self.analyze(fake)
        self.assertEqual(self.app.store.count('learning_analyses'),0)

    def test_fake_business_process_quote_does_not_establish_business_weakness(self):
        self.attempt()
        def fake(system,data,**kw):
            out=self.answer(system,data)
            for o in out['shenlun_dimension_observations']:o['process_quote']='这是用户没说过的业务理解。'
            return out
        self.analyze(fake);self.assertEqual(self.card('business')['weak_questions'],0)

    def test_objective_only_update_preserves_existing_shenlun_dimensions(self):
        self.attempt();first,_=self.analyze();before=first['result']['shenlun_dimension_conclusions']
        b=self.app.preview_import({'rows':[{'stem':'新的客观题','module':'常识判断','options':{'A':'是','B':'否'},'answer':['A']}]});self.app.commit_import(b['id'])
        q=next(q for q in self.app.store.all('questions') if q['type']=='single');s=self.app.create_session({'count':1,'question_ids':[q['id']]});self.app.save_answer(s['id'],q['id'],{'value':['A']});self.app.submit(s['id'])
        second,model=self.analyze();self.assertEqual(model.call_args.args[1]['dimension_sources'],[])
        self.assertEqual(second['result']['shenlun_dimension_conclusions'],before);self.assertEqual(self.card('structure')['written_questions'],1)

    def test_no_new_evidence_uses_cache_and_preview_never_calls_model(self):
        self.attempt();first,_=self.analyze();body={'shenlun_version':1,'shenlun_dimensions_version':1}
        with patch.object(self.app,'model_call',side_effect=AssertionError('No new evidence')):
            p=la.preview(self.app,body);sd.overview(self.app)
            second=la.run(self.app,{**body,'confirmed':True,'plan_token':p['plan_token']})
        self.assertEqual(second['id'],first['id']);self.assertTrue(second['reused'])

    def test_grades_and_original_answers_are_not_overwritten(self):
        self.attempt();before={t:self.app.store.all(t) for t in ('questions','sessions','attempts','diagnoses','settings','documents')}
        self.analyze()
        for table,records in before.items():self.assertEqual(records,self.app.store.all(table))

    def test_new_depth_mode_batches_one_shenlun_question_and_shares_global_coverage(self):
        self.attempt();self.attempt(self.qs[1]);body={'shenlun_version':1,'shenlun_dimensions_version':1}
        self.assertEqual(la.preview(self.app,body)['batch_count'],1)
        first,_=self.analyze(domain='shenlun');self.assertEqual(first['pending_count'],1)
        self.assertEqual(la.preview(self.app,body)['new_count'],1)

    def test_restart_restores_dimension_conclusions_and_evidence(self):
        self.attempt();self.analyze();restored=Application(self.tmp.name)
        self.assertEqual(sd.overview(restored)['questions'],1)
        self.assertEqual(next(c for c in sd.overview(restored)['dimensions'] if c['dimension']=='structure')['state'],'单题信号')

    def test_efficiency_uses_recorded_stage_times_not_model_numbers(self):
        self.judgments={'efficiency':'weak'};self.attempt();self.analyze();task=self.app.store.all('coach_tasks')[0]
        with patch('learning_coach.time.time',return_value=100):coach.task_action(self.app,task['id'],'start',{})
        with patch('learning_coach.time.time',return_value=140):coach.task_action(self.app,task['id'],'answer',{'stage_index':0,'text':'第一步很快，写完后我反复改第二步。'})
        with patch('learning_coach.time.time',return_value=300):coach.task_action(self.app,task['id'],'answer',{'stage_index':1,'text':'我在归并两种做法时来回改了几次。'})
        def model(system,data,**kw):
            result=self.answer(system,data)
            for o in result['shenlun_dimension_observations']:o['timing']=[{'seconds':99999}]
            return result
        self.analyze(model);ob=next(o for o in self.card('efficiency')['observations'] if o['source_type']=='training')
        self.assertEqual([t['seconds'] for t in ob['timing']],[40,160])
        self.assertEqual(self.card('efficiency')['weak_questions'],0)

    def test_unconfirmed_handwriting_does_not_enter_dimension_context(self):
        q=self.qs[0]
        row={'attempt_id':'draft','question':q,'user_answer':'见附件','shenlun':{'transcription_required':True}}
        self.assertEqual(sd.prepare(self.app,[row],[],{}),{})

    def test_old_reports_are_preserved_without_automatic_paid_reanalysis(self):
        self.attempt();body={'shenlun_version':1,'domain':'shenlun'};p=la.preview(self.app,body)
        with patch.object(self.app,'model_call',side_effect=lambda system,data,**kw:test_shenlun.ShenlunTests.answer(None,system,data)):
            old=la.run(self.app,{**body,'confirmed':True,'plan_token':p['plan_token']})
        with patch.object(self.app,'model_call',side_effect=AssertionError('No upgrade regrading')):
            p=la.preview(self.app,{'shenlun_version':1,'shenlun_dimensions_version':1});self.assertEqual(p['pending_count'],0)
            self.assertTrue(all(c['state']=='证据不足' for c in sd.overview(self.app)['dimensions']))
        self.assertEqual(la.latest(self.app)['id'],old['id'])


if __name__=='__main__':unittest.main()
