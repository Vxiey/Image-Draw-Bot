\
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from DrawBot import DrawBotApp
from PreviewQuality import full_preview_options
from Version import APP_VERSION


class Value:
    def __init__(self,value):self.value=value
    def get(self):return self.value
    def set(self,value):self.value=value


class Rc16PreviewParityTests(unittest.TestCase):
    def test_manual_build_preview_routes_to_full_detail_planner(self):
        app=SimpleNamespace(original=object(),preview_mode=Value('Manual'),status=Value(''))
        calls=[]
        app.update_plan=lambda **kw:calls.append(kw) or kw
        result=DrawBotApp.request_preview(app)
        self.assertTrue(result['user_initiated']);self.assertTrue(result['full_detail'])

    def test_auto_full_button_routes_to_full_detail_planner(self):
        app=SimpleNamespace(original=object(),preview_mode=Value('Auto full'),status=Value(''))
        app.update_plan=lambda **kw:kw
        self.assertTrue(DrawBotApp.request_preview(app)['full_detail'])

    def test_auto_light_button_keeps_bounded_preview(self):
        app=SimpleNamespace(original=object(),preview_mode=Value('Auto light'),status=Value(''))
        app.update_plan=lambda **kw:kw
        self.assertFalse(DrawBotApp.request_preview(app)['full_detail'])

    def test_full_detail_preview_preserves_quality_and_caps_workers(self):
        options={'ram_budget_mb':2048,'cpu_workers':'8','cpu_workers_resolved':8,
                 'color_layers':'All','planning_resolution':'Extreme','max_seconds':90,
                 'preview_mode':'Manual'}
        out=full_preview_options(options,(1200,800))
        self.assertFalse(out['_preview_plan']);self.assertTrue(out['_full_detail_preview'])
        self.assertEqual(out['planning_resolution'],'Extreme');self.assertEqual(out['color_layers'],'All')
        self.assertEqual(out['cpu_workers'],'4');self.assertEqual(out['cpu_workers_resolved'],4)
        self.assertEqual(out['gpu_mode'],'CPU')
        self.assertEqual(out['_preview_resource_policy'],'full-detail-planner-parity')

    def test_single_worker_request_stays_single_worker(self):
        out=full_preview_options({'ram_budget_mb':1024,'cpu_workers':'1'},(800,500))
        self.assertEqual(out['cpu_workers_resolved'],1)

    def test_source_options_are_not_mutated(self):
        options={'ram_budget_mb':1024,'cpu_workers':'8','color_layers':'All'}
        before=dict(options);full_preview_options(options,(800,500));self.assertEqual(options,before)

    def test_version(self):self.assertEqual(APP_VERSION,'1.0.146-rc2')


if __name__=='__main__':unittest.main()
