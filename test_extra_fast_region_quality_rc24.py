import ast
import unittest
from pathlib import Path

from AutoDrawing import resolve_drawing
from BrowserBrushSize import POLICIES
from Version import APP_VERSION


class ExtraFastRegionQualityRc24Tests(unittest.TestCase):
    def test_extra_fast_overrides_stale_strong_simplify(self):
        opts={
            'render_preset':'Extra fast','adaptive_detail':'Strong simplify',
            'fill_tool_available':False,'erase_mode':False,'paint_current_color':False,
            'outline':False,'exact_color_available':False,
        }
        out=resolve_drawing(object(),opts)
        self.assertEqual(out['adaptive_detail'],'Auto')
        self.assertTrue(out['extra_fast_v2'])
        self.assertIn('regional hybrid',out['auto_drawing_meta']['engine'].lower())

    def test_gartic_policy_exposes_five_real_brush_levels(self):
        self.assertEqual(POLICIES['gartic-phone']['sizes'],(2,4,8,16,28))

    def test_make_plan_routes_extra_fast_to_adaptive_regions(self):
        source=Path('DrawBot.py').read_text(encoding='utf-8')
        tree=ast.parse(source)
        make_plan=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='make_plan')
        scope=next(n for n in make_plan.body if isinstance(n,ast.With))
        context=scope.items[0].context_expr
        self.assertIsInstance(context,ast.Call)
        self.assertIsInstance(context.func,ast.Name)
        self.assertEqual(context.func.id,'planning_calibration_scope')
        returned=scope.body[0]
        self.assertIsInstance(returned,ast.Return)
        self.assertIsInstance(returned.value,ast.Call)
        self.assertIsInstance(returned.value.func,ast.Name)
        self.assertEqual(returned.value.func.id,'_make_plan')
        self.assertEqual([n.id for n in returned.value.args],['original','area','options','cancelled'])
        implementation=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_make_plan')
        calls=[n for n in ast.walk(implementation) if isinstance(n,ast.Call)]
        names=[]
        for call in calls:
            fn=call.func
            if isinstance(fn,ast.Name):names.append(fn.id)
            elif isinstance(fn,ast.Attribute):names.append(fn.attr)
        self.assertIn('build_adaptive_hybrid_plan',names)

    def test_finish_plan_consumes_regional_groups_and_sequence(self):
        source=Path('DrawBot.py').read_text(encoding='utf-8')
        self.assertIn("adaptive_hybrid_prebuilt = options.get('_adaptive_hybrid_execution_groups')",source)
        self.assertIn("options.get('_adaptive_hybrid_execution_sequence')",source)
        self.assertIn('or adaptive_hybrid_prebuilt is not None',source)
        self.assertIn('adaptive_hybrid_prebuilt is None',source)
        self.assertIn('render_adaptive_preview',source)
        self.assertIn("'target_skipped_paths':0",source)

    def test_version_stays_rc24_for_hotfix_branch(self):
        self.assertEqual(APP_VERSION,'1.0.148')


if __name__=='__main__':
    unittest.main()
