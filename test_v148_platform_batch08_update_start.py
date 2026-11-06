"""An updater must respect the actual settings writer's failed-save result."""
import queue
import threading
import unittest
from unittest.mock import Mock, patch

from DrawBot import DrawBotApp
import test_v148_application_batch04_settings as settings_fixtures


class UpdateSaveBoundaryTests(unittest.TestCase):
    def setUp(self):
        fixture = settings_fixtures.LocalSettingsTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.app, self.path = fixture.app, fixture.path
        self.app.activity = None
        self.app.stop = threading.Event()
        self.app.events = queue.Queue()
        self.app.update_request = object()
        self.app.update_summary = Mock()
        self.app.begin_worker = Mock(return_value=True)
        self.app.save_settings = lambda: DrawBotApp.save_settings(self.app)
        self.payload = {'request':self.app.update_request,'installer_path':'unused.exe',
                        'installer':{'test':'metadata passed unchanged to verified launcher'}}

    def test_actual_disk_failure_prevents_install_and_preserves_request_and_previous_settings(self):
        self.path.write_bytes(b'previous saved settings')
        with patch('DrawBot.atomic_write_text',side_effect=OSError('controlled disk failure')), \
                patch('DrawBot.log_event'):
            self.assertFalse(DrawBotApp._install_checked_update(self.app,self.payload))
        self.assertEqual(self.path.read_bytes(), b'previous saved settings')
        self.assertIs(self.app.update_request, self.payload['request'])
        self.app.begin_worker.assert_not_called()
        self.assertIn('Nothing was installed', self.app.update_summary.set.call_args.args[0])

    def test_protected_newer_settings_schema_also_blocks_automatic_install(self):
        self.path.write_text('{"settings_schema":3,"future_preference":true}')
        self.app._settings_protected_path = self.path
        before = self.path.read_bytes()
        self.assertFalse(DrawBotApp._install_checked_update(self.app,self.payload))
        self.assertEqual(self.path.read_bytes(), before)
        self.app.begin_worker.assert_not_called()

    def test_successful_actual_save_schedules_one_verified_install_and_consumes_request(self):
        self.assertTrue(DrawBotApp._install_checked_update(self.app,self.payload))
        self.assertTrue(self.path.is_file())
        self.assertIsNone(self.app.update_request)
        self.app.begin_worker.assert_called_once()
        self.assertEqual(self.app.begin_worker.call_args.args[0], 'update-install')
        with patch('UpdateCenter.launch_installer') as launch:
            self.app.begin_worker.call_args.args[1]()
        launch.assert_called_once_with(self.payload['installer_path'], self.payload['installer'],
                                       cancelled=self.app.stop.is_set)
        self.assertEqual(self.app.events.get_nowait(), ('update_installer_started',True))
        self.assertFalse(DrawBotApp._install_checked_update(self.app,self.payload))
        self.app.begin_worker.assert_called_once()


if __name__ == '__main__':
    unittest.main()
