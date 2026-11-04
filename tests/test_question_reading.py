import copy
import unittest
from unittest.mock import patch

import book_import
from app import normalize_question
from question_reading import locate_region,presentation,reading


class QuestionReadingTests(unittest.TestCase):
    def setUp(self):
        from test_page_assist import PageAssistTests
        PageAssistTests.setUp(self)

    def tearDown(self):
        self.app.page_assist.queue.join();self.app.uploads.tasks.join();self.tmp.cleanup()

    def test_109_individual_examples_keep_their_own_material_and_short_stem(self):
        rows,_=book_import.parse_objective([{'page':1,'text':'封面'},{'page':2,'text':'练习1 增量\n【例题1】（2025甲）\n第一份完整统计表。\n问：增长多少？\nA. 10\nB. 20\n【例题2】（2025乙）\n另一份完整统计表。\n问：减少多少？\nA. 30\nB. 40'},{'page':3,'text':'参考答案\n练习1 增量\n1-2：AB'}],'资料分析')
        self.assertEqual([q['stem'] for q in rows],['增长多少？','减少多少？'])
        self.assertNotEqual(rows[0]['group_id'],rows[1]['group_id'])
        self.assertNotIn('第一份',rows[1]['material'])

    def test_110_shared_material_pages_stop_before_first_question_for_all_five(self):
        rows,_=book_import.parse_objective([{'page':1,'text':'封面'},{'page':2,'text':'刷题1\n一、根据以下资料，完成1-5题。\n同一份统计材料。\n1. 第一题？\nA. 甲\nB. 乙'},{'page':3,'text':'2. 第二题？\nA. 甲\nB. 乙'},{'page':4,'text':'参考答案\n刷题1\n1-2：AB'}],'资料分析')
        self.assertEqual(rows[0]['material_pages'],[2]);self.assertEqual(rows[1]['material_pages'],[2])
        self.assertEqual(rows[0]['reading_source']['material'],rows[1]['reading_source']['material'])
        self.assertNotIn('第一题',rows[1]['reading_source']['material'][0]['text'])

    def test_111_region_crop_excludes_adjacent_questions_and_keeps_table_rows(self):
        labels=['其他题目','统计表','类别 2024 2025','甲 100 200','乙 300 400','1. 本题问题 A甲 B乙','2. 下一道题 A丙 B丁']
        layout={'layout_size':[1000,1000],'layout':[{'text':s,'box':[[100,100+i*100],[900,100+i*100],[900,130+i*100],[100,130+i*100]]} for i,s in enumerate(labels)]}
        bounds=locate_region('\n'.join(labels),'\n'.join(labels[1:5]),layout)['bbox']
        self.assertGreater(bounds[1],130);self.assertLess(bounds[3],600)
        self.assertLess(bounds[1],200);self.assertGreater(bounds[3],530)

    def test_112_low_confidence_crop_is_not_silently_replaced_with_whole_page(self):
        layout={'layout_size':[1000,1000],'layout':[{'text':'完全不同','box':[[1,1],[9,1],[9,9],[1,9]]}]}
        with self.assertRaises(ValueError):locate_region('真实材料内容','真实材料内容',layout)

    def test_113_historical_display_upgrades_without_mutating_snapshot_or_answers(self):
        raw={'stem':'旧题面含长材料','options':{'A':'甲','B':'乙'},'answer':'A','origin_key':'stable'}
        old=normalize_question(raw);snapshot=copy.deepcopy(old)
        self.app.store.put('questions',{**old,'stem':'仅本题问题','material':'独立资料','reading_source':{'version':1,'material':[],'question':[]}})
        result=presentation(self.app,snapshot)
        self.assertEqual(result['reading_stem'],'仅本题问题');self.assertEqual(snapshot,old)
        self.assertEqual(result['answer'],old['answer'])

    def test_114_wrapped_exam_label_is_not_mistaken_for_option_c(self):
        rows,_=book_import.parse_objective([{'page':1,'text':'封面'},{'page':2,'text':'【例题1】（2025事业\nC）\n题目材料。\n问：哪个正确？\nA. 甲\nB. 乙\nC. 丙\nD. 丁'},{'page':3,'text':'参考答案\n1：A'}],'资料分析')
        self.assertEqual(rows[0]['stem'],'哪个正确？');self.assertEqual(rows[0]['options']['C'],'丙')

    def test_115_question_reading_does_not_call_a_model_and_contains_no_answer(self):
        q=normalize_question({'stem':'本题问题','options':{'A':'甲','B':'乙'},'answer':'A','reading_source':{'version':1,'material':[{'page':1,'text':'资料'}],'question':[{'page':2,'text':'问题'}]},'page_images':[{'batch_id':self.bid,'file_id':self.fid,'page':1}]})
        self.app.store.put('questions',q)
        with patch('question_reading.region_asset',return_value={'id':'vis_'+'a'*32,'page':1}),patch.object(self.app,'model_call',side_effect=AssertionError('No cloud call')):
            result=self.app.dispatch('GET','/api/question-reading/'+q['id'],{})
        self.assertEqual(len(result['material']),1);self.assertNotIn('answer',result)

    def test_116_shared_material_end_does_not_include_the_following_passage(self):
        rows,_=book_import.parse_objective([{'page':1,'text':'封面'},{'page':2,'text':'刷题1\n一、根据以下资料，完成1-5题。\n第一份材料。\n1. 甲题？\nA. 甲\nB. 乙\nC. 丙\nD. 丁\n二、根据以下资料，完成6-10题。\n第二份材料。\n6. 乙题？\nA. 甲\nB. 乙\nC. 丙\nD. 丁'},{'page':3,'text':'参考答案\n刷题1\n1：A 6：B'}],'资料分析')
        self.assertNotIn('第二份',rows[0]['reading_source']['question'][0]['text'])
        self.assertNotIn('甲题',rows[1]['reading_source']['material'][0]['text'])

    def test_117_garbled_ocr_uses_neighbor_boundaries_and_includes_unreadable_line(self):
        labels=['前面完整材料','乱码xxxx','A 100 B 200 C 300 D 400','下一道题']
        layout={'layout_size':[1000,1000],'layout':[{'text':s,'box':[[100,100+i*150],[900,100+i*150],[900,140+i*150],[100,140+i*150]]} for i,s in enumerate(labels)]}
        result=locate_region('前面完整材料\n问：这是需要模型识别的长问题，正确答案应该是多少？\nA 100 B 200 C 300 D 400\n下一道题','问：这是需要模型识别的长问题，正确答案应该是多少？\nA 100 B 200 C 300 D 400',layout)
        self.assertEqual(result['method'],'neighbor_anchors');self.assertLess(result['bbox'][1],250)
        self.assertGreater(result['bbox'][1],140);self.assertLess(result['bbox'][3],550)

    def test_118_cross_page_material_preserves_one_scale_and_creates_a_single_image(self):
        from PIL import Image
        from question_reading import continuous_material
        helper=self.app.page_assist.pages
        assets=[{'id':'first','page':1,'bbox':[100,100,700,300],'coverage':1},
                {'id':'second','page':2,'bbox':[200,300,800,600],'coverage':1}]
        with patch.object(helper,'image',side_effect=lambda *args:Image.new('RGB',(1000,1000),'white')):
            result=continuous_material(helper,self.bid,self.fid,assets,self.source)
        self.assertEqual(result['pages'],[1,2]);self.assertEqual(result['width'],700)
        self.assertEqual(result['height'],500)
        with Image.open(helper.asset_path(result['id'])) as image:self.assertEqual(image.size,(700,500))

    def test_119_page_edge_garbled_material_can_use_header_and_next_question(self):
        labels=['超格学员专用','上半年部分数据','乱码xxxx','问：本题问题','A 1 B 2']
        layout={'layout_size':[1000,1000],'layout':[{'text':s,'box':[[100,30+i*150],[900,30+i*150],[900,60+i*150],[100,60+i*150]]} for i,s in enumerate(labels)]}
        region='上半年部分数据，这里还有模型已经识别但本地未能读出的后半句。'
        result=locate_region(region+'\n问：本题问题\nA 1 B 2',region,layout)
        self.assertEqual(result['method'],'neighbor_anchors');self.assertLess(result['bbox'][1],180)
        self.assertGreater(result['bbox'][3],360);self.assertLess(result['bbox'][3],480)

    def test_120_first_material_page_is_kept_when_questions_start_on_the_next_page(self):
        from library_rebuild import build_rows
        rows,_=build_rows([{'page':1,'text':'封面'},{'page':2,'text':'一、根据以下资料，完成1-5题。\n完整的首篇统计材料。'},{'page':3,'text':'1. 本题问题？\nA. 甲\nB. 乙'}],'资料分析.pdf',self.bid,self.fid)
        self.assertEqual(len(rows),1);self.assertIn('首篇统计材料',rows[0]['material'])
        self.assertEqual(rows[0]['material_pages'],[2]);self.assertEqual(rows[0]['source_pages'],[3])

    def test_121_existing_ocr_coordinates_are_reused_without_recognizing_again(self):
        import file_pages
        from question_reading import page_layout
        saved={'layout_size':[1000,1000],'layout':[{'text':'资料','box':[[1,1],[9,1],[9,9],[1,9]]}]}
        file_pages.write_page(self.source,1,saved,'ocr-cache')
        with patch('local_ocr.recognize',side_effect=AssertionError('Coordinates already cached')):
            result=page_layout(self.app.page_assist.pages,self.bid,self.fid,1)
        self.assertEqual(result,saved)
