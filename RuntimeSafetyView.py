"""Private ownership of one controller's current runtime safety presentation.

Workers publish detached evidence. Only the UI thread advances this view; Stop
does not revoke a stopped run's evidence, while replacement/clear does.
"""
from copy import deepcopy
from dataclasses import dataclass

from RuntimeSafetyReport import _valid_report, compact_summary


@dataclass(frozen=True, eq=False)
class RuntimeSafetyRequest:
    label: str


@dataclass(frozen=True)
class RuntimeSafetyResult:
    request: RuntimeSafetyRequest
    payload: dict | None
    error: str = ''


def capture_runtime_report(request, options):
    """Capture final executor evidence without retaining its plan or images."""
    try:
        payload = options.get('runtime_safety_report')
        return RuntimeSafetyResult(request, deepcopy(payload) if isinstance(payload, dict) else None)
    except Exception as error:
        return RuntimeSafetyResult(request, None, f'Report capture failed: {type(error).__name__}.')


class RuntimeSafetyView:
    def __init__(self):
        self.local = False
        self.request = None
        self.payload = None
        self.finished = False
        self.error = ''

    def begin(self, label):
        self.local = True
        self.request = RuntimeSafetyRequest(str(label))
        self.payload = None
        self.finished = False
        self.error = ''
        return self.request

    def clear(self):
        self.local = True
        self.request = None
        self.payload = None
        self.finished = True
        self.error = ''

    def finish(self, request):
        if request is not None and request is self.request:
            self.finished = True

    def accept(self, result):
        if not isinstance(result, RuntimeSafetyResult) or result.request is not self.request:
            return False
        if self.request is None:
            return False
        try:
            self.payload = deepcopy(result.payload)
            self.error = result.error
        except Exception as error:
            self.payload = None
            self.error = f'Report capture failed: {type(error).__name__}.'
        self.finished = True
        return True

    def current_or_history(self, loader):
        return self.payload if self.local else loader()

    def presentation(self, payload, *, stopped=False):
        if self.local and not _valid_report(payload):
            if self.request is None:
                return ('No current runtime safety report.',
                        'Cached drawing cleared. A new execution will provide new safety results.')
            if stopped:
                summary = f'STOPPED · {self.request.label} · no runtime report available'
            elif not self.finished:
                summary = f'Runtime safety pending · {self.request.label}'
            else:
                summary = f'Runtime safety report unavailable · {self.request.label}'
            detail = self.error or ('Current attempt is still running.' if not self.finished and not stopped
                                    else 'This attempt did not produce a current runtime safety report.')
            return summary, detail
        summary = compact_summary(payload)
        if not payload:
            return summary, 'Local-only safety reports are saved after each execution.'
        stop = (payload.get('stop') or {}).get('reason') or ''
        when = str(payload.get('finished_utc') or payload.get('started_utc') or '')
        prefix = 'Current run' if self.local else 'Latest saved report'
        detail = f"{prefix}: {when} · Profile: {payload.get('profile', '')}"
        if stop:
            detail += f' · Stop: {str(stop)[:90]}'
        if payload.get('save_error'):
            detail += f" · Report not saved: {str(payload['save_error'])[:180]}"
        return summary, detail
