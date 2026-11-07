"""Public word-filter callbacks expose all matches through bounded UI pages."""
import sys
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import customtkinter as ctk

import DrawBot
import StudioUI
from WordHelperResults import PAGE_SIZE, results_for
from test_precision_v102 import Value


WORDS = tuple('word' + chr(97 + index // (26 * 26)) + chr(97 + index // 26 % 26)
              + chr(97 + index % 26) for index in range(451))


class Listbox:
    def __init__(self):
        self.rows = []
        self.selection = ()
        self.insertions = []
        self.alive = True

    def winfo_exists(self): return self.alive
    def delete(self, start, end): self.rows = []; self.selection = ()
    def insert(self, index, *rows): self.insertions.append(rows); self.rows.extend(rows)
    def selection_set(self, index): self.selection = (index,)
    def curselection(self): return self.selection
    def get(self, index): return self.rows[index]
    def activate(self, index): self.active = index
    def see(self, index): self.visible = index


class Button:
    def __init__(self): self.values = {}
    def configure(self, **values): self.values.update(values)
    def invoke(self):
        if self.values.get('state') != 'disabled':
            return self.values['command']()


def app_fixture():
    app = SimpleNamespace(guess_words=WORDS, guess_pattern=Value(''), guess_length=Value('7'),
        guess_result=Value(''), guess_list=Listbox(), activity=None, closing=False,
        root=SimpleNamespace(clipboard_clear=Mock(), clipboard_append=Mock()), status=Mock())
    pager = results_for(app)
    previous, following = Button(), Button()
    pager.set_navigation(previous, following)
    return app, pager, previous, following


class CompleteWordResultsTests(unittest.TestCase):
    def test_actual_filter_and_navigation_reach_every_match_in_deterministic_order(self):
        app, pager, previous, following = app_fixture()
        DrawBot.DrawBotApp.update_guesses(app)
        self.assertEqual(pager.page_count, 3)
        self.assertEqual(app.guess_list.rows, list(WORDS[:200]))
        self.assertIn('Showing 1–200 of 451', app.guess_result.get())
        self.assertEqual(previous.values['state'], 'disabled')
        self.assertEqual(following.values['state'], 'normal')
        observed = list(app.guess_list.rows)
        while following.values['state'] == 'normal':
            following.invoke()
            observed.extend(app.guess_list.rows)
        self.assertEqual(observed, list(WORDS))
        self.assertIn('Showing 401–451 of 451', app.guess_result.get())
        self.assertFalse(pager.next())
        self.assertEqual(previous.values['state'], 'normal')
        previous.invoke()
        self.assertEqual(app.guess_list.rows, list(WORDS[200:400]))
        self.assertEqual(app.guess_list.insertions, [WORDS[:200], WORDS[200:400], WORDS[400:], WORDS[200:400]])

    def test_copy_selected_uses_the_visible_page_and_resets_selection_between_pages(self):
        app, pager, _previous, following = app_fixture()
        DrawBot.DrawBotApp.update_guesses(app)
        app.guess_list.selection_set(150)
        following.invoke()
        self.assertEqual(app.guess_list.curselection(), (0,))
        DrawBot.DrawBotApp.copy_guess(app)
        app.root.clipboard_append.assert_called_once_with(WORDS[200])
        self.assertEqual(app.guess_list.visible, 0)

    def test_changed_query_or_word_snapshot_starts_at_first_page_and_clears_old_errors(self):
        app, pager, previous, following = app_fixture()
        DrawBot.DrawBotApp.update_guesses(app)
        following.invoke(); following.invoke()
        app.guess_pattern.set('wordaa?')
        DrawBot.DrawBotApp.update_guesses(app)
        self.assertEqual(pager.page, 0)
        self.assertEqual(app.guess_list.rows, list(WORDS[:26]))
        self.assertEqual(previous.values['state'], 'disabled')
        self.assertEqual(following.values['state'], 'disabled')
        app.guess_words = ('wordaaz',)
        DrawBot.DrawBotApp.update_guesses(app)
        self.assertEqual(app.guess_list.rows, ['wordaaz'])
        self.assertIn('Showing 1–1 of 1', app.guess_result.get())
        app.guess_pattern.set('bad!')
        DrawBot.DrawBotApp.update_guesses(app)
        self.assertFalse(pager.matches)
        self.assertFalse(app.guess_list.rows)
        self.assertFalse(app.guess_list.curselection())
        self.assertIn('Pattern:', app.guess_result.get())
        app.guess_pattern.set('zzzzzzz')
        DrawBot.DrawBotApp.update_guesses(app)
        self.assertEqual(app.guess_result.get(), '0 possible words. No confidence ranking.')
        app.guess_pattern.set('wordaa?')
        DrawBot.DrawBotApp.update_guesses(app)
        self.assertEqual(app.guess_list.rows, ['wordaaz'])

    def test_page_boundaries_have_no_empty_extra_page(self):
        for count in (0, 1, 199, 200, 201, 400):
            with self.subTest(count=count):
                app, pager, previous, following = app_fixture()
                app.guess_words = WORDS[:count]
                DrawBot.DrawBotApp.update_guesses(app)
                pages = 0
                while True:
                    if app.guess_list.rows: pages += 1
                    self.assertLessEqual(len(app.guess_list.rows), PAGE_SIZE)
                    if not following.invoke(): break
                self.assertEqual(pages, (count + 199) // 200)
                self.assertEqual(following.values['state'], 'disabled')

    def test_stale_navigation_does_not_touch_busy_closed_or_destroyed_widgets(self):
        for state in ('busy', 'closing', 'destroyed'):
            with self.subTest(state=state):
                app, pager, previous, following = app_fixture()
                DrawBot.DrawBotApp.update_guesses(app)
                before = tuple(app.guess_list.rows)
                if state == 'busy': app.activity = 'draw'
                elif state == 'closing': app.closing = True
                else: app.guess_list.alive = False
                self.assertFalse(pager.next())
                pager.refresh_controls()
                self.assertEqual(previous.values['state'], 'disabled')
                self.assertEqual(following.values['state'], 'disabled')
                self.assertEqual(tuple(app.guess_list.rows), before)

    def test_actual_workspace_refresh_restores_page_bounds_after_shared_busy_controls(self):
        from test_v148_ui_profiles_batch04 import studio_state_renderer
        app, scope = studio_state_renderer()
        app.guess_words = WORDS
        app.guess_pattern = Value('')
        app.guess_length = Value('7')
        app.guess_result = Value('')
        app.guess_list = Listbox()
        pager = results_for(app)
        previous, following = Button(), Button()
        pager.set_navigation(previous, following)
        DrawBot.DrawBotApp.update_guesses(app)
        pager.next(); pager.next()
        # set_busy restores every registered control's normal state before the
        # shared workspace renderer reapplies each control's specific bounds.
        previous.configure(state='normal'); following.configure(state='normal')
        scope['_apply_ui_state']()
        self.assertEqual(previous.values['state'], 'normal')
        self.assertEqual(following.values['state'], 'disabled')
        app.activity = 'draw'
        scope['_apply_ui_state']()
        self.assertEqual(previous.values['state'], 'disabled')
        self.assertEqual(following.values['state'], 'disabled')


@unittest.skipUnless(sys.platform == 'win32', 'Actual Windows Tk word-result navigation')
class WindowsWordResultsTests(unittest.TestCase):
    def test_actual_filter_native_list_and_keyboard_buttons_reach_later_words(self):
        root = ctk.CTk()
        self.addCleanup(root.destroy)
        root.geometry('500x350')
        errors = []
        root.report_callback_exception = lambda *args: errors.append(args)
        app = SimpleNamespace(guess_words=WORDS, guess_pattern=tk.StringVar(root, value=''),
            guess_length=tk.StringVar(root, value='7'), guess_result=tk.StringVar(root),
            guess_list=tk.Listbox(root, height=5, exportselection=False), activity=None, closing=False)
        app.guess_list.pack(fill='x', padx=10, pady=10)
        tk.Label(root, textvariable=app.guess_result).pack()
        previous = StudioUI.button(root, 'Previous', lambda: None)
        following = StudioUI.button(root, 'Next', lambda: None)
        previous.pack(); following.pack()
        pager = results_for(app)
        pager.set_navigation(previous, following)
        DrawBot.DrawBotApp.update_guesses(app)
        root.update()
        following.focus_force(); root.update()
        following.event_generate('<KeyPress-Return>', when='now')
        following.event_generate('<KeyRelease-Return>', when='now')
        root.update()
        self.assertEqual(app.guess_list.get(0, 'end'), WORDS[200:400])
        self.assertEqual(app.guess_list.curselection(), (0,))
        self.assertIn('Showing 201–400 of 451', app.guess_result.get())
        following.invoke(); root.update()
        self.assertEqual(app.guess_list.get(0, 'end'), WORDS[400:])
        self.assertEqual(following.cget('state'), 'disabled')
        previous.focus_force(); root.update()
        previous.event_generate('<KeyPress-space>', when='now')
        previous.event_generate('<KeyRelease-space>', when='now')
        root.update()
        self.assertEqual(app.guess_list.get(0, 'end'), WORDS[200:400])
        self.assertFalse(errors, errors)


if __name__ == '__main__':
    unittest.main()
