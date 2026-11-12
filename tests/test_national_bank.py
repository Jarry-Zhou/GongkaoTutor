"""Synthetic fixtures only; no third-party question corpus is redistributed."""
import copy
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from app import Application, UserError, normalize_question
import national_bank as nb
import question_reading as reading


NOTE='''---
地区: "国考"
年份: "2020"
模块: "判断推理"
试卷: "2020年合成测试卷"
题数: "1"
---
## 第 1 题 <sub>qid 999 · 图形推理</sub>
<p>合成图形测试<img src="../90-图片/题目图/test.png"></p>
- **A**. <p>合成甲</p>
- **B**. <p>合成乙</p> ✅
**答案**：B
**官方解析**
<p>合成解释<img src="../90-图片/公式图/explain.png"></p>
'''


class NationalBankTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Application(self.tmp.name)
        self.asset={'asset':'a'*64,'width':20,'height':20,'mime':'image/png'}
        self.resolve=lambda path:dict(self.asset,asset=('b' if 'explain' in path else 'a')*64)

    def tearDown(self):self.tmp.cleanup()
    def parse(self,note=NOTE):return nb.parse_paper(note,'01/test.md','c'*40,self.resolve)[0]
    def report(self):return {'commit':'c'*40,'questions':1}

    def test_separates_answer_ticks_and_explanation_image(self):
        q=self.parse();self.assertEqual(q['answer'],['B']);self.assertEqual(q['status'],'ready')
        self.assertNotIn('✅',q['options']['B']);self.assertNotIn('合成解释',q['stem'])
        self.assertEqual(nb.image_count(q),1)
        self.assertEqual([n['asset'] for n in nb.image_roles(q)[1][1]],['a'*64])

    def test_diagrams_participate_in_dedup_fingerprint(self):
        first=self.parse();self.resolve=lambda path:dict(self.asset,asset='d'*64)
        self.assertNotEqual(first['fingerprint'],self.parse()['fingerprint'])

    def test_material_groups_keep_table_shape_and_answer_separate(self):
        note=NOTE.replace('## 第 1 题','## 材料 1\n<table><tr><th colspan="2">合成表头</th></tr><tr><td>甲</td><td>12</td></tr></table>\n## 第 1 题')
        q=self.parse(note);self.assertTrue(q['whole_group']);self.assertTrue(q['group_id'])
        table=q['rich_content']['material'][0];self.assertEqual(table['tag'],'table')
        self.assertEqual(table['children'][0]['children'][0]['colspan'],2)
        self.assertNotIn('12',q['stem'])

    def test_missing_picture_and_inconsistent_answer_are_reviewed(self):
        self.resolve=lambda path:None
        self.assertEqual(self.parse()['status'],'review')
        self.resolve=lambda path:self.asset
        q=self.parse(NOTE.replace('**答案**：B','**答案**：A'))
        self.assertEqual(q['status'],'review')

    def test_wrong_region_count_and_source_traversal_rejected(self):
        for note in [NOTE.replace('地区: "国考"','地区: "地方"'),NOTE.replace('题数: "1"','题数: "2"')]:
            with self.assertRaises(ValueError):self.parse(note)
        for path in ['../evil','/root/a','a\\b','a/../b']:
            with self.assertRaises(ValueError):nb.safe_source_path(path)

    def test_rich_parser_drops_executable_markup_external_images_and_attributes(self):
        calls=[]
        nodes,missing=nb.parse_rich('<script>secret</script><p onclick="evil()">text<img src="https://evil/x.png"></p><table><tr><td colspan="999" style="bad">cell</td></tr></table>',lambda p:calls.append(p),'stem')
        raw=json.dumps(nodes);self.assertNotIn('secret',raw);self.assertNotIn('onclick',raw);self.assertNotIn('style',raw)
        self.assertEqual(calls,[]);self.assertEqual(len(missing),1)
        self.assertEqual(next(n for n in nb.walk(nodes) if n['tag']=='td')['colspan'],20)

    def test_atomic_archive_restore_reinstall_and_history_immutability(self):
        old=normalize_question({'stem':'合成旧题','module':'常识判断','options':{'A':'甲','B':'乙'},'answer':['A']},'合成')
        self.app.store.put('questions',old)
        history={'id':'synthetic-history','question':copy.deepcopy(old),'correct':False}
        self.app.store.put('attempts',history)
        q=self.parse()
        with self.assertRaises(UserError):nb.install(self.app,[q],self.report())
        self.assertIsNone(self.app.store.get('questions',q['id']))
        nb.install(self.app,[q],self.report(),replace=True)
        self.assertEqual([x['id'] for x in self.app.catalog_questions()],[q['id']])
        self.assertEqual(self.app.store.get('questions',old['id']),old)
        self.assertEqual(self.app.store.get('attempts',history['id']),history)
        q['explanation']='人工修订';self.app.store.put('questions',q)
        self.assertTrue(nb.install(self.app,[self.parse()],self.report(),replace=True)['reused'])
        self.assertEqual(self.app.store.get('questions',q['id'])['explanation'],'人工修订')
        nb.restore(self.app);self.assertEqual([x['id'] for x in self.app.catalog_questions()],[old['id']])
        nb.install(self.app,[q],self.report(),replace=True)
        self.assertEqual(len(self.app.store.all('questions')),2)

    def test_public_session_hides_rich_answer_until_check(self):
        q=self.parse();nb.install(self.app,[q],self.report())
        s=self.app.create_session({'count':1,'feedback':'each'})
        exposed=s['questions'][0]
        self.assertNotIn('answer',exposed);self.assertNotIn('explanation',exposed['rich_content'])
        self.assertNotIn('合成解释',json.dumps(exposed,ensure_ascii=False))
        self.app.save_answer(s['id'],q['id'],{'value':['B']},check=True)
        exposed=self.app.public_session(self.app.require('sessions',s['id']))['questions'][0]
        self.assertEqual(exposed['answer'],['B']);self.assertIn('explanation',exposed['rich_content'])
        result=self.app.submit(s['id']);self.assertEqual(result['attempts'][0]['correct'],True)

    def test_new_sessions_exclude_archived_bank(self):
        old=normalize_question({'stem':'合成旧题','module':'常识判断','options':{'A':'甲','B':'乙'},'answer':['A']},'合成')
        self.app.store.put('questions',old);q=self.parse();nb.install(self.app,[q],self.report(),replace=True)
        self.assertEqual({x['id'] for x in self.app.pool({})},{q['id']})
        self.assertEqual(self.app.dispatch('GET','/api/questions',{}),[q])

    def test_material_group_preserves_source_order_after_random_sampling(self):
        rows=[]
        for number in (3,1,2):
            q=self.parse();q.update(id='synthetic-'+str(number),source_number=number,group_id='synthetic-group',whole_group=True)
            self.app.store.put('questions',q);rows.append(q)
        self.assertEqual([q['source_number'] for q in self.app.choose(rows,3)],[1,2,3])

    def test_model_images_exclude_explanation_and_count_material_separately(self):
        q=self.parse();folder=self.app.store.folder/'national-bank/assets';folder.mkdir(parents=True)
        b=io.BytesIO();Image.new('RGB',(20,20),'white').save(b,'PNG');(folder/('a'*64)).write_bytes(b.getvalue())
        # Explanation b*64 is intentionally absent: it must never be read.
        self.assertEqual(len(reading.model_images(self.app,q)),1)
        q['rich_content']['material']=[dict(self.asset,tag='img',label='material-1')]
        self.assertEqual(reading.image_count(q),2);self.assertEqual(len(reading.model_images(self.app,q)),2)
        with self.assertRaises(UserError):nb.model_images(self.app,q,limit=1)
        with self.assertRaises(UserError):nb.asset_path(self.app,'../bad')

    def test_bad_cache_never_trusted_and_download_failure_keeps_current_bank(self):
        cache=Path(self.tmp.name)/'cache';cache.mkdir();(cache/'x.md').write_bytes(b'bad')
        item={'path':'x.md','size':4,'sha':nb.git_sha(b'good')}
        with patch.object(nb.urllib.request,'urlopen',side_effect=ValueError('no source')):
            with self.assertRaises(ValueError):nb._fetch_source(item,{'commit':'c'*40},cache)
        self.assertEqual(self.app.catalog_questions(),[])

    def test_explicit_confirmation_and_interrupted_job(self):
        with self.assertRaises(UserError):nb.start_install(self.app,{})
        self.app.store.put('bank_catalog',{'id':'job','status':'running'})
        nb.recover_job(self.app);self.assertEqual(nb.status(self.app)['job']['status'],'interrupted')


if __name__=='__main__':unittest.main()
