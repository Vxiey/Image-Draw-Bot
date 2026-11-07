"""Modal native menu returns cannot leave a closed popup marked open."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from test_v148_ui_batch08_keyboard import event, selector_without_window


class NativeMenuReturnTests(unittest.TestCase):
    def selector(self, windowing_system):
        item = selector_without_window()
        item.tk = SimpleNamespace(call=Mock(return_value=windowing_system))
        item._current_height = 39
        item._apply_widget_scaling = lambda value: value
        return item

    def test_modal_return_without_enter_or_unmap_reopens_on_every_keyboard_press(self):
        for entry in ('pointer', 'keyboard'):
            with self.subTest(entry=entry):
                item = self.selector('win32')
                # Only the OS posting boundary is modeled: Windows returns
                # after dismissal and emits no Tk menu-window Unmap event.
                if entry == 'pointer':
                    item._open_dropdown_menu()
                    item._dropdown_menu.open.assert_called_once_with(120, 269)
                else:
                    item._keyboard_key_press(event('F4'))
                self.assertFalse(item._close_on_next_click)
                before = item._dropdown_menu.tk_popup.call_count
                for count in (1, 2):
                    item._keyboard_key_press(event('F4'))
                    self.assertEqual(item._dropdown_menu.tk_popup.call_count, before + count)
                    self.assertFalse(item._close_on_next_click)
                item._command.assert_not_called()
                self.assertEqual(item.get(), 'Balanced')
                self.assertTrue(all(call.args == ('tk', 'windowingsystem')
                                    for call in item.tk.call.call_args_list))

    def test_nonmodal_return_preserves_open_state_until_close_or_unmap(self):
        for entry in ('pointer', 'keyboard'):
            with self.subTest(entry=entry):
                item = self.selector('x11')
                if entry == 'pointer':
                    item._open_dropdown_menu()
                else:
                    item._keyboard_key_press(event('F4'))
                self.assertTrue(item._close_on_next_click)
                before = item._dropdown_menu.tk_popup.call_count
                item._keyboard_key_press(event('F4'))
                self.assertFalse(item._close_on_next_click)
                self.assertEqual(item._dropdown_menu.tk_popup.call_count, before)
                item._dropdown_menu.unpost.assert_called_once()
                item._keyboard_key_press(event('F4'))
                self.assertTrue(item._close_on_next_click)
                self.assertEqual(item._dropdown_menu.tk_popup.call_count, before + 1)
                item._keyboard_popup_unmapped()
                self.assertFalse(item._close_on_next_click)
                item._keyboard_key_press(event('F4'))
                self.assertEqual(item._dropdown_menu.tk_popup.call_count, before + 2)
                item._command.assert_not_called()
