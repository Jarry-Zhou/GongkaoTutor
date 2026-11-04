import base64
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import Application, UserError


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.app=Application(self.tmp.name)
    def tearDown(self):
        self.tmp.cleanup()
    def payload(self,name,data):
        return {'name':name,'data':base64.b64encode(data).decode()}

    def test_26_csv_bom_and_chinese_headers(self):
        value='题干,A,B,答案,模块\n增长率是多少,10%,20%,B,资料分析\n'
        b=self.app.preview_import(self.payload('bank.csv',value.encode('utf-8-sig')))
        self.assertEqual(b['total'],1)
        self.assertEqual(b['items'][0]['answer'],['B'])

    @unittest.skipUnless(importlib.util.find_spec('openpyxl'),'Optional Excel dependency')
    def test_27_xlsx_import(self):
        from openpyxl import Workbook
        wb=Workbook();ws=wb.active
        ws.append(['题干','A','B','答案','模块'])
        ws.append(['只有报名才考试，已考试可推出？','已报名','未报名','A','判断推理'])
        buf=io.BytesIO();wb.save(buf)
        b=self.app.preview_import(self.payload('bank.xlsx',buf.getvalue()))
        self.assertEqual(b['items'][0]['module'],'判断推理')
        self.assertEqual(b['items'][0]['status'],'ready')

    @unittest.skipUnless(importlib.util.find_spec('docx'),'Optional Word dependency')
    def test_28_docx_question_and_knowledge_import(self):
        from docx import Document
        doc=Document()
        for line in ['1. 只有报名才考试，已考试可推出？','A. 已报名','B. 未报名','答案：A','解析：考试推出报名。']:
            doc.add_paragraph(line)
        buf=io.BytesIO();doc.save(buf)
        payload=self.payload('questions.docx',buf.getvalue())
        b=self.app.preview_import(payload)
        self.assertEqual(b['total'],1)
        d=self.app.add_document(payload)
        self.assertIn('考试推出报名',d['text'])

    @unittest.skipUnless(importlib.util.find_spec('pypdf') and importlib.util.find_spec('reportlab'),'Optional PDF dependencies')
    def test_29_text_pdf_import_and_page_provenance(self):
        from reportlab.pdfgen import canvas
        buf=io.BytesIO();c=canvas.Canvas(buf)
        for i,line in enumerate(['1. What is 2+2?','A. 4','B. 5','Answer: A']):
            c.drawString(50,750-i*25,line)
        c.save()
        doc=self.app.add_document(self.payload('sample.pdf',buf.getvalue()))
        self.assertIn('What is 2+2',doc['text'])
        self.assertEqual(doc['chunks'][0]['page'],'[第 1 页]')

    @unittest.skipUnless(importlib.util.find_spec('pypdf'),'Optional PDF dependency')
    def test_30_scanned_pdf_does_not_fabricate_text(self):
        from pypdf import PdfWriter
        buf=io.BytesIO();w=PdfWriter();w.add_blank_page(300,300);w.write(buf)
        with self.assertRaises(UserError) as ctx:
            self.app.preview_import(self.payload('blank.pdf',buf.getvalue()))
        self.assertIn('OCR',str(ctx.exception))

    def test_31_bulk_edit_keeps_history_and_stable_concept_ids(self):
        b=self.app.preview_import({'rows':[{'stem':f'例题{i}','options':['甲','乙'],'answer':'A','knowledge_points':['条件关系']} for i in range(2)]})
        self.app.commit_import(b['id'])
        original=self.app.store.all('questions')
        ids=[q['id'] for q in original]
        old_concept=original[0]['knowledge_point_ids'][0]
        result=self.app.dispatch('PATCH','/api/questions/bulk',{'ids':ids,'module':'判断推理','subtype':'逻辑判断'})
        self.assertEqual(result['updated'],2)
        for q in self.app.store.all('questions'):
            self.assertEqual(q['knowledge_point_ids'][0],old_concept)
            self.assertEqual(q['classification_status'],'confirmed')
            self.assertEqual(len(q['history']),1)

    def test_32_new_seen_question_does_not_count_as_independent_exam(self):
        b=self.app.preview_import({'rows':[{'stem':'测试题','options':['甲','乙'],'answer':'A'}]})
        self.app.commit_import(b['id'])
        s=self.app.create_session({'count':1,'kind':'exam','minutes':5})
        self.app.submit(s['id'])
        s2=self.app.create_session({'count':1,'kind':'exam','minutes':5})
        result=self.app.submit(s2['id'])
        self.assertFalse(result['independent'])
        self.assertFalse(self.app.estimate()['available'])


if __name__=='__main__':
    unittest.main(verbosity=2)
