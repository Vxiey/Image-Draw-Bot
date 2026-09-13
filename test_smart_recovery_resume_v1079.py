import threading
import unittest
from PIL import Image

from RenderResume import checkpoint_before_path, items_fingerprint, resolve_resume
from SmartRecovery import classify_interruption
from StrokeDeliveryVerification import StrokeDeliveryVerificationError
from Version import APP_VERSION, FILE_VERSION

from DrawBot import execute_plan
from test_drawbot import Mouse, NoWait


def executable_plan(resume=None):
    p=plan()
    p['options'].update({
        'delay':0.0,'speed':'Fast','precision':'Normal','human_mode':'Off','paint_current_color':False,
        'strict_color_verification':False,'adaptive_color_verification':False,'brush_px':1,'max_seconds':180,
        'render_resume_state':resume,'stroke_delivery_verification':'Off',
    })
    p['path_stats']={}
    return p


class TransientMouse(Mouse):
    def __init__(self, message, fail_move=3):
        super().__init__();self.message=message;self.fail_move=fail_move;self.move_count=0
    def move(self,x,y):
        self.move_count+=1
        if self.move_count>=self.fail_move:
            raise InterruptedError(self.message)
        return super().move(x,y)


def plan():
    return {
        'options':{'color_order':[0,1],'profile_key':'skribbl-fast'},
        'image':Image.new('RGB',(5,5),'white'),'fitted':(50,50),'count':4,
        'groups':[[(0,0,1,0),(1,0,2,0)],[(0,1,1,1),(1,1,2,1)]],
        'execution_groups':[
            [[(0,0),(1,0)],[(1,0),(2,0)]],
            [[(0,1),(1,1)],[(1,1),(2,1)]],
        ],
        'execution_sequence':[],
        'colors':((0,0,0),(255,0,0)),
        'color_selectors':({'kind':'palette','palette_index':0},{'kind':'palette','palette_index':1}),
    }


class SmartRecoveryV1079Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION,'1.0.145-rc29');self.assertEqual(FILE_VERSION,'1.0.145')

    def test_path_checkpoint_resumes_same_unfinished_path(self):
        p=plan();items=p['execution_groups'][0]
        state=checkpoint_before_path(p,1,1,len(items),ordered_items=items)
        r=resolve_resume(p,state)
        self.assertTrue(r['compatible']);self.assertTrue(r['path_level'])
        self.assertEqual(r['active_color_number'],1);self.assertEqual(r['next_path_index'],1)
        self.assertEqual(r['active_items_fingerprint'],items_fingerprint(items))

    def test_completed_previous_color_and_path_position_are_both_preserved(self):
        p=plan();items=p['execution_groups'][1]
        state=checkpoint_before_path(p,2,1,len(items),ordered_items=items)
        r=resolve_resume(p,state)
        self.assertEqual(r['completed_count'],1);self.assertEqual(r['active_color_number'],2);self.assertEqual(r['next_path_index'],1)

    def test_path_order_change_refuses_skip_when_executor_compares_fingerprint(self):
        p=plan();items=p['execution_groups'][0]
        state=checkpoint_before_path(p,1,1,len(items),ordered_items=items)
        r=resolve_resume(p,state)
        changed=list(reversed(items))
        self.assertNotEqual(r['active_items_fingerprint'],items_fingerprint(changed))

    def test_stroke_delivery_failure_is_recoverable_browser_interruption(self):
        d=classify_interruption(StrokeDeliveryVerificationError('Stroke delivery verification failed after 1 retry'),'skribbl-fast')
        self.assertTrue(d.recoverable);self.assertTrue(d.requires_recalibration);self.assertFalse(d.full_stop)

    def test_manual_mouse_or_transient_overlay_can_checkpoint_current_path(self):
        self.assertTrue(classify_interruption(InterruptedError('Stopped: the mouse was moved manually. No automatic restart.'),'gartic-phone').recoverable)
        self.assertTrue(classify_interruption(InterruptedError('Stopped: another window covers the click position.'),'sketchheads').recoverable)

    def test_canvas_or_target_geometry_error_is_hard_stop(self):
        d=classify_interruption(InterruptedError('Stopped: target window moved or changed size. Select the drawing area again.'),'skribbl')
        self.assertFalse(d.recoverable);self.assertTrue(d.full_stop)

    def test_time_limit_is_not_silently_resumed(self):
        d=classify_interruption(InterruptedError('Time limit reached. No automatic restart.'),'gartic-phone')
        self.assertFalse(d.recoverable)

    def test_execute_resume_skips_completed_paths_in_active_color(self):
        base=executable_plan();items=base['execution_groups'][0]
        state=checkpoint_before_path(base,1,1,len(items),ordered_items=items)
        resumed=executable_plan(state);mouse=Mouse();events=[]
        execute_plan(resumed,(100,100,50,50),[(10,10),(20,10)],mouse,NoWait(),threading.Event(),lambda *e:events.append(e))
        presses=sum(1 for a in mouse.actions if a==('press',))
        self.assertEqual(presses,3)  # one remaining path in color 1 + two in color 2
        self.assertTrue(any(k=='status' and 'skipping 1 already-completed path' in v for k,v in events if isinstance(v,str)))

    def test_transient_mid_path_saves_current_unfinished_path(self):
        p=executable_plan();mouse=TransientMouse('Stopped: another window covers the click position.',fail_move=3);saved=[]
        with self.assertRaises(InterruptedError):
            execute_plan(p,(100,100,50,50),[(10,10),(20,10)],mouse,NoWait(),threading.Event(),lambda *e:None,checkpoint=lambda x:saved.append(x))
        self.assertTrue(saved);self.assertTrue(saved[-1]['path_level']);self.assertEqual(saved[-1]['active_color_number'],1);self.assertEqual(saved[-1]['next_path_index'],0)

    def test_hard_target_geometry_failure_does_not_create_path_resume(self):
        p=executable_plan();mouse=TransientMouse('Stopped: target window moved or changed size. Select the drawing area again.',fail_move=3);saved=[]
        with self.assertRaises(InterruptedError):
            execute_plan(p,(100,100,50,50),[(10,10),(20,10)],mouse,NoWait(),threading.Event(),lambda *e:None,checkpoint=lambda x:saved.append(x))
        self.assertFalse(any(x.get('path_level') for x in saved))

if __name__=='__main__':unittest.main()
