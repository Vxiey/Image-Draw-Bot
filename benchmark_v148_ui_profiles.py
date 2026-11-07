"""Paired sidebar text-lookup benchmark; never creates a GUI or sends input.

This isolates the tree-search algorithm on supported fake Tk widgets. It does
not measure application startup or the independent CTk unsupported-text fix.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import statistics
import subprocess
import time
import tkinter as tk
import tracemalloc
from types import ModuleType

import UICompactLayout as current

BASELINE='1d48eabaf349a5fd8049a2c96ef5426745c3078c'


class Node:
    def __init__(self,parent=None,text=None):
        self.master=parent;self.text=text;self.children=[]
        self.text_reads=0;self.children_reads=0
        if parent is not None:parent.children.append(self)
    def cget(self,key):
        self.text_reads+=1
        if self.text is None:raise tk.TclError('unknown option -text')
        return self.text
    def winfo_children(self):
        self.children_reads+=1
        return tuple(self.children)


def fixture():
    root=Node();nodes=[root]
    for section in range(16):
        parent=Node(root);nodes.append(parent)
        for control in range(60):nodes.append(Node(parent,f'Target control {section:02d}/{control:02d}'))
    queries=[f'Target control {section:02d}/{control:02d}' for section in range(16) for control in (5,35,59)]
    queries.append('Missing control')
    return root,nodes,queries


def operation(module,root,queries,*,indexed):
    lookup=module._WidgetLookup(root) if indexed else None
    found=[lookup.find(root,query) if indexed else module._find_text(root,query) for query in queries]
    return [widget.text if widget is not None else None for widget in found]


def sample(module,*,indexed,memory=False):
    root,nodes,queries=fixture()
    if memory:tracemalloc.start()
    start=time.perf_counter()
    result=operation(module,root,queries,indexed=indexed)
    elapsed=time.perf_counter()-start
    peak=tracemalloc.get_traced_memory()[1] if memory else None
    if memory:tracemalloc.stop()
    expected=[*queries[:-1],None]
    if result!=expected:raise AssertionError('Lookup results changed.')
    digest=hashlib.sha256(json.dumps(result,ensure_ascii=False).encode('utf-8')).hexdigest()
    return {'seconds':elapsed,'peak_python_bytes':peak,
            'text_reads':sum(node.text_reads for node in nodes),
            'children_reads':sum(node.children_reads for node in nodes),
            'result_sha256':digest}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',default=BASELINE)
    parser.add_argument('--samples',type=int,default=7)
    parser.add_argument('--output',type=Path,default=Path('docs/v148-batch04-ui-profiles-benchmarks.json'))
    args=parser.parse_args()
    if not 3<=args.samples<=100:parser.error('--samples must be between 3 and 100')
    source=subprocess.run(['git','show',f'{args.baseline}:UICompactLayout.py'],check=True,capture_output=True,text=True).stdout
    baseline=ModuleType('baseline_compact_layout');exec(compile(source,'baseline/UICompactLayout.py','exec'),baseline.__dict__)
    sample(baseline,indexed=False);sample(current,indexed=True)
    before=[];after=[]
    for iteration in range(args.samples):
        order=((baseline,False,before),(current,True,after))
        if iteration%2:order=tuple(reversed(order))
        for module,indexed,rows in order:rows.append(sample(module,indexed=indexed))
    report={'baseline_commit':args.baseline,'python':platform.python_version(),'platform':platform.platform(),
        'workload':{'widgets':977,'queries':49,'description':'Preorder label lookup with one missing target; deterministic supported Tk widget fakes.'},
        'scope':'Algorithm/accessor calls only; no application startup, native Tk latency, Windows input or GPU measurements.',
        'baseline_source_sha256':hashlib.sha256(source.encode()).hexdigest(),
        'current_source_sha256':hashlib.sha256(Path(current.__file__).read_bytes()).hexdigest(),
        'before':before,'after':after,
        'before_memory':sample(baseline,indexed=False,memory=True),
        'after_memory':sample(current,indexed=True,memory=True),
        'before_median_seconds':statistics.median(row['seconds'] for row in before),
        'after_median_seconds':statistics.median(row['seconds'] for row in after)}
    if len({row['result_sha256'] for row in before+after})!=1:raise AssertionError('Before/after results differ.')
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:report[key] for key in ('before_median_seconds','after_median_seconds','before_memory','after_memory')},indent=2))


if __name__=='__main__':main()
