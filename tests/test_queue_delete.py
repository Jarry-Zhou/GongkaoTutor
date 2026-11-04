import io
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import Application, UserError


class QueueDeleteTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Application(self.tmp.name);self.m=self.app.uploads

    def tearDown(self):
        self.m.tasks.join();self.tmp.cleanup()

    def make(self,data=b'Knowledge notes: B implies A, a necessary condition.',purpose='document'):
        name='note.md' if purpose=='document' else 'bank.json'
        batch=self.m.create({'files':[{'name':name,'size':len(data),'purpose':purpose}]})
        item=batch['files'][0]
        self.m.write_chunk(batch['id'],item['id'],0,len(data),io.BytesIO(data))
        return batch['id'],item['id']

    def item(self,b,f):return self.m.require(b,f)[1]

    def test_62_deleted_queued_task_is_never_parsed(self):
        b,f=self.make()
        with patch('file_imports.threading.Thread.start'):
            self.m.enqueue(b,f);self.m.remove(b,f)
        with patch.object(self.app,'add_document',side_effect=AssertionError('Deleted job must not parse')):
            self.m.run()
        self.assertEqual(self.item(b,f)['status'],'deleted')
        self.assertEqual(self.app.store.count('documents'),0)
        self.assertTrue(self.m.path_for(b,f).is_file())

    def test_63_delete_running_parser_stops_at_next_progress_callback(self):
        b,f=self.make();started=threading.Event();release=threading.Event()
        original=self.app.add_document
        def parse(payload,persist=True):
            started.set();release.wait(4);payload['_progress'](0,1,'OCR page finished')
            return original(payload,persist=persist)
        with patch.object(self.app,'add_document',side_effect=parse):
            self.m.enqueue(b,f)
            try:
                self.assertTrue(started.wait(3));self.assertEqual(self.m.remove(b,f)['status'],'deleting')
            finally:release.set()
            self.m.tasks.join()
        self.assertEqual(self.item(b,f)['status'],'deleted')
        self.assertEqual(self.app.store.count('documents'),0)

    def test_64_deletion_before_final_commit_cannot_leave_a_document(self):
        b,f=self.make();computed=threading.Event();release=threading.Event();original=self.app.add_document
        def parse(payload,persist=True):
            result=original(payload,persist=persist);computed.set();release.wait(4);return result
        with patch.object(self.app,'add_document',side_effect=parse):
            self.m.enqueue(b,f)
            try:self.assertTrue(computed.wait(3));self.m.remove(b,f)
            finally:release.set()
            self.m.tasks.join()
        self.assertEqual(self.item(b,f)['status'],'deleted')
        self.assertEqual(self.app.store.count('documents'),0)
        self.assertEqual(self.app.sources('necessary condition'),[])

    def test_65_committed_document_and_parsed_question_preview_are_protected(self):
        b,f=self.make();self.m.enqueue(b,f);self.m.tasks.join()
        with self.assertRaises(UserError):self.m.remove(b,f)
        self.assertEqual(self.app.store.count('documents'),1)
        data=json.dumps([{'stem':'Question','options':['A','B'],'answer':'A'}]).encode()
        qb,qf=self.make(data,'question_bank');self.m.enqueue(qb,qf);self.m.tasks.join()
        with self.assertRaises(UserError):self.m.remove(qb,qf)
        self.assertEqual(self.item(qb,qf)['status'],'preview_ready')
        self.m.commit(qb,qf);self.assertEqual(self.app.store.count('questions'),1)

    def test_66_restore_does_not_execute_a_stale_queue_entry_twice(self):
        b,f=self.make()
        with patch('file_imports.threading.Thread.start'):
            first=self.m.enqueue(b,f)['run_token'];self.m.remove(b,f);second=self.m.restore(b,f)['run_token']
        self.assertNotEqual(first,second)
        with patch.object(self.app,'add_document',wraps=self.app.add_document) as parser:self.m.run()
        self.assertEqual(parser.call_count,1)
        self.assertEqual(self.app.store.count('documents'),1)

    def test_67_restart_finalizes_deletion_and_does_not_resurrect_it(self):
        b,f=self.make();self.m.update(b,f,status='parsing');self.m.remove(b,f)
        restarted=Application(self.tmp.name)
        self.assertEqual(restarted.uploads.require(b,f)[1]['status'],'deleted')
        with self.assertRaises(UserError):restarted.uploads.enqueue(b,f)
        self.assertEqual(restarted.uploads.retry(b,f,{})['status'],'deleted')

    def test_68_deleted_partial_upload_is_rejected_and_can_be_restored(self):
        b=self.m.create({'files':[{'name':'note.md','size':10,'purpose':'document'}]});f=b['files'][0]['id'];b=b['id']
        self.m.write_chunk(b,f,0,4,io.BytesIO(b'abcd'));self.m.remove(b,f)
        with self.assertRaises(UserError) as error:self.m.write_chunk(b,f,4,6,io.BytesIO(b'efghij'))
        self.assertNotIn('expected_offset',error.exception.details or {})
        self.assertEqual(self.m.restore(b,f)['uploaded_bytes'],4)
        self.m.write_chunk(b,f,4,6,io.BytesIO(b'efghij'));self.m.enqueue(b,f);self.m.tasks.join()
        self.assertEqual(self.item(b,f)['status'],'completed')

    def test_69_bulk_delete_keeps_newly_completed_items_and_validates_ids(self):
        b,f=self.make();other,of=self.make(b'Separate task')
        with self.assertRaises(UserError):self.m.remove_pending(b,{'file_ids':[f,of]})
        self.assertEqual(self.item(b,f)['status'],'uploaded')
        self.m.enqueue(b,f);self.m.tasks.join()
        result=self.m.remove_pending(b,{'file_ids':[f]})
        self.assertEqual(result['kept'],[f]);self.assertEqual(result['deleted'],[])
        self.assertEqual(self.item(other,of)['status'],'uploaded')

    def test_70_delete_and_restore_api_are_idempotent(self):
        b,f=self.make();path=f'/api/file-imports/{b}/files/{f}'
        self.assertEqual(self.app.dispatch('DELETE',path,{})['status'],'deleted')
        self.assertEqual(self.app.dispatch('DELETE',path,{})['status'],'deleted')
        self.app.dispatch('POST',path+'/restore',{});self.m.tasks.join()
        self.assertEqual(self.app.dispatch('POST',path+'/restore',{})['status'],'completed')
        self.assertEqual(self.app.store.count('documents'),1)

    def test_71_parser_failure_after_delete_does_not_revive_as_error(self):
        b,f=self.make();started=threading.Event();release=threading.Event()
        def parse(*args,**kwargs):started.set();release.wait(4);raise RuntimeError('Parser failed')
        with patch.object(self.app,'add_document',side_effect=parse):
            self.m.enqueue(b,f)
            try:self.assertTrue(started.wait(3));self.m.remove(b,f)
            finally:release.set()
            self.m.tasks.join()
        self.assertEqual(self.item(b,f)['status'],'deleted')
        self.assertEqual(self.item(b,f)['error'],'')

    def test_72_deleting_one_file_does_not_stop_other_queued_files(self):
        b,f=self.make();other,of=self.make(b'Another surviving knowledge note')
        with patch('file_imports.threading.Thread.start'):
            self.m.enqueue(b,f);self.m.enqueue(other,of);self.m.remove(b,f)
        self.m.run()
        self.assertEqual(self.item(b,f)['status'],'deleted');self.assertEqual(self.item(other,of)['status'],'completed')
        self.assertEqual(self.app.store.count('documents'),1)


if __name__=='__main__':unittest.main()
