import unittest

import PictureCustomPalette as pcp
from UiTransactionRuntime import AdaptivePacer, UiTransaction


class Mouse:
    def __init__(self):
        self.actions=[]
        self.armed=False
    def arm_input(self):
        self.armed=True; self.actions.append(('arm',))
    def disarm_input(self):
        self.armed=False; self.actions.append(('disarm',))
    def move(self,x,y):
        self.actions.append(('move',int(x),int(y)))
    def click(self):
        self.actions.append(('click',))


class Keyboard:
    def __init__(self): self.actions=[]
    def press_and_release(self,key): self.actions.append(('press',str(key)))
    def write(self,text,delay=0): self.actions.append(('write',str(text)))


CONTROLS={
    'OpenCustomColor':(10,10),
    'RedField':(20,20),
    'GreenField':(30,30),
    'BlueField':(40,40),
    'ConfirmColor':(50,50),
    'AddCustomColor':(60,60),
}


class UiTransactionRuntimeTests(unittest.TestCase):
    def test_retry_is_bounded_and_pacer_grows_after_failure(self):
        waits=[];calls=[]
        tx=UiTransaction(max_attempts=3,pacer=AdaptivePacer(base_delay=.02,max_delay=.2),wait=waits.append)
        def operation(attempt):
            calls.append(attempt)
            if attempt<3: raise TimeoutError('slow UI')
            return 'ok'
        self.assertEqual(tx.retry(operation),'ok')
        self.assertEqual(calls,[1,2,3])
        self.assertEqual(len(waits),2)
        self.assertTrue(all(v>=.02 for v in waits))
        self.assertIn('RECOVER',[e.state for e in tx.history])

    def test_final_retry_preserves_original_exception(self):
        tx=UiTransaction(max_attempts=2,wait=lambda _s:None)
        with self.assertRaisesRegex(ValueError,'still wrong'):
            tx.retry(lambda _attempt: (_ for _ in ()).throw(ValueError('still wrong')))
        self.assertEqual(tx.state,'FAILED')


class PaintPaletteRetryTests(unittest.TestCase):
    def test_transient_rgb_rejection_retypes_then_commits_once(self):
        mouse=Mouse();keyboard=Keyboard();states=[];waits=[];checks={'n':0}
        def color_ready(_rgb):
            checks['n']+=1
            if checks['n']==1:
                raise TimeoutError('Paint has not updated the fields yet')
            return {}
        count=pcp.apply_custom_rgb_sequence(
            mouse,keyboard,CONTROLS,[(12,34,56)],
            retry_limit=3,
            wait=waits.append,
            color_ready=color_ready,
            state_callback=lambda event:states.append(event.state),
        )
        self.assertEqual(count,1)
        self.assertFalse(mouse.armed)
        self.assertEqual(checks['n'],2)
        self.assertEqual([a for a in keyboard.actions if a[0]=='write'],[
            ('write','12'),('write','34'),('write','56'),
            ('write','12'),('write','34'),('write','56'),
        ])
        self.assertEqual(mouse.actions.count(('move',60,60)),1)
        self.assertIn('RECOVER',states)
        self.assertIn('VERIFY_VALUE',states)
        self.assertEqual(states[-1],'DONE')

    def test_persistent_rejection_never_clicks_add(self):
        mouse=Mouse();keyboard=Keyboard()
        def rejected(_rgb): raise ValueError('wrong RGB')
        with self.assertRaisesRegex(ValueError,'wrong RGB'):
            pcp.apply_custom_rgb_sequence(
                mouse,keyboard,CONTROLS,[(1,2,3)],retry_limit=3,
                wait=lambda _s:None,color_ready=rejected,
                input_guard=lambda _point,**_kwargs:None,  # owned fake modal permits cleanup
            )
        self.assertEqual(mouse.actions.count(('move',60,60)),0)
        self.assertFalse(mouse.armed)
        self.assertIn(('press','esc'),keyboard.actions)

    def test_production_adapter_enables_three_attempts(self):
        mouse=Mouse();keyboard=Keyboard();checks={'n':0}
        def color_ready(_rgb):
            checks['n']+=1
            if checks['n']<3: raise TimeoutError('not ready')
            return {}
        count=pcp._production_apply_custom_rgb_sequence(
            mouse,keyboard,CONTROLS,[(9,8,7)],wait=lambda _s:None,color_ready=color_ready
        )
        self.assertEqual(count,1)
        self.assertEqual(checks['n'],3)
        self.assertEqual(mouse.actions.count(('move',60,60)),1)


if __name__=='__main__':
    unittest.main()
