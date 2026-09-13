\
import base64
import threading
import unittest
from pathlib import Path
from PIL import Image

from RenderResume import (checkpoint_after_batch, checkpoint_sequence_progress, resolve_resume,
                          sequence_entry_key, validate_progress)
from SmartRecovery import classify_interruption
from Version import APP_VERSION


def seq_plan(sequence=None, resume=None):
    seq=sequence or [
        {'color_index':0,'path':[(0,0),(4,0)],'phase':'major_coverage','brush_px':8,'operation_type':'stroke'},
        {'color_index':1,'path':[(0,1),(4,1)],'phase':'structure','brush_px':4,'operation_type':'stroke'},
        {'color_index':0,'path':[(1,2),(2,2)],'phase':'important_details','brush_px':2,'operation_type':'stroke'},
        {'color_index':2,'path':[(3,3),(3,4)],'phase':'accuracy','brush_px':2,'operation_type':'stroke'},
    ]
    return {
        'options':{'profile_key':'gartic-phone','profile_name':'Gartic Phone','brush_px':2,'speed':'Fast','precision':'High','drawing_mode':'Smart paths','render_resume_state':resume},
        'image':Image.new('RGB',(8,6),'white'),'fitted':(80,60),'groups':[[(0,0,4,0)],[(0,1,4,1)],[(3,3,3,4)]],
        'execution_groups':None,'execution_sequence':list(seq),'count':len(seq),
        'colors':((200,10,10),(10,200,10),(10,10,200)),
        'color_selectors':({'kind':'palette','palette_index':0},{'kind':'palette','palette_index':1},{'kind':'palette','palette_index':2}),
        'plan_area':(0,0,80,60),
    }


class Rc14SequenceResumeTests(unittest.TestCase):
    def test_sequence_checkpoint_survives_runtime_reorder(self):
        plan=seq_plan();keys=[sequence_entry_key(row) for row in plan['execution_sequence']]
        state=checkpoint_sequence_progress(plan,{keys[0]:1,keys[2]:1},last_entry=plan['execution_sequence'][2])
        reordered=seq_plan([plan['execution_sequence'][3],plan['execution_sequence'][2],plan['execution_sequence'][0],plan['execution_sequence'][1]])
        resolved=resolve_resume(reordered,state)
        self.assertTrue(resolved['compatible']);self.assertTrue(resolved['sequence_level'])
        self.assertEqual(resolved['sequence_completed_count'],2);self.assertEqual(resolved['sequence_remaining_count'],2)
        self.assertEqual(sum(resolved['sequence_completed_counts'].values()),2)

    def test_changed_sequence_operation_rejects_resume(self):
        plan=seq_plan();key=sequence_entry_key(plan['execution_sequence'][0])
        state=checkpoint_sequence_progress(plan,{key:1})
        changed=seq_plan();changed['execution_sequence'][0]=dict(changed['execution_sequence'][0],brush_px=16)
        resolved=resolve_resume(changed,state)
        self.assertFalse(resolved['compatible']);self.assertIn('sequence',resolved['reason'])

    def test_compact_bitset_and_corruption_guard(self):
        plan=seq_plan();counts={sequence_entry_key(row):1 for row in plan['execution_sequence'][:3]}
        state=checkpoint_sequence_progress(plan,counts)
        self.assertTrue(state['sequence_level']);self.assertEqual(state['sequence_completed_count'],3)
        self.assertLessEqual(len(base64.b64decode(state['sequence_completed_bits'])),1)
        broken=dict(state,sequence_completed_bits='%%%')
        self.assertIsNone(validate_progress(broken))

    def test_old_color_checkpoint_still_rejected_for_progressive_plan(self):
        base=seq_plan();base['execution_sequence']=[]
        state=checkpoint_after_batch(base,1)
        resolved=resolve_resume(seq_plan(),state)
        self.assertFalse(resolved['compatible']);self.assertIn('sequence checkpoint',resolved['reason'])

    def test_target_disappearance_is_checkpointable_but_requires_recalibration(self):
        decision=classify_interruption(ValueError('Target window no longer exists.'),'gartic-phone')
        self.assertTrue(decision.recoverable);self.assertTrue(decision.requires_recalibration);self.assertTrue(decision.full_stop)

    def test_drawbot_integrates_sequence_checkpointing(self):
        src=Path('DrawBot.py').read_text(encoding='utf-8')
        self.assertIn('checkpoint_sequence_progress',src);self.assertIn('sequence_completed_counts',src)
        self.assertIn('sequence_new_completed%25==0',src);self.assertIn('Dynamic Replanner may safely reorder only the remaining work',src)

    def test_version(self):self.assertEqual(APP_VERSION,'1.0.146-rc1')


if __name__=='__main__':unittest.main()
