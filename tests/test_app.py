import base64
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import Application, UserError, normalize_question, parse_text, protect


class AppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Application(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def seed(self, count=8, **extra):
        rows = [dict(stem=f'只有完成报名才能考试。例题{i}，已参加考试可推出什么？', options={'A': '已报名', 'B': '未报名'}, answer=['A'], module='判断推理', knowledge_points=['必要条件'], explanation='参加考试→完成报名', **extra) for i in range(count)]
        batch = self.app.preview_import({'rows': rows})
        self.app.commit_import(batch['id'])
        return self.app.store.all('questions')

    def session(self, count=2, **extra):
        return self.app.create_session({'count': count, 'minutes': 20, 'kind': 'exam', **extra})

    def test_01_import_preserves_answers_and_deduplicates(self):
        self.seed()
        batch = self.app.preview_import({'rows': [{'stem': 'only', 'options': ['one', 'two'], 'answer': 'A'}]*2})
        committed = self.app.commit_import(batch['id'])
        self.assertEqual(committed['added'], 1)
        self.assertEqual(committed['skipped'], 1)
        self.assertEqual(self.app.commit_import(batch['id'])['added'], 1)
        self.assertEqual(len(self.app.store.all('questions')), 9)

    def test_02_exam_response_contains_no_answers_or_explanations(self):
        self.seed()
        session = self.session()
        raw = json.dumps(session, ensure_ascii=False)
        self.assertNotIn('"answer":', raw)
        self.assertNotIn('"explanation":', raw)
        self.assertNotIn('参加考试→完成报名', raw)
        self.assertNotIn('snapshots', session)

    def test_03_submit_is_idempotent_and_blank_answers_are_wrong(self):
        self.seed()
        s = self.session()
        q = s['questions'][0]
        self.app.save_answer(s['id'], q['id'], {'value': ['A'], 'reason': '先看后件', 'duration_seconds': 20})
        first = self.app.submit(s['id'])
        second = self.app.submit(s['id'])
        self.assertEqual(first['score'], 1)
        self.assertEqual(second['score'], 1)
        self.assertEqual(len(self.app.store.all('attempts')), 2)
        self.assertEqual(first['correct_count'], 1)
        self.assertEqual([a['question_id'] for a in first['attempts']], [q['id'] for q in s['questions']])
        self.assertEqual(len(self.app.store.all('diagnoses')), 2)

    def test_04_refresh_restores_draft_without_attempts(self):
        self.seed()
        s = self.session()
        q = s['questions'][0]
        self.app.save_answer(s['id'], q['id'], {'value': ['B'], 'reason': '我的步骤', 'duration_seconds': 15})
        reloaded = self.app.dispatch('GET', '/api/sessions/'+s['id'], {})
        self.assertEqual(reloaded['answers'][q['id']]['value'], ['B'])
        self.assertEqual(reloaded['answers'][q['id']]['reason'], '我的步骤')
        self.assertEqual(self.app.store.all('attempts'), [])

    def test_05_exam_cannot_reveal_each_question(self):
        self.seed()
        s = self.session(feedback='each')
        with self.assertRaises(UserError):
            self.app.save_answer(s['id'], s['questions'][0]['id'], {'value': ['A']}, check=True)

    def test_06_practice_check_reveals_only_checked_question(self):
        self.seed()
        s = self.session(kind='practice', feedback='each')
        r = self.app.save_answer(s['id'], s['questions'][0]['id'], {'value': ['A']}, check=True)
        self.assertIn('answer', r['questions'][0])
        self.assertNotIn('answer', r['questions'][1])
        result = self.app.submit(s['id'])
        self.assertFalse(result['independent'])

    def test_07_insufficient_inventory_does_not_create_session(self):
        self.seed(2)
        with self.assertRaises(UserError):
            self.session(3)
        self.assertEqual(self.app.store.all('sessions'), [])

    def test_08_whole_material_group_is_not_split(self):
        self.seed(3, group_id='g1', whole_group=True)
        with self.assertRaises(UserError):
            self.session(2)
        s = self.session(3)
        self.assertEqual(len(s['questions']), 3)
        self.assertEqual({q['group_id'] for q in s['questions']}, {'g1'})

    def test_09_module_quotas_and_weighted_scoring(self):
        self.seed(2)
        batch = self.app.preview_import({'rows': [{'stem': '上年100今年120增长率是多少？', 'options': {'A': '20%', 'B': '10%'}, 'answer': 'A', 'module': '资料分析'}]})
        self.app.commit_import(batch['id'])
        s = self.session(quotas={'判断推理': 2, '资料分析': 1}, module_points={'判断推理': 2, '资料分析': 3})
        for q in s['questions']:
            self.app.save_answer(s['id'], q['id'], {'value': ['A']})
        result = self.app.submit(s['id'])
        self.assertEqual(result['score'], 7)
        self.assertEqual(result['max_score'], 7)
        self.assertEqual(len(result['questions']), 3)

    def test_10_snapshot_survives_question_edit(self):
        qs = self.seed(2)
        s = self.session()
        original = self.app.require('questions', s['questions'][0]['id'])
        original['answer'] = ['B']
        self.app.store.put('questions', original)
        self.app.save_answer(s['id'], original['id'], {'value': ['A']})
        self.assertEqual(self.app.submit(s['id'])['score'], 1)

    def test_11_subjective_is_pending_not_falsely_auto_scored(self):
        batch = self.app.preview_import({'rows': [{'stem': '概括措施', 'type': 'short', 'answer': '改进服务', 'points': 10}]})
        self.app.commit_import(batch['id'])
        s = self.session(1)
        self.app.save_answer(s['id'], s['questions'][0]['id'], {'value': '具体措施'})
        result = self.app.submit(s['id'])
        self.assertEqual(result['pending_score'], 10)
        self.assertIsNone(result['attempts'][0]['correct'])

    def test_12_no_reason_does_not_invent_error_cause(self):
        self.seed(1)
        s = self.session(1)
        self.app.save_answer(s['id'], s['questions'][0]['id'], {'value': ['B']})
        a = self.app.submit(s['id'])['attempts'][0]
        result = self.app.diagnosis(a)
        self.assertEqual(result['confidence'], '待确认')
        self.assertTrue(result['questions'])
        self.assertIn('不能仅凭选项', result['cause'])

    def test_13_personal_reason_and_followup_reach_model(self):
        self.seed(1)
        s = self.session(1)
        self.app.save_answer(s['id'], s['questions'][0]['id'], {'value': ['B'], 'reason': '我把只有A才B写成A→B'})
        a = self.app.submit(s['id'])['attempts'][0]
        with patch.object(self.app, 'model_call', return_value={'cause': '把必要条件方向反转', 'explanation': '从B出发推出A', 'confidence': '有用户证据支持', 'questions': [], 'source_ids': ['fake:1']}) as call:
            result = self.app.diagnosis(a, True, '我不确定箭头方向')
        self.assertEqual(call.call_args.args[1]['response']['reason'], '我把只有A才B写成A→B')
        self.assertEqual(call.call_args.args[1]['followup_dialogue'][0]['text'], '我不确定箭头方向')
        self.assertEqual(result['source_ids'], [])
        self.assertEqual(result['confidence'], '有用户证据支持')
        self.assertEqual(self.app.require('attempts', a['id'])['correct'], False)

    def test_14_exclude_seen_does_not_reuse_questions(self):
        self.seed(2)
        s = self.session(2)
        self.app.submit(s['id'])
        with self.assertRaises(UserError):
            self.session(1, exclude_seen=True)

    def test_15_duplicate_conflicting_answer_is_flagged(self):
        self.seed(1)
        original = self.app.store.all('questions')[0]
        b = self.app.preview_import({'rows': [{**original, 'answer': ['B']}]})
        self.assertTrue(b['items'][0]['duplicate_of'])
        self.assertEqual(b['items'][0]['status'], 'review')
        self.app.commit_import(b['id'])
        self.assertEqual(self.app.store.all('questions')[0]['answer'], ['A'])

    def test_16_text_import_extracts_options_answer_and_explanation(self):
        rows = parse_text('1. 某题\nA. 选项一\nB. 选项二\n答案：B\n解析：理由\n2. 另一题\nA. 甲\nB. 乙\n答案：A')
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['answer'], 'B')
        self.assertEqual(rows[0]['options']['B'], '选项二')

    def test_17_missing_answer_cannot_enter_exam(self):
        b = self.app.preview_import({'rows': [{'stem': '无答案', 'options': ['甲', '乙']}]})
        self.app.commit_import(b['id'])
        with self.assertRaises(UserError):
            self.session(1)

    def test_18_dpapi_encrypts_and_config_does_not_expose_key(self):
        if sys.platform != 'win32':
            self.skipTest('Windows-specific')
        secret = 'test-key-only-not-a-real-credential'
        public = self.app.dispatch('POST', '/api/settings', {'base_url': 'https://example.org/v1', 'model': 'test', 'api_key': secret})
        self.assertNotIn(secret, json.dumps(public))
        self.assertNotIn('key_cipher', public)
        stored = self.app.store.get('settings', 'model')
        self.assertNotIn(secret, stored['key_cipher'])
        self.assertEqual(protect(stored['key_cipher'], True), secret)
        self.assertNotIn('settings', self.app.dispatch('GET', '/api/export', {}))

    def test_19_external_plain_http_rejected(self):
        with self.assertRaises(UserError):
            self.app.dispatch('POST', '/api/settings', {'base_url': 'http://external.example/v1'})

    def test_20_no_fabricated_estimate_without_evidence(self):
        result = self.app.estimate()
        self.assertFalse(result['available'])
        self.assertNotIn('mean', result)

    def test_21_invalid_answer_options_rejected(self):
        self.seed(1)
        s = self.session(1)
        with self.assertRaises(UserError):
            self.app.save_answer(s['id'], s['questions'][0]['id'], {'value': ['Z']})

    def test_22_real_retrieval_and_no_fabricated_source(self):
        self.app.add_document({'title': '条件笔记', 'text': '只有A才B表示B推出A。必要条件是结果成立必须具备的条件。'})
        sources = self.app.sources('必要条件 只有A才B')
        self.assertEqual(sources[0]['title'], '条件笔记')
        self.assertEqual(sources[0]['chunk_id'], 1)

    def test_23_expired_session_auto_submits_on_reopen(self):
        self.seed(1)
        s = self.session(1)
        saved = self.app.require('sessions', s['id'])
        saved['started_at'] -= 5000
        self.app.store.put('sessions', saved)
        result = self.app.dispatch('GET', '/api/sessions/'+s['id'], {})
        self.assertEqual(result['status'], 'finished')
        self.assertEqual(result['score'], 0)

    def test_24_fill_boolean_and_multiple(self):
        fill = normalize_question({'stem': '填空', 'type': 'fill', 'answer': '20|二十'})
        self.assertTrue(self.app.grade(fill, {'value': '二十'}))
        boolean = normalize_question({'stem': '判断', 'type': 'boolean', 'answer': True})
        self.assertTrue(self.app.grade(boolean, {'value': ['T']}))
        multiple = normalize_question({'stem': '多选', 'type': 'multiple', 'options': ['one', 'two', 'three'], 'answer': ['A', 'C']})
        self.assertFalse(self.app.grade(multiple, {'value': ['A']}))
        self.assertTrue(self.app.grade(multiple, {'value': ['C', 'A']}))

    def test_25_mocked_model_actual_http_adapter(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        observed = {}
        class FakeModel(BaseHTTPRequestHandler):
            def do_POST(self):
                observed['path'] = self.path
                observed['body'] = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                body = json.dumps({'choices': [{'message': {'content': '{"ok":true}'}}]}).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), FakeModel)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            self.app.dispatch('POST', '/api/settings', {'base_url': f'http://127.0.0.1:{server.server_port}/v1', 'model': 'mock-model'})
            result = self.app.dispatch('POST', '/api/settings/test', {})
            self.assertTrue(result['ok'])
            self.assertEqual(observed['path'], '/v1/chat/completions')
            self.assertEqual(observed['body']['response_format'], {'type': 'json_object'})
        finally:
            server.shutdown()
            server.server_close()

    def test_33_classification_disagreement_requires_review(self):
        row = {'stem':'上年100今年120，增长率是多少？','options':['10%','20%'],'answer':'B'}
        def classify_result(system,data,**kwargs):
            return {'classifications':[{'id':data['questions'][0]['id'],'module':'数量关系','knowledge_points':['比例计算'],'basis':'增长计算'}]}
        with patch.object(self.app,'model_call',side_effect=classify_result):
            b=self.app.preview_import({'rows':[row],'use_ai':True})
        q=b['items'][0]
        self.assertEqual(q['module'],'资料分析')
        self.assertEqual(q['classification_status'],'conflict')
        self.assertEqual(q['status'],'review')

    def test_34_model_does_not_override_provided_module(self):
        def classify_result(system,data,**kwargs):
            return {'classifications':[{'id':data['questions'][0]['id'],'module':'数量关系','knowledge_points':[]}]}
        with patch.object(self.app,'model_call',side_effect=classify_result):
            b=self.app.preview_import({'rows':[{'stem':'某题','options':['甲','乙'],'answer':'A','module':'判断推理'}],'use_ai':True})
        self.assertEqual(b['items'][0]['module'],'判断推理')
        self.assertEqual(b['items'][0]['classification_status'],'provided')

    def test_35_provided_module_does_not_inherit_unrelated_subtype(self):
        q=normalize_question({'stem':'只有有人学习，技艺才能传承。这段文字主要说明什么？','module':'言语理解','options':['甲','乙'],'answer':'A'})
        self.assertEqual(q['module'],'言语理解')
        self.assertEqual(q['subtype'],'片段阅读')

    def test_36_question_task_overrides_incidental_conditional_words(self):
        q=normalize_question({'stem':'只有有人学习，技艺才能传承。这段文字主要说明什么？','options':['甲','乙'],'answer':'A'})
        self.assertEqual(q['module'],'言语理解')


if __name__ == '__main__':
    unittest.main(verbosity=2)
