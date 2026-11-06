"""Paint preparation via Windows UI Automation; no canvas input or document clearing."""
from __future__ import annotations
import json
import os
import re
import subprocess
import tempfile
import time
from WindowsSystem import system_directory

# Kept inline so frozen builds need no PowerShell resource or Python COM package.
_SCRIPT = r'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$root=[System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]HANDLE)
$process=Get-Process -Id $root.Current.ProcessId
if ($process.ProcessName -notmatch '^(mspaint|PaintApp|Paint)$') { throw 'Target is not Microsoft Paint.' }
$all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$rows=@()
for($i=0;$i -lt $all.Count;$i++) {
 $e=$all.Item($i); $c=$e.Current; $b=$c.BoundingRectangle
 if($c.IsOffscreen -or !$c.IsEnabled -or $b.Width -le 0 -or $b.Height -le 0){continue}
 $label=''; if($c.LabeledBy){$label=$c.LabeledBy.Current.Name}
 $v=''; if($c.ControlType -eq [System.Windows.Automation.ControlType]::Edit) {try{$v=$e.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).Current.Value}catch{}}
 $rows+=@{id=$i;name=$c.Name;label=$label;kind=$c.ControlType.ProgrammaticName;rect=@($b.Left,$b.Top,$b.Right,$b.Bottom);value=$v}
}
ACTION
ConvertTo-Json -InputObject @($rows) -Depth 5 -Compress
'''


# A provider may keep Invoke blocked until a modal dialog closes. The caller must
# scan/verify the resulting UI state; a pending invocation is not proof of success.
_INVOKE_HELPER = r'''
Add-Type -AssemblyName WindowsBase
Add-Type -ReferencedAssemblies @([System.Windows.Automation.InvokePattern].Assembly.Location,[System.Windows.Automation.AutomationElementIdentifiers].Assembly.Location,[System.Windows.Rect].Assembly.Location) -TypeDefinition @"
using System;
using System.Threading;
using System.Windows.Automation;
public static class PaintModalAction {
    public static bool Run(Action action, int waitMs) {
        Exception failure = null;
        Thread worker = new Thread(() => { try { action(); } catch (Exception e) { failure = e; } });
        worker.IsBackground = true;
        worker.SetApartmentState(ApartmentState.MTA);
        worker.Start();
        bool finished = worker.Join(waitMs);
        if (finished && failure != null) throw new InvalidOperationException("Paint action failed", failure);
        return finished;
    }
    public static void Invoke(InvokePattern pattern) { Run(() => pattern.Invoke(), 750); }
    public static void Legacy(object pattern) { Run(() => pattern.GetType().GetMethod("DoDefaultAction").Invoke(pattern, null), 750); }
}
"@
'''

_INVOKE_ACTION = r'''
$activated=$false
$pattern=$null
if($e.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern,[ref]$pattern)) {
    [PaintModalAction]::Invoke([System.Windows.Automation.InvokePattern]$pattern); $activated=$true
}
if(!$activated) {
    $pattern=$null
    if($e.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern,[ref]$pattern)) {
        ([System.Windows.Automation.SelectionItemPattern]$pattern).Select(); $activated=$true
    }
}
if(!$activated) {
    $pattern=$null
    if($e.TryGetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern,[ref]$pattern)) {
        ([System.Windows.Automation.TogglePattern]$pattern).Toggle(); $activated=$true
    }
}
if(!$activated) {
    $pattern=$null
    if($e.TryGetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern,[ref]$pattern)) {
        $expand=[System.Windows.Automation.ExpandCollapsePattern]$pattern
        if($expand.Current.ExpandCollapseState -ne [System.Windows.Automation.ExpandCollapseState]::Expanded) {$expand.Expand()}
        $activated=$true
    }
}
if(!$activated) {
    $pattern=$null
    # .NET Framework UIAutomationClient does not expose this native pattern on
    # all Windows installations. Skip unavailable wrappers instead of throwing.
    $legacyType='System.Windows.Automation.LegacyIAccessiblePattern' -as [type]
    if($legacyType) {
        $legacyField=$legacyType.GetField('Pattern')
        if($legacyField -and $e.TryGetCurrentPattern($legacyField.GetValue($null),[ref]$pattern)) {
            [PaintModalAction]::Legacy($pattern); $activated=$true
        }
    }
}
if(!$activated) {
    # Modern Paint/XAML controls sometimes expose a valid named Button without
    # InvokePattern or SelectionItemPattern. Focus + Enter is a bounded fallback
    # on that already re-resolved UI element; it never guesses a canvas position.
    try {
        $e.SetFocus()
        Start-Sleep -Milliseconds 60
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
        $activated=$true
    } catch {}
}
if(!$activated){throw 'Paint control could not be activated with supported UI Automation patterns or focused Enter.'}
'''

_CUSTOM_COLOR_NAMES = (
    'edit colors','edit colours','edit color','edit colour',
    'custom color','custom colour','more colors','more colours',
    'redigera färger','anpassad färg','fler färger',
)


def _powershell_json_literal(value):
    """Keep control names as data, including quotes and localized Unicode text."""
    payload=json.dumps(value,ensure_ascii=True)
    return "'"+payload.replace("'","''")+"'"


def _automation_script(handle, *, element=None, action=None, size_px=1):
    command=''
    if element is not None:
        # Re-resolve by identity and rectangle; never trust an old tree index.
        command=f"$wanted=ConvertFrom-Json -InputObject {_powershell_json_literal(element)}\n"
        command+=r'''
