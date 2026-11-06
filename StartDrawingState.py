"""Explicit Start Drawing state tracking for Image Draw Bot v1.0.119-beta."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

STATES=("START_ACCEPTED","PREFLIGHT","PLAN_READY","INPUT_ARMED","DRAWING","COMPLETED","ABORTED")
_ALLOWED={
    "START_ACCEPTED":{"PREFLIGHT","ABORTED"},
    "PREFLIGHT":{"PLAN_READY","ABORTED"},
    "PLAN_READY":{"INPUT_ARMED","ABORTED"},
    "INPUT_ARMED":{"DRAWING","ABORTED"},
    "DRAWING":{"COMPLETED","ABORTED"},
    "COMPLETED":set(),"ABORTED":set(),
}

@dataclass
class StartStateSnapshot:
    state:str
    elapsed_in_state:float
    block_reason:str
    total_elapsed:float

class StartDrawingStateMachine:
    def __init__(self, *, clock=time.monotonic, logger:Callable[[str],None]|None=None):
        self.clock=clock;self.logger=logger
        now=float(clock());self.started=now;self.changed=now
        self.state="START_ACCEPTED";self.block_reason="accepted; preparing preflight"
        self.history=[(self.state,now,self.block_reason)]
        self._emit(self.state,self.block_reason)

    def _emit(self,state,reason):
        if self.logger:
            try:self.logger(f"Start state: {state} start_block_reason={reason!r}")
            except Exception:pass  # Diagnostic I/O must not change authorization state.

    def transition(self,state:str,reason:str=""):
        state=str(state)
        if state not in STATES:raise ValueError(f"Unknown start state: {state}")
        if state!=self.state and state not in _ALLOWED.get(self.state,set()):
            raise ValueError(f"Invalid Start Drawing transition {self.state} -> {state}")
        now=float(self.clock())
        changed = state != self.state
        self.state=state
        if changed:self.changed=now
        self.block_reason=str(reason or "")
        if changed:self.history.append((state,now,self.block_reason))
        self._emit(state,self.block_reason)
        return self.snapshot()

    def set_block_reason(self,reason:str):
        self.block_reason=str(reason or "")

    def snapshot(self):
        now=float(self.clock())
        return StartStateSnapshot(self.state,max(0.0,now-self.changed),self.block_reason,max(0.0,now-self.started))

    def stalled(self,threshold_seconds:float=2.0):
        snap=self.snapshot()
        return snap.state not in ("COMPLETED","ABORTED") and snap.elapsed_in_state>=max(.1,float(threshold_seconds))

    def watchdog_text(self,threshold_seconds:float=2.0):
        snap=self.snapshot()
        if snap.state in ("COMPLETED","ABORTED") or snap.elapsed_in_state<max(.1,float(threshold_seconds)):return ""
        reason=snap.block_reason or "waiting for the current stage"
        return f"{snap.state} for {snap.elapsed_in_state:.1f}s: {reason}"
