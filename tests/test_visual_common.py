import unittest
from unittest.mock import patch
import book_import
from app import normalize_question,UserError
from question_reading import locate_region,model_images,region_asset


class VisualCommonTests(unittest.TestCase):
    def setUp(self):
        from test_page_assist import PageAssistTests
        PageAssistTests.setUp(self)

    def tearDown(self):
        self.a.queue.join();self.app.uploads.tasks.join();self.tmp.cleanup()

    def test_135_graph_and_other_modules_keep_region_metadata_and_image_requirement(self):
        rows,_=book_import.parse_objective([{'page':1,'text':'封面'},{'page':2,'text':'专项刷题一\n1. 请选出问号处应填的图形。\nA\nB\nC\nD'},{'page':3,'text':'参考答案\n专项刷题一\n1：A'}],'判断推理.pdf')
        q=normalize_question(rows[0]);self.assertTrue(q['requires_image']);self.assertEqual(q['reading_source']['presentation'],'figure')

    def test_136_figure_crop_includes_non_text_pixels_below_recognized_stem(self):
        layout={'layout_size':[1000,1000],'layout':[{'text':'1. 选择图形规律','box':[[100,100],[900,100],[900,140],[100,140]]},
            {'text':'2. 下一道题','box':[[100,600],[900,600],[900,640],[100,640]]}]}
        region='1. 选择图形规律\n[图形保留在原图中]'
        r=locate_region(region+'\n2. 下一道题',region,layout,figure=True)
        self.assertGreater(r['bbox'][3],500);self.assertLess(r['bbox'][3],600)

    def test_137_garbled_header_stays_with_its_own_question(self):
        rows=[('1. 甲题完整指令',100),('A B C D',200),('乱码标题xxxx',250),('规律性',300),('A B C D',400),('3. 丙题完整指令',450)]
        layout={'layout_size':[1000,1000],'layout':[{'text':t,'box':[[100,y],[900,y],[900,y+20],[100,y+20]]} for t,y in rows]}
        one='1. 甲题完整指令\nA B C D';two='2. 乙题完整指令\n规律性\nA B C D';page=one+'\n'+two+'\n3. 丙题完整指令'
        a=locate_region(page,one,layout,figure=True);b=locate_region(page,two,layout,figure=True)
        self.assertLess(a['bbox'][3],250);self.assertLess(b['bbox'][1],250);self.assertGreater(b['bbox'][1],220)

    def test_138_model_images_use_only_cropped_asset_not_original_page(self):
        q=normalize_question({'stem':'图形题','options':{'A':'图中A','B':'图中B'},'answer':'A','requires_image':True,'reading_source':{'presentation':'figure'},
            'page_images':[{'batch_id':self.bid,'file_id':self.fid,'page':1}]})
        p=self.source.with_suffix('.test-crop');p.write_bytes(b'only-the-cropped-question')
        with patch('question_reading.reading',return_value={'material':[],'question':[{'id':'crop'}],'warnings':[]}),patch.object(self.a.pages,'asset_path',return_value=p),patch.object(self.a.pages,'image',side_effect=AssertionError('No full page transmission')):
            result=model_images(self.app,q)
        import base64
        self.assertEqual(base64.b64decode(result[0].split(',')[1]),p.read_bytes())

    def test_139_unreliable_crop_blocks_cloud_analysis_instead_of_sending_full_page(self):
        q=normalize_question({'stem':'图形题','options':{'A':'甲','B':'乙'},'answer':'A','requires_image':True,'reading_source':{'presentation':'figure'},'page_images':[{'batch_id':self.bid,'file_id':self.fid,'page':1}]})
        with patch('question_reading.reading',return_value={'warnings':[{'page':1,'message':'Uncertain'}]}),patch.object(self.a.pages,'image',side_effect=AssertionError('No full page')):
            with self.assertRaises(UserError):model_images(self.app,q)

    def test_140_figure_and_text_region_caches_are_separate(self):
        with patch('question_reading.page_layout',return_value={}),patch('question_reading.locate_region',return_value={'bbox':[100,100,900,500],'coverage':1}) as locate:
            region_asset(self.a.pages,self.bid,self.fid,{'page':1,'text':'GOOD PAGE ONE'},figure=False)
            region_asset(self.a.pages,self.bid,self.fid,{'page':1,'text':'GOOD PAGE ONE'},figure=True)
        self.assertEqual(locate.call_count,2)

    def test_143_inline_answer_is_preserved_but_excluded_from_question_crop(self):
        rows,_=book_import.parse_objective([{'page':1,'text':'1. 选择符合规律的图形？\nA. 图甲\nB. 图乙\n答案：A\n解析：按数量递增。'}],'判断推理.pdf')
        q=rows[0];self.assertEqual(q['answer'],['A']);self.assertEqual(q['explanation'],'按数量递增。')
        self.assertNotIn('答案',q['reading_source']['question'][0]['text']);self.assertNotIn('解析',q['options']['B'])
