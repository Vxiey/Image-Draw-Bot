"""Input-free tests for wheel routing, cancellation and trusted Paint paths."""
import math
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from SmoothScroll import ScrollAccumulator,install_scrolling
from UiTransactionRuntime import AdaptivePacer,UiTransaction
import PaintPreparation as paint


class UiMaintenanceTests(unittest.TestCase):
    def scrolling(self,widget,system='win32'):
        callbacks=[];bindings={}
        root=SimpleNamespace(tk=SimpleNamespace(call=lambda *args:system),
                             winfo_containing=lambda *args:widget,
                             after=lambda ms,fn:callbacks.append(fn) or len(callbacks),
                             bind_all=lambda key,fn:bindings.update({key:fn}))
        install_scrolling(root)
        return bindings['<MouseWheel>'],callbacks

    def event(self,delta=-120,state=0):
        return SimpleNamespace(state=state,x_root=1,y_root=2,delta=delta,num=None)

    def test_bad_wheel_values_do_not_poison_fractional_scroll(self):
        accumulator=ScrollAccumulator();accumulator.add(.5)
        for bad in (math.nan,math.inf,-math.inf,None,'bad'):
            self.assertFalse(accumulator.add(bad))
        accumulator.add(.5)
        self.assertEqual(accumulator.take(),1)

    def test_wheel_at_inner_boundary_scrolls_outer_panel(self):
        inner=Mock();inner.yview.return_value=(.5,1)
        outer=Mock();outer.yview.return_value=(0,.5)
        parent=SimpleNamespace(_parent_canvas=outer,winfo_class=lambda:'Frame',master=None)
        child=SimpleNamespace(_parent_canvas=inner,winfo_class=lambda:'Frame',master=parent)
        wheel,callbacks=self.scrolling(child)
        self.assertEqual(wheel(self.event()),'break');callbacks[0]()
        inner.yview_scroll.assert_not_called()
        outer.yview_scroll.assert_called_once_with(1,'units')

    def test_native_controls_and_horizontal_scroll_keep_their_binding(self):
        for native in ('Treeview','TCombobox','Spinbox','TScale'):
            with self.subTest(native=native):
                widget=SimpleNamespace(_parent_canvas=Mock(),winfo_class=lambda:native)
                wheel,callbacks=self.scrolling(widget)
                self.assertIsNone(wheel(self.event()));self.assertEqual(callbacks,[])
        wheel,callbacks=self.scrolling(SimpleNamespace(winfo_class=lambda:'Frame'))
        self.assertIsNone(wheel(self.event(state=1)));self.assertEqual(callbacks,[])

    def test_macos_native_wheel_units_are_not_divided_by_120(self):
        canvas=Mock();canvas.yview.return_value=(0,.5)
        widget=SimpleNamespace(_parent_canvas=canvas,winfo_class=lambda:'Frame')
        wheel,callbacks=self.scrolling(widget,'aqua')
        self.assertEqual(wheel(self.event(delta=-1)),'break');callbacks[0]()
        canvas.yview_scroll.assert_called_once_with(1,'units')

    def test_cancellation_prevents_recovery_input_after_failure(self):
        stopped=[False];recover=Mock();wait=Mock()
        transaction=UiTransaction(cancelled=lambda:stopped[0],wait=wait)

        def operation(attempt):
            stopped[0]=True
            raise TimeoutError('UI busy')

        with self.assertRaises(InterruptedError):transaction.retry(operation,recover=recover)
        recover.assert_not_called();wait.assert_not_called()

    def test_interruption_is_never_retried_even_with_broad_retry_tuple(self):
        operation=Mock(side_effect=InterruptedError('stopped'))
        transaction=UiTransaction(wait=lambda delay:None)
        with self.assertRaises(InterruptedError):transaction.retry(operation,retry_on=(Exception,))
        operation.assert_called_once_with(1)

    def test_cancellation_during_success_does_not_continue_transaction(self):
        stopped=[False];transaction=UiTransaction(cancelled=lambda:stopped[0])
        def operation(attempt):stopped[0]=True;return 'done'
        with self.assertRaises(InterruptedError):transaction.retry(operation)

    def test_nonfinite_pacing_cannot_create_unbounded_sleep(self):
        for field in ('base_delay','max_delay','growth','decay'):
            for bad in (math.inf,-math.inf,math.nan,'bad'):
                with self.subTest(field=field,bad=bad):
                    with self.assertRaisesRegex(ValueError,'finite'):AdaptivePacer(**{field:bad})

    def test_paint_executables_ignore_environment_directory_override(self):
        process=Mock(returncode=0)
        process.communicate.return_value=(b'[]',b'')
        process.poll.return_value=0
        safe=Path('/trusted/System32')
        with patch.dict('os.environ',{'SystemRoot':'/untrusted','WINDIR':'/untrusted'}), \
             patch.object(paint,'system_directory',return_value=safe), \
             patch.object(paint.subprocess,'Popen',return_value=process) as launch:
            paint._run_powershell('ConvertTo-Json -InputObject @()')
            self.assertEqual(launch.call_args.args[0][0],str(safe/'WindowsPowerShell'/'v1.0'/'powershell.exe'))
            with patch('PaintFullCalibration.choose_paint_window',return_value='ready'):
                self.assertEqual(paint.ensure_paint(Mock(side_effect=[[],[{'title':'Paint'}]]),wait=lambda delay:None),'ready')
            self.assertEqual(launch.call_args.args[0],[str(safe/'mspaint.exe')])


if __name__=='__main__':unittest.main()