$matches=@($rows | Where-Object { $_.name -eq $wanted.name -and $_.kind -eq $wanted.kind -and (($_.rect -join ',') -eq ($wanted.rect -join ',')) })
if($matches.Count -ne 1){throw 'Paint controls moved or are ambiguous. Retry preparation.'}
$e=$all.Item([int]$matches[0].id)
'''
        if action=='invoke':
            command+=_INVOKE_HELPER+_INVOKE_ACTION
        elif action=='size':
            target_size=max(1,min(50,int(size_px or 1)))
            command+=f'$targetSize={target_size}\n'+r'''
$pattern=$null
if(!$e.TryGetCurrentPattern([System.Windows.Automation.RangeValuePattern]::Pattern,[ref]$pattern)) {throw 'Paint size control does not expose RangeValuePattern.'}
$p=[System.Windows.Automation.RangeValuePattern]$pattern
if($p.Current.Minimum -gt $targetSize -or $p.Current.Maximum -lt $targetSize){throw ('Paint size does not expose the requested '+$targetSize+' px value.')}
$p.SetValue($targetSize)
if([Math]::Abs($p.Current.Value-$targetSize) -gt 0.001){throw ('Paint did not accept '+$targetSize+' px.')}
'''
        else:raise ValueError('Unsupported Paint control action.')
    return _SCRIPT.replace('HANDLE',str(int(handle))).replace('ACTION',command)


def _run_powershell(script, *, action=None, cancelled=lambda:False):
    """Run our readable inline script with the same bounded UIA subprocess."""
    if cancelled():raise InterruptedError('Paint preparation cancelled.')
    # -Command - parses stdin one statement at a time. A single block keeps the
    # UIA scan/action together, including the multiline C# helper. The final blank
    # line completes that block. JSON's ASCII escapes avoid console-codepage loss.
    source=("& {\n$ErrorActionPreference='Stop'\n"
            "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)\n"
            "try {\n"+script+"\n} catch {\n"
            "[Console]::Error.WriteLine($_.ToString())\nexit 1\n}\n}\n\n")
    source=source.encode('ascii')
    executable=str(system_directory()/'WindowsPowerShell'/'v1.0'/'powershell.exe')
    # A regular input file avoids communicate(input=...) blocking synchronously
    # on Windows when a child stops reading its stdin pipe. No script is added to
    # the command line, downloaded, or kept after this operation finishes.
    with tempfile.TemporaryFile() as script_input:
        script_input.write(source)
        script_input.seek(0)
        process=subprocess.Popen([executable,'-NoProfile','-NonInteractive','-Command','-'],stdin=script_input,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        deadline=time.monotonic()+12
        try:
            while True:
                if cancelled():raise InterruptedError('Paint preparation cancelled.')
                if time.monotonic()>deadline:raise TimeoutError('Paint controls did not respond during '+(action or 'control scan')+'. Keep Paint visible; if Edit colors is open, leave it in RGB mode and retry calibration.')
                try:out,err=process.communicate(timeout=.1);break
                except subprocess.TimeoutExpired:pass
            if process.returncode:raise ValueError(err.decode('utf-8',errors='replace').strip()[-1200:])
            return out
        finally:
            if process.poll() is None:process.kill();process.communicate()


def automation(handle, *, element=None, action=None, size_px=1, cancelled=lambda:False):
    if os.name!='nt':raise OSError('Automatic Paint preparation requires Windows.')
    if cancelled():raise InterruptedError('Paint preparation cancelled.')
    script=_automation_script(handle,element=element,action=action,size_px=size_px)
    out=_run_powershell(script,action=action,cancelled=cancelled)
    data=json.loads(out.decode('utf-8-sig'))
    return data if isinstance(data,list) else [data]


def _normalized_name(node):
    text=str(node.get('label') or node.get('name') or '').strip().casefold()
    return re.sub(r'\s*\([^)]*\)\s*$','',text).rstrip(':').strip()


def find_control(nodes, names, *, kind=None):
    names=tuple(str(name).casefold() for name in names)
    def matches(n):
        return _normalized_name(n) in names and (kind is None or str(n.get('kind','')).endswith(kind))
    hits=[n for n in nodes if matches(n)]
    if len(hits)!=1:raise ValueError('Paint control not uniquely identified: '+', '.join(names))
    return hits[0]


def find_custom_color_opener(nodes):
    """Find Paint's Edit colors control across classic and current XAML variants."""
    names=set(_CUSTOM_COLOR_NAMES)
    hits=[]
    for node in nodes:
        kind=str(node.get('kind',''))
        if _normalized_name(node) in names and any(kind.endswith(suffix) for suffix in ('Button','MenuItem','Custom')):
            hits.append(node)
    if len(hits)!=1:
        raise ValueError('Paint Edit colors / custom color control was not uniquely identified.')
    return hits[0]


def center(node):
    l,t,r,b=node['rect']
    return round((l+r)/2),round((t+b)/2)


def rgb_controls(nodes):
    result={}
    for key,names in (('RedField',('red','röd')),('GreenField',('green','grön')),('BlueField',('blue','blå'))):
        try:field=find_control(nodes,names,kind='Edit')
        except ValueError:
            label=find_control(nodes,names,kind='Text')
            lx,ly=center(label)
            # Paint puts labels beside numeric edits. Associate the same row,
            # accepting only one nearby field instead of guessing field order.
            hits=[n for n in nodes if str(n.get('kind','')).endswith('Edit')
                  and abs(center(n)[1]-ly)<(n['rect'][3]-n['rect'][1])*.5
                  and 0<=label['rect'][0]-n['rect'][2]<=max(80,n['rect'][2]-n['rect'][0])]
            if len(hits)!=1:raise ValueError('Could not identify Paint '+key+'. Open Edit colors in RGB mode.')
            field=hits[0]
        if not str(field.get('value','')).isdigit() or not 0<=int(field['value'])<=255:
            raise ValueError('Paint RGB field did not expose a valid numeric value.')
        result[key]=center(field)
    if len(set(result.values()))!=3:raise ValueError('Paint RGB fields overlap.')
    result['ConfirmColor']=center(find_control(nodes,('ok',),kind='Button'))
    return result


def find_add_custom_color(nodes):
    """Resolve Paint's save-to-custom-palette button, never the dialog's OK."""
    controls=rgb_controls(nodes)
    names=('add to custom colors','add to custom colours','add custom color',
           'add custom colour','add color','add colour',
           'lägg till i anpassade färger','lägg till anpassad färg',
           'lägg till färg','lägg till i egna färger')
    hits=[n for n in nodes if str(n.get('kind','')).endswith('Button')
          and _normalized_name(n) in names]
    if len(hits)==1:return hits[0]
    if len(hits)>1:raise ValueError('Paint Add custom color button is ambiguous.')
    # Some XAML versions expose only the + glyph. Restrict it to the custom
    # palette area below the RGB fields and above the dialog confirmation row.
    red_x,_=controls['RedField'];_,blue_y=controls['BlueField']
    _,ok_y=controls['ConfirmColor']
    hits=[n for n in nodes if str(n.get('kind','')).endswith('Button')
          and _normalized_name(n) in ('+','plus','add','lägg till')
          and center(n)[0]>=red_x and blue_y<center(n)[1]<ok_y]
    if len(hits)!=1:
        raise ValueError('Paint + / Add to custom colors could not be identified. No picture colors were saved.')
    return hits[0]


def edit_colors_dialog_open(nodes):
    """Return True only when Paint's numeric Edit colors dialog is still exposed."""
    try:
        rgb_controls(nodes)
    except ValueError:
        return False
    return True


def close_edit_colors(handle, *, accept=False, cancelled=lambda:False, backend=automation,
                      wait=time.sleep, max_attempts=3):
    """Close Edit colors and prove it disappeared before canvas work continues.

    Paint's current XAML dialog can return from InvokePattern before the modal is
    actually removed from the UI tree.  The old preparation flow immediately took
    a canvas screenshot after invoking Cancel, so its own Edit colors dialog could
    cover the canvas and trigger a false covered/ambiguous-canvas stop.  This helper
    retries only the already identified OK/Cancel button and requires the RGB fields
    to disappear; it never clicks or guesses a canvas coordinate.
    """
    names=('ok',) if accept else ('cancel','avbryt')
    attempts=max(1,min(5,int(max_attempts)))
    last_nodes=None
    for _ in range(attempts):
        if cancelled():raise InterruptedError('Paint preparation cancelled.')
        nodes=backend(handle,cancelled=cancelled);last_nodes=nodes
        if not edit_colors_dialog_open(nodes):
            wait(.12)
            if cancelled():raise InterruptedError('Paint preparation cancelled.')
            verify=backend(handle,cancelled=cancelled)
            if not edit_colors_dialog_open(verify):return True
            last_nodes=verify
        try:button=find_control(last_nodes,names,kind='Button')
        except ValueError:
            wait(.08);continue
        backend(handle,element=button,action='invoke',cancelled=cancelled)
        wait(.12)
    if cancelled():raise InterruptedError('Paint preparation cancelled.')
    nodes=backend(handle,cancelled=cancelled)
    if not edit_colors_dialog_open(nodes):
        wait(.12);return True
    action='OK' if accept else 'Cancel'
    raise ValueError(f'Paint Edit colors did not close after {action}. Close the dialog and retry; no canvas input was sent.')


def ensure_paint(enumerate_windows, *, cancelled=lambda:False, launch=None, wait=None):
    from PaintFullCalibration import choose_paint_window
    from threading import Event
    wait=wait or Event().wait
    def candidates():return [n for n in enumerate_windows() if re.search(r'(?:^|[–—-]\s*)Paint\s*$',str(n.get('title','')),re.I)]
    if cancelled():raise InterruptedError()
    found=candidates()
    if found:return choose_paint_window(found)
    if launch is None:
        launch=lambda:subprocess.Popen([str(system_directory()/'mspaint.exe')])
    launch()
    for _ in range(40):
        if cancelled():raise InterruptedError('Paint preparation cancelled.')
        found=candidates()
        if found:return choose_paint_window(found)
        wait(.2)
    raise ValueError('Paint did not open in time. Open it and retry.')


def prepare_tool_controls(handle, *, brush_px=1, cancelled=lambda:False, backend=automation):
    """Prepare Pencil and the requested verified pixel size without opening Paint Edit colors.

    This is the required path for black contour sketch, Single-color sketch
    (current ink), and Eraser workflows.  It may close an already-open stale
    Edit colors modal, but it never activates the custom-color opener.
    """
    def scan():return backend(handle,cancelled=cancelled)
    def invoke(node):return backend(handle,element=node,action='invoke',cancelled=cancelled)
    nodes=scan()
    if edit_colors_dialog_open(nodes):
        close_edit_colors(handle,cancelled=cancelled,backend=backend)
        nodes=scan()
    pencil=find_control(nodes,('pencil','penna','blyertspenna'),kind='Button')
    invoke(pencil)
    nodes=scan()
    size=find_control(nodes,('size','brush size','pencil size','storlek','penselstorlek','pennstorlek','thickness','tjocklek'),kind='Slider')
    backend(handle,element=size,action='size',size_px=max(1,min(50,int(brush_px or 1))),cancelled=cancelled)
    return True


def calibrate_rgb_controls(handle, *, cancelled=lambda:False, backend=automation):
    """Open Edit colors only to learn numeric RGB controls, then close it."""
    def scan():return backend(handle,cancelled=cancelled)
    def invoke(node):return backend(handle,element=node,action='invoke',cancelled=cancelled)
    nodes=scan()
    if edit_colors_dialog_open(nodes):
        # A previous provider timeout may have opened the dialog successfully.
        # Capture it, close it, and resolve the opener from the enabled toolbar.
        controls=rgb_controls(nodes)
        close_edit_colors(handle,cancelled=cancelled,backend=backend)
        opener=find_custom_color_opener(scan())
        controls['OpenCustomColor']=center(opener)
        return controls
    opener=find_custom_color_opener(nodes)
    invoke(opener)
    deadline=time.monotonic()+5
    while True:
        if cancelled():raise InterruptedError('Paint preparation cancelled.')
        nodes=scan()
        try:
            controls=rgb_controls(nodes)
            break
        except ValueError:
            if time.monotonic()>deadline:raise ValueError('Paint Edit colors opened, but numeric RGB controls could not be calibrated. Keep the dialog in RGB mode and retry.')
            time.sleep(.12)
    close_edit_colors(handle,cancelled=cancelled,backend=backend)
    controls['OpenCustomColor']=center(opener)
    return controls


def prepare_controls(handle, *, brush_px=1, cancelled=lambda:False, backend=automation):
    """Backward-compatible full Paint tool + exact-RGB preparation."""
    prepare_tool_controls(handle,brush_px=brush_px,cancelled=cancelled,backend=backend)
    return calibrate_rgb_controls(handle,cancelled=cancelled,backend=backend)
