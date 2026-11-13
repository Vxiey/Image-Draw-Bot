"""Replacing help text must not retain duplicate event/timer owners."""
import unittest
from unittest.mock import Mock, patch
import StudioUI


class TooltipReplacementTests(unittest.TestCase):
    def test_repeated_help_updates_reuse_one_owner_and_one_binding_set(self):
        widget = Mock()
        widget._image_draw_bot_tooltip = None
        self.assertIs(StudioUI.tooltip(widget, 'Old help'), widget)
        original = widget._image_draw_bot_tooltip
        original._enter()
        old_job = original.job
        popup = Mock()
        original.window = popup
        initial_bindings = widget.bind.call_count
        for value in ('Updated help', 'Newest help'):
            self.assertIs(StudioUI.tooltip(widget, value), widget)
            self.assertIs(widget._image_draw_bot_tooltip, original)
        self.assertEqual(widget.bind.call_count, initial_bindings)
        self.assertEqual(initial_bindings, 6)
        widget.after_cancel.assert_called_once_with(old_job)
        popup.destroy.assert_called_once_with()
        self.assertIsNone(original.job)
        self.assertIsNone(original.window)
        self.assertEqual(original.text, 'Newest help')
        # Every retained binding still targets the one current owner.
        self.assertTrue(all(call.args[1].__self__ is original
                            for call in widget.bind.call_args_list))
        original._enter()
        self.assertEqual(widget.after.call_args.args[1], original._show)

    def test_updated_text_is_used_by_the_next_popup(self):
        widget = Mock()
        widget._image_draw_bot_tooltip = None
        for name, value in [('rootx', 10), ('rooty', 20), ('height', 30),
                            ('vrootx', 0), ('vrooty', 0),
                            ('vrootwidth', 1000), ('vrootheight', 800)]:
            getattr(widget, 'winfo_' + name).return_value = value
        StudioUI.tooltip(widget, 'Old help')
        original = widget._image_draw_bot_tooltip
        StudioUI.tooltip(widget, 'Updated help')
        with patch.object(StudioUI.tk, 'Toplevel') as top, patch.object(StudioUI.tk, 'Label') as label:
            top.return_value.winfo_reqwidth.return_value = 200
            top.return_value.winfo_reqheight.return_value = 70
            original._show()
            self.assertEqual(label.call_args.kwargs['text'], 'Updated help')


if __name__ == '__main__':
    unittest.main()
