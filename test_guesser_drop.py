import queue
import tempfile
import threading
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from WordGuesser import find_candidates,load_words
from DrawBot import DrawBotApp

class Value:
    def __init__(self,value=None):self.value=value
    def get(self):return self.value
    def set(self,value):self.value=value

class GuesserTests(unittest.TestCase):
    def test_length_and_letters(self):
        self.assertEqual(find_candidates(['katt','kort','kotte','ko'],'k__t','4'),['katt','kort'])
    def test_swedish_unicode(self):
        self.assertEqual(find_candidates(['äpple','åska'],'A\u0308____'),['äpple'])
    def test_multiple_words(self):
        self.assertEqual(find_candidates(['röd bil','röd båt'],'r_d b_l','6'),['röd bil'])
    def test_invalid_and_conflicting_input(self):
        for pattern,length in [('k__t','5'),('.*',''),('','0'),('','')]:
            with self.assertRaises(ValueError):find_candidates(['katt'],pattern,length)
    def test_import_deduplicates_and_rejects_bad_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'words.txt';path.write_text('\ufeffKatt\nkatt\nRöd bil\n# kommentar\n',encoding='utf8')
            self.assertEqual(load_words(path),('katt','röd bil'))
            path.write_text('123',encoding='utf8')
            with self.assertRaises(ValueError):load_words(path)

class DropTests(unittest.TestCase):
    def make_app(self):
        app=SimpleNamespace(activity=None,closing=False,root=SimpleNamespace(tk=tk.Tcl()),drop_mode=Value('Draw immediately'),palette_ready=True,corners=[(0,0),(10,10)],target_window=(123,(0,0,100,100)),status=Value(),loads=[])
        app.load_source=lambda *args,**kw:app.loads.append((args,kw))
        # The load callback closes over app, so refcounting alone cannot retire
        # its creator-thread Tcl interpreter. Detach it during test cleanup,
        # before a later planning worker triggers cyclic collection.
        self.addCleanup(setattr, app.root, 'tk', None)
        return app
    def test_braced_path_only_loads_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'min bild.png';path.write_bytes(b'test')
            app=self.make_app()
            self.assertEqual(DrawBotApp.drop_image(app,SimpleNamespace(data='{'+str(path)+'}')),'copy')
            self.assertEqual(app.loads[0][1],{'action':None})
    def test_unconfigured_only_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'bild.png';path.write_bytes(b'test');app=self.make_app();app.palette_ready=False
            DrawBotApp.drop_image(app,SimpleNamespace(data=str(path)))
            self.assertEqual(app.loads[0][1],{'action':None})
    def test_busy_rejects_drop(self):
        app=self.make_app();app.activity='draw'
        self.assertEqual(DrawBotApp.drop_image(app,SimpleNamespace(data='anything')),'none');self.assertEqual(app.loads,[])
    def test_escape_cancels_queued_direct_start(self):
        app=SimpleNamespace(events=queue.Queue(),stop=threading.Event(),drop_action_pending='Draw immediately',activity=None,closing=False,needs_plan=False,root=SimpleNamespace(after=lambda *args:None),poll=lambda:None)
        app.stop.set();app.draw=lambda:self.fail('Must not draw after Esc')
        DrawBotApp.poll(app);self.assertIsNone(app.drop_action_pending)
    def test_old_direct_start_is_discarded_without_drawing(self):
        calls=[];plans=[]
        app=SimpleNamespace(events=queue.Queue(),stop=threading.Event(),drop_action_pending='Draw immediately',activity=None,closing=False,needs_plan=True,root=SimpleNamespace(after=lambda *args:None),poll=lambda:None,draw=lambda:calls.append('draw'),update_plan=lambda:plans.append('plan'))
        DrawBotApp.poll(app);DrawBotApp.poll(app)
        self.assertEqual(calls,[]);self.assertEqual(plans,['plan']);self.assertIsNone(app.drop_action_pending)

if __name__=='__main__':unittest.main()
