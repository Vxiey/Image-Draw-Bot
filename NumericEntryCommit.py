"""Local numeric-entry commits without invalidating unchanged drawing settings."""
from tkinter import TclError
from weakref import WeakSet


_MISSING = object()


class NumericEntryCommit:
    def __init__(self, field, variable, callback, owner):
        self.field = field
        self.variable = variable
        self.callback = callback
        self.owner = owner
        self.alive = True
        self.focused = False
        self.committing = False
        self.retry_required = False
        self.trace = None
        self.committed = self._read()
        try:
            self.trace = variable.trace_add('write', self._written)
            field.bind('<FocusIn>', self._focus_in, add='+')
            field.bind('<FocusOut>', self._focus_out, add='+')
            field.bind('<Return>', self._commit, add='+')
            field.bind('<Destroy>', self.dispose, add='+')
            if not hasattr(owner, '_numeric_entry_commits'):
                owner._numeric_entry_commits = WeakSet()
            owner._numeric_entry_commits.add(self)
        except BaseException:
            self.dispose()
            raise

    def _read(self):
        try:
            return self.variable.get()
        except (TclError, RuntimeError):
            return _MISSING

    def acknowledge(self):
        if not self.alive or getattr(self.owner, 'closing', False):
            return
        value = self._read()
        if value is not _MISSING:
            self.committed = value
            self.retry_required = False

    def _written(self, *_args):
        if (not self.focused or getattr(self.owner, 'profile_change_in_progress', False)):
            # Profile application/rollback and unfocused programmatic updates
            # establish a fresh baseline, rather than an outstanding user edit.
            self.acknowledge()

    def _focus_in(self, _event=None):
        if not self.alive or self.focused or getattr(self.owner, 'closing', False):
            return
        if not self.retry_required:
            self.acknowledge()
        self.focused = True

    def _focus_out(self, event=None):
        try:
            return self._commit(event)
        finally:
            self.focused = False

    def _commit(self, event=None):
        if not self.alive or self.committing or getattr(self.owner, 'closing', False):
            return
        value = self._read()
        if value is _MISSING or value == self.committed:
            return
        if (getattr(self.owner, 'activity', None) or
                getattr(self.owner, 'profile_change_in_progress', False)):
            self.retry_required = True
            return
        self.committing = True
        self.retry_required = True
        try:
            result = self.callback(event)
            if result is not False:
                self.acknowledge()
            return result
        finally:
            self.committing = False

    def dispose(self, _event=None):
        if not self.alive:
            return
        self.alive = False
        if self.trace is not None:
            try:
                self.variable.trace_remove('write', self.trace)
            except (TclError, RuntimeError):
                pass
            self.trace = None
        registry = getattr(self.owner, '_numeric_entry_commits', None)
        if registry is not None:
            registry.discard(self)


def bind_numeric_commit(field, variable, callback, *, owner):
    """Keep CTk's native bindings and own only the field's additional handlers."""
    handler = NumericEntryCommit(field, variable, callback, owner)
    field._numeric_entry_commit = handler
    return handler


def sync_numeric_commits(app):
    """Acknowledge displayed values after a successful settings invalidation."""
    for handler in tuple(getattr(app, '_numeric_entry_commits', ())):
        handler.acknowledge()
