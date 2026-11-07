"""Short native windows reserve room for the selected workspace at high DPI."""
from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from ResponsiveWorkspace import ResponsiveWorkspace
import test_v148_ui_batch06_workspace as fixtures


class Widget(fixtures.Widget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.height = 960
        self.binding_tokens = {}
        self.unbound = []

    def winfo_height(self):
        return self.height

    def bind(self, name, callback, **kwargs):
        token = 'owned-' + str(len(self.binding_tokens))
        self.binding_tokens[token] = (name, callback)
        return token

    def unbind(self, name, token):
        self.unbound.append((name, token))
        del self.binding_tokens[token]


class WindowHeightTests(unittest.TestCase):
    def create(self, stack, height=960, scale=1, main_width=1200):
        stack.enter_context(patch('ResponsiveWorkspace.tk.StringVar', fixtures.Value))
        for name in ('Frame', 'Label', 'Combobox'):
            stack.enter_context(patch('ResponsiveWorkspace.ttk.' + name, Widget))
        window = Widget(); window.height = height
        main, header, footer = (Widget(window) for _ in range(3))
        row = Widget(footer)
        main.scale = scale
        main.width = main_width
        header.width = 1200
        groups = tuple(Widget(header) for _ in range(3))
        actions = tuple(Widget(groups[-1]) for _ in range(4))
        for action in actions:
            action.command = Mock()
            action.request = 120
        panels = {name: Widget(main) for name in ('Setup', 'Workspace', 'Readiness')}
        layout = ResponsiveWorkspace(main, panels, window=window, header=header,
            header_groups=groups, header_actions=actions, footer=footer, footer_row=row)
        main.flush()
        return window, main, header, footer, row, groups, actions, layout

    def test_starved_unmapped_main_compacts_chrome_before_waiting_for_panel_width(self):
        with ExitStack() as stack:
            _, main, header, _, _, groups, _, layout = self.create(stack,
                height=500, scale=1.5, main_width=1)
            self.assertTrue(layout.compact_height)
            self.assertIsNone(layout.compact)
            self.assertIsNone(groups[0].layout)
            self.assertIsNone(groups[1].layout)
            self.assertEqual(header.layout[1]['pady'], (6, 4))
            self.assertEqual(groups[2].layout[1]['row'], 0)
            main.width = 584
            layout.schedule(SimpleNamespace(widget=main)); main.flush()
            self.assertTrue(layout.compact)
            self.assertEqual(layout.panels['Setup'].layout[1]['row'], 1)

    def test_same_client_height_enters_compact_chrome_when_control_scaling_increases(self):
        with ExitStack() as stack:
            window, main, header, footer, row, groups, actions, layout = self.create(stack, height=700)
            self.assertFalse(layout.compact_height)
            self.assertTrue(all(group.layout for group in groups))
            main.scale = 1.5
            layout.schedule(SimpleNamespace(widget=window)); main.flush()
            self.assertTrue(layout.compact_height)
            self.assertIsNone(groups[0].layout)
            self.assertIsNone(groups[1].layout)
            self.assertEqual(groups[2].layout[1]['row'], 0)
            self.assertEqual(header.layout[1]['pady'], (6, 4))
            self.assertEqual(footer.layout[1]['pady'], (4, 6))
            self.assertEqual(row.layout[1]['pady'], (6, 4))
            self.assertEqual(main.layout[1]['padx'], 12)
            self.assertTrue(all(action.command.call_count == 0 for action in actions))
            self.assertEqual(window.height, 700)
            main.scale = 1
            layout.schedule(SimpleNamespace(widget=window)); main.flush()
            self.assertFalse(layout.compact_height)
            self.assertTrue(all(group.layout for group in groups))
            self.assertEqual(header.layout[1]['pady'], (18, 10))
            self.assertEqual(footer.layout[1]['pady'], (10, 16))
            self.assertEqual(row.layout[1]['pady'], (11, 7))
            self.assertEqual(main.layout[1]['padx'], 22)

    def test_observed_650_by_500_metrics_leave_panel_height_after_compacting_chrome(self):
        with ExitStack() as stack:
            window, main, header, footer, row, groups, _, layout = self.create(stack, height=500, scale=1.5)
            # Independent arithmetic using the actual failing Windows trace:
            # header 156, footer 220, outer padding 81, navigation 43 left 0.
            self.assertEqual(500 - 156 - 220 - 81 - 43, 0)
            # Its actionable header row needs 60 physical px. Hiding the
            # branding row and reducing only spacing must leave useful height
            # even when the enabled Pause adds 25 px to the footer grid.
            scale = main.scale
            outside = sum(header.layout[1]['pady']) * scale + sum(footer.layout[1]['pady']) * scale
            footer_height = 220 - 18 * scale + sum(row.layout[1]['pady']) * scale
            panel_height = window.height - 60 - footer_height - outside - 43
            self.assertGreaterEqual(panel_height - 25, 48 * scale)
            self.assertEqual(groups[2].layout[1]['row'], 0)
            for name in layout.panels:
                layout.select(name)
                self.assertEqual(layout.panels[name].layout[1]['row'], 1)

    def test_root_resize_is_coalesced_and_its_owned_binding_is_removed(self):
        with ExitStack() as stack:
            window, main, _, _, _, _, _, layout = self.create(stack)
            unrelated = window.bind('<Configure>', Mock(), add='+')
            owned = layout._window_binding
            for _ in range(20):
                layout.schedule(SimpleNamespace(widget=window))
            self.assertEqual(len(main.jobs), 1)
            layout.dispose(SimpleNamespace(widget=main))
            self.assertFalse(main.jobs)
            self.assertEqual(window.unbound, [('<Configure>', owned)])
            self.assertIn(unrelated, window.binding_tokens)
            layout.schedule(SimpleNamespace(widget=window))
            self.assertFalse(main.jobs)


if __name__ == '__main__':
    unittest.main()
