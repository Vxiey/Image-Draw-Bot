"""Bounded pages for the deterministic word helper's complete result set."""
from __future__ import annotations

import tkinter as tk


PAGE_SIZE = 200


class WordResults:
    """Keep every match reachable while inserting at most one page into Tk."""

    def __init__(self, app):
        self.app = app
        self.listbox = app.guess_list
        self.matches = ()
        self.page = 0
        self.previous_button = None
        self.next_button = None

    @property
    def page_count(self):
        return (len(self.matches) + PAGE_SIZE - 1) // PAGE_SIZE

    def _available(self):
        try:
            return not getattr(self.app, 'closing', False) and bool(self.listbox.winfo_exists())
        except (tk.TclError, RuntimeError):
            return False

    def set_navigation(self, previous, following):
        self.previous_button = previous
        self.next_button = following
        previous.configure(command=self.previous)
        following.configure(command=self.next)
        self.refresh_controls()

    def refresh_controls(self):
        enabled = self._available() and not getattr(self.app, 'activity', None)
        for button, allowed in ((self.previous_button, self.page > 0),
                                (self.next_button, self.page + 1 < self.page_count)):
            if button is not None:
                try:
                    button.configure(state='normal' if enabled and allowed else 'disabled')
                except (tk.TclError, RuntimeError):
                    pass

    def set_matches(self, matches):
        if not self._available():
            return False
        self.matches = tuple(matches)
        self.page = 0
        return self._render()

    def set_error(self, message):
        if not self._available():
            return False
        self.matches = ()
        self.page = 0
        return self._render(message=str(message))

    def _render(self, *, message=None):
        start = self.page * PAGE_SIZE
        rows = self.matches[start:start + PAGE_SIZE]
        try:
            self.listbox.delete(0, 'end')
            if rows:
                # One Tcl call, independent of the page's number of words.
                self.listbox.insert('end', *rows)
                self.listbox.selection_set(0)
                self.listbox.activate(0)
                self.listbox.see(0)
            if message is None:
                count = len(self.matches)
                message = (f'Showing {start + 1}–{start + len(rows)} of {count} possible words'
                           f' · Page {self.page + 1} of {self.page_count}. No confidence ranking.'
                           if rows else '0 possible words. No confidence ranking.')
            self.app.guess_result.set(message)
        except (tk.TclError, RuntimeError):
            return False
        self.refresh_controls()
        return True

    def show_page(self, index):
        if not self._available() or getattr(self.app, 'activity', None):
            return False
        index = max(0, min(max(0, self.page_count - 1), index))
        if index == self.page:
            return False
        self.page = index
        return self._render()

    def previous(self):
        return self.show_page(self.page - 1)

    def next(self):
        return self.show_page(self.page + 1)


def results_for(app):
    results = getattr(app, '_word_helper_results', None)
    if results is None or results.listbox is not app.guess_list:
        results = app._word_helper_results = WordResults(app)
    return results
