import copy
import json
import random
import tempfile
import unittest
from decimal import Decimal as D
from unittest.mock import patch
from app import Application,UserError
import calculation_training as ct


class CalculationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Application(self.tmp.name)
        self.parameters={'a':'192','b':'876','r1':'34.8','r2':'35.9'}

    def tearDown(self):self.tmp.cleanup()

    def create(self,**body):return ct.create(self.app,{'count':5,**body})
    def action(self,s,verb,**body):return ct.action(self.app,s['id'],verb,body)
    def question(self,kind='base_a'):return {'id':'cq_example','kind':kind,'parameters':self.parameters}

    def test_reference_image_all_thirteen_formulas(self):
        expected={'base_a':'142.43','base_b':'644.59','increase_a':'49.57','increase_b':'231.41',
            'share_now':'21.92','share_base':'22.10','share_change':'-0.18','ratio_growth':'-0.81',
            'base_sum':'787.02','base_difference':'502.16','compound_growth':'83.19',
            'sum_growth':'35.70','difference_growth':'36.21'}
        self.assertEqual({k:ct.fmt(v) for k,v in ct.values(self.parameters).items()},expected)

    def test_accepts_both_absolute_three_boundaries_and_rejects_outside(self):
        q=self.question()
        for v in ('139.43','145.43'):self.assertTrue(ct.grade(q,v)['correct'])
        for v in ('139.429999','145.430001','145.43000000000000000000000000001'):self.assertFalse(ct.grade(q,v)['correct'])

    def test_boundaries_use_visible_rounded_reference_not_hidden_fraction(self):
        result=ct.grade(self.question(),'145.43')
        self.assertEqual(result['reference'],'142.43');self.assertEqual(result['error'],'3.00')

    def test_percent_is_percent_points_not_relative_three_percent(self):
        q=self.question('share_now')
        self.assertTrue(ct.grade(q,'24.92%')['correct'])
        self.assertTrue(ct.grade(q,'18.92％')['correct'])
        self.assertFalse(ct.grade(q,'24.921')['correct'])
        self.assertFalse(ct.grade(q,'0.2192')['correct'])

    def test_direction_warning_does_not_override_requested_tolerance(self):
        r=ct.grade(self.question('share_change'),'0.18个百分点')
        self.assertTrue(r['correct']);self.assertTrue(r['direction_warning'])
        self.assertEqual(r['error'],'0.36')

    def test_numeric_parser_rejects_code_nonfinite_booleans_and_expressions(self):
        for raw in ('','NaN','Infinity','1e10','2+2','__import__("os")','1,2',None,True,'1'*41):
            with self.subTest(raw=raw),self.assertRaises((ValueError,ct.InvalidOperation)):ct.parse_answer(raw,'亿元')
        self.assertEqual(ct.parse_answer('1,234.5亿元','亿元'),D('1234.5'))
        self.assertEqual(ct.parse_answer('−0.18','个百分点'),D('-.18'))
        with self.assertRaises(ValueError):ct.parse_answer('10%','亿元')

    def test_generator_valid_across_levels_including_negative_growth(self):
        negatives=False;rng=random.Random(93)
        for level in ('basic','standard','challenge'):
            for _ in range(250):
                p=ct.generate(level,rng);v=ct.values(p)
                self.assertLess(D(p['a']),D(p['b']))
                self.assertGreater(v['base_difference'],D(p['b'])*D('.12')-D('.0001'))
                self.assertNotEqual(p['r1'],p['r2'])
                self.assertLessEqual(v['share_base'],95)
                self.assertLessEqual(abs(v['difference_growth']),100000)
                self.assertGreaterEqual(v['sum_growth'],min(D(p['r1']),D(p['r2'])))
                self.assertLessEqual(v['sum_growth'],max(D(p['r1']),D(p['r2'])))
                negatives|=D(p['r1'])<0
        self.assertTrue(negatives)

    def test_sum_difference_and_share_identities(self):
        v=ct.values(self.parameters);a,b=D(192),D(876)
        self.assertEqual(v['base_sum'],v['base_a']+v['base_b'])
        self.assertEqual(v['base_difference'],v['base_b']-v['base_a'])
        self.assertAlmostEqual(v['share_change'],v['share_now']-v['share_base'])
        self.assertAlmostEqual(v['ratio_growth'],(v['share_now']/v['share_base']-1)*100)
        self.assertAlmostEqual(v['sum_growth'],(a+b)/(v['base_sum'])*100-100)

    def test_selected_types_balanced_and_no_numeric_answers_before_submit(self):
        s=self.create(count=20,types=['base_a','share_now'])
        self.assertEqual(len(s['questions']),20)
        self.assertEqual(sum(q['kind']=='base_a' for q in s['questions']),10)
        self.assertTrue(all(q['result'] is None for q in s['questions']))
        raw=json.dumps(s);self.assertNotIn('"reference"',raw);self.assertNotIn('"lower"',raw)
        self.assertGreater(len({q['parameters']['a'] for q in s['questions']}),1)

    def test_table_uses_one_group_and_all_thirteen_types(self):
        s=self.create(mode='table');self.assertEqual(s['total'],13)
        self.assertTrue(all(q['parameters']==s['questions'][0]['parameters'] for q in s['questions']))
        self.assertEqual({q['kind'] for q in s['questions']},set(ct.KINDS))

    def test_invalid_setup_has_no_records(self):
        for body in ({'mode':'bad'},{'level':'bad'},{'types':[]},{'types':['bad']},{'count':0},{'count':True},{'count':'5.0'}):
            with self.subTest(body=body),self.assertRaises(UserError):self.create(**body)
        self.assertEqual(self.app.store.count('calculation_sessions'),0)

    def test_submit_idempotent_and_client_cannot_change_reference_or_tolerance(self):
        s=self.create(types=['base_a']);q=s['questions'][0];ref=ct.rounded(ct.values(q['parameters'])[q['kind']])
        first=self.action(s,'answer',question_id=q['id'],value=str(ref+4),tolerance=999,reference=str(ref+4))
        self.assertFalse(first['questions'][0]['result']['correct']);self.assertEqual(first['status'],'review')
        again=self.action(s,'answer',question_id=q['id'],value=str(ref))
        self.assertEqual(again,first);self.assertEqual(again['answered'],1)

    def test_quick_out_of_order_rejected_and_skip_is_explicit(self):
        s=self.create();q=s['questions'][0]
        with self.assertRaises(UserError):self.action(s,'answer',question_id=s['questions'][1]['id'],value='0')
        with self.assertRaises(UserError):self.action(s,'answer',question_id=q['id'],value='')
        out=self.action(s,'skip',question_id=q['id'])
        self.assertTrue(out['questions'][0]['result']['skipped']);self.assertFalse(out['questions'][0]['result']['correct'])

    def test_table_check_is_atomic_and_blank_is_not_zero(self):
        s=self.create(mode='table',types=['base_a','share_change']);q1,q2=s['questions']
        with self.assertRaises(UserError):self.action(s,'check',values={q1['id']:'12',q2['id']:'bad'})
        self.assertEqual(self.app.store.get('calculation_sessions',s['id'])['results'],{})
        r=self.action(s,'check',values={q1['id']:str(ct.rounded(ct.values(q1['parameters'])['base_a'])),q2['id']:''})
        self.assertEqual(r['status'],'finished');self.assertEqual(r['correct'],1)
        self.assertTrue(r['questions'][1]['result']['skipped'])
        self.assertEqual(self.action(s,'check',values={}),r)

    def test_draft_pause_restart_and_hint_preserved(self):
        s=self.create();qid=s['questions'][0]['id']
        self.action(s,'draft',values={qid:'-12.5','foreign':'100'})
        self.action(s,'hint',question_id=qid);self.action(s,'pause')
        app2=Application(self.tmp.name);r=ct.action(app2,s['id'],'read',{})
        self.assertEqual(r['status'],'paused');self.assertEqual(r['questions'][0]['draft'],'-12.5')
        self.assertIn('formula',r['questions'][0]['hint']);self.assertNotIn('reference',r['questions'][0])
        with self.assertRaises(UserError):self.action(s,'answer',question_id=qid,value='1')
        self.action(s,'start');r=self.action(s,'answer',question_id=qid,value='1')
        self.assertTrue(r['questions'][0]['result']['hint_used'])

    def test_pause_and_feedback_time_excluded_but_resumed_answer_time_accumulates(self):
        with patch.object(ct.time,'time',return_value=100):s=self.create()
        with patch.object(ct.time,'time',return_value=110):self.action(s,'pause')
        with patch.object(ct.time,'time',return_value=500):self.action(s,'start')
        with patch.object(ct.time,'time',return_value=505):r=self.action(s,'answer',question_id=s['questions'][0]['id'],value='0')
        self.assertEqual(r['elapsed_seconds'],15);self.assertEqual(r['questions'][0]['result']['duration_seconds'],15)
        with patch.object(ct.time,'time',return_value=700):self.action(s,'start')
        with patch.object(ct.time,'time',return_value=707):r=self.action(s,'skip',question_id=s['questions'][1]['id'])
        self.assertEqual(r['elapsed_seconds'],22);self.assertEqual(r['questions'][1]['result']['duration_seconds'],7)

    def test_disconnect_lease_caps_at_thirty_seconds(self):
        with patch.object(ct.time,'time',return_value=100):s=self.create()
        with patch.object(ct.time,'time',return_value=110):self.action(s,'heartbeat')
        with patch.object(ct.time,'time',return_value=1000):r=self.action(s,'read')
        self.assertEqual(r['status'],'paused');self.assertEqual(r['elapsed_seconds'],40)
        with patch.object(ct.time,'time',return_value=2000):r=self.action(s,'read')
        self.assertEqual(r['elapsed_seconds'],40)

    def test_finished_and_partially_stopped_history_with_type_statistics(self):
        s=self.create(types=['share_now']);q=s['questions'][0]
        r=self.action(s,'answer',question_id=q['id'],value=str(ct.rounded(ct.values(q['parameters'])['share_now'])))
        self.action(s,'finish');o=ct.overview(self.app)
        self.assertEqual(o['total'],1);self.assertEqual(o['correct'],1)
        self.assertEqual(o['recent'][0]['total'],5);self.assertEqual(o['recent'][0]['answered'],1)
        self.assertEqual(o['recent'][0]['status'],'finished')
        item=next(t for t in o['types'] if t['id']=='share_now');self.assertEqual(item['correct'],1)

    def test_no_exam_ai_or_original_question_records_modified(self):
        tables=['attempts','sessions','questions','learning_analyses','coach_tasks','settings']
        before={t:copy.deepcopy(self.app.store.all(t)) for t in tables}
        with patch.object(self.app,'model_call',side_effect=AssertionError('No model calls allowed')):
            s=self.create(mode='table');self.action(s,'check',values={});ct.overview(self.app)
        self.assertEqual({t:self.app.store.all(t) for t in tables},before)
        self.assertEqual(self.app.profile()['total_attempts'],0)

    def test_http_dispatch_contract_and_export(self):
        o=self.app.dispatch('GET','/api/calculation-training',{});self.assertEqual(len(o['types']),13)
        s=self.app.dispatch('POST','/api/calculation-training/sessions',{'count':5})
        out=self.app.dispatch('GET',f'/api/calculation-training/sessions/{s["id"]}',{})
        self.assertEqual(out['id'],s['id'])
        self.app.dispatch('POST',f'/api/calculation-training/sessions/{s["id"]}/pause',{})
        export=self.app.dispatch('GET','/api/export',{})
        self.assertEqual(len(export['calculation_sessions']),1);self.assertNotIn('settings',export)
        with self.assertRaises(UserError):self.app.dispatch('POST','/api/calculation-training/missing',{})
