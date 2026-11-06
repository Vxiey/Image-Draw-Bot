"""Mobile preview ordering, bounded clients and browser reconnect behavior."""
import http.client
import json
import shutil
import socket
import subprocess
import threading
import unittest
from unittest.mock import Mock, patch

from PIL import Image
import MobilePreview as mobile


class MobileMaintenanceTests(unittest.TestCase):
    def server(self):
        result=mobile.MobilePreviewServer()
        self.addCleanup(result.stop)
        return result

    def test_newer_preview_wins_when_an_older_encode_finishes_last(self):
        server=self.server()
        old=Image.new('RGB',(12,10),'red')
        new=Image.new('RGB',(12,10),'blue')
        entered=threading.Event();resume=threading.Event()
        encode=mobile._image_png_bytes

        def slow(value):
            if value is old:
                entered.set()
                if not resume.wait(3):raise TimeoutError('test encode did not resume')
            return encode(value)

        with patch.object(mobile,'_image_png_bytes',side_effect=slow):
            worker=threading.Thread(target=lambda:server.update_images(preview=old))
            worker.start()
            try:
                self.assertTrue(entered.wait(3))
                newest=server.update_images(preview=new)
            finally:
                resume.set();worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(server._images['preview'],encode(new))
        self.assertEqual(server.state().revision,newest)

    def test_identical_frames_do_not_trigger_phone_reload(self):
        server=self.server()
        image=Image.new('RGBA',(10,12),(20,40,80,128))
        first=server.update_images(preview=image)
        self.assertEqual(server.update_images(preview=image.copy()),first)
        self.assertEqual(server.update_images(preview=Image.new('RGB',(10,12),'white')),first+1)

    def test_addresses_are_cached_for_a_session_and_sorted_numerically(self):
        probe=Mock()
        probe.getsockname.return_value=('8.8.8.8',1234)
        values=['192.168.1.10','8.8.8.8','192.168.1.2','bad','::1','169.254.1.2','192.168.1.2']
        with patch.object(mobile.socket,'gethostbyname_ex',return_value=('host',[],values)), \
             patch.object(mobile.socket,'socket',return_value=probe):
            self.assertEqual(mobile.local_ipv4_addresses(),['192.168.1.2','192.168.1.10','169.254.1.2'])
        server=self.server()
        with patch.object(mobile,'local_ipv4_addresses',return_value=['192.168.1.2']) as discover:
            state=server.start()
            for _ in range(5):
                self.assertEqual(server.state(),state)
                self.assertEqual(server.urls(),list(state.urls))
            discover.assert_called_once_with()

    def test_reopening_panel_can_refresh_changed_network_without_restarting_session(self):
        server=self.server()
        with patch.object(mobile,'local_ipv4_addresses',side_effect=[['192.168.1.2'],['192.168.2.4']]):
            first=server.start()
            second=server.refresh_addresses()
        self.assertEqual((first.token,first.port),(second.token,second.port))
        self.assertEqual(second.urls,(f'http://192.168.2.4:{first.port}/{first.token}/',))

    def test_discovery_never_blocks_stop_or_revives_a_cancelled_start(self):
        server=self.server();entered=threading.Event();resume=threading.Event();failures=[]

        def discover():
            entered.set()
            if not resume.wait(3):raise TimeoutError('test discovery did not resume')
            return ['192.168.1.2']

        def start():
            try:server.start()
            except Exception as error:failures.append(error)

        with patch.object(mobile,'local_ipv4_addresses',side_effect=discover):
            worker=threading.Thread(target=start);worker.start()
            try:
                self.assertTrue(entered.wait(3))
                self.assertFalse(server.state().running)
                server.stop()
            finally:
                resume.set();worker.join(3)
        self.assertFalse(server.running)
        self.assertEqual(len(failures),1)
        self.assertIsInstance(failures[0],InterruptedError)

    def test_failed_server_thread_start_releases_socket_and_session(self):
        server=self.server();instances=[];constructor=mobile._PreviewHTTPServer

        def make(*args,**kwargs):
            result=constructor(*args,**kwargs);instances.append(result);return result

        with patch.object(mobile,'_PreviewHTTPServer',side_effect=make), \
             patch.object(mobile.threading.Thread,'start',side_effect=RuntimeError('thread unavailable')):
            with self.assertRaisesRegex(RuntimeError,'thread unavailable'):server.start()
        self.assertFalse(server.running)
        self.assertEqual(server.port,0)
        self.assertEqual(server.token,'')
        self.assertEqual(instances[0].socket.fileno(),-1)

    def test_idle_client_expires_and_server_remains_usable(self):
        server=self.server()
        with patch.object(mobile,'MOBILE_PREVIEW_CLIENT_TIMEOUT',.1):
            state=server.start()
            with socket.create_connection(('127.0.0.1',state.port),timeout=3) as connection:
                self.assertEqual(connection.recv(1),b'')
            client=http.client.HTTPConnection('127.0.0.1',state.port,timeout=3)
            try:
                client.request('GET',f'/{state.token}/status.json')
                response=client.getresponse()
                self.assertEqual(response.status,200);response.read()
            finally:client.close()

    def test_connection_cap_closes_excess_client_and_releases_worker_slot(self):
        server=self.server();accepted=threading.Event()
        with patch.object(mobile,'MOBILE_PREVIEW_MAX_CLIENTS',1):
            state=server.start()
        handler=server._server.RequestHandlerClass
        setup=handler.setup

        def mark(request):
            setup(request);accepted.set()

        with patch.object(handler,'setup',mark):
            first=socket.create_connection(('127.0.0.1',state.port),timeout=3)
            self.addCleanup(first.close)
            self.assertTrue(accepted.wait(3))
            with socket.create_connection(('127.0.0.1',state.port),timeout=3) as second:
                try:self.assertEqual(second.recv(1),b'')
                except ConnectionResetError:pass
            first.sendall(f'GET /{state.token}/status.json HTTP/1.0\r\nHost: localhost\r\n\r\n'.encode())
            response=http.client.HTTPResponse(first)
            try:
                response.begin();self.assertEqual(response.status,200);response.read()
            finally:response.close()
        # Acquire blocks only until the just-completed worker's finally runs.
        self.assertTrue(server._server._client_slots.acquire(timeout=3))
        server._server._client_slots.release()


_BROWSER_HARNESS=r'''
const fs=require('fs'),vm=require('vm');const source=fs.readFileSync(0,'utf8');
const mode=__MODE__;const timers=[];let writes=0,aborted=false;
const image={hidden:false,removeAttribute(){delete this.url;},set src(value){writes++;this.url=value;}};
const empty={hidden:true},status={textContent:''};
const buttons=['preview','original','safety'].map(view=>({dataset:{view},classList:{add(){},remove(){}},setAttribute(k,v){this[k]=v;}}));
const document={hidden:false,getElementById(id){return {image,empty,status}[id];},querySelectorAll(){return buttons;}};
const context={document,AbortController,Date,JSON,Object,String,Boolean,Error,
 setTimeout(fn,ms){timers.push({fn,ms,active:true});return timers.length-1;},clearTimeout(id){timers[id].active=false;},
 async fetch(url,options){
  if(mode==='stalled')return new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>{aborted=true;reject(new Error('timeout'));}));
  if(mode==='http-error')return {ok:false};
  return {ok:true,async json(){return {revision:1,available:{preview:mode==='image-error',original:mode==='original',safety:false}};}};
 }};
(async()=>{vm.runInNewContext(source,context);await new Promise(resolve=>setImmediate(resolve));
 if(mode==='stalled'){timers.find(t=>t.ms===5000).fn();await new Promise(resolve=>setImmediate(resolve));}
 if(mode==='original')buttons[1].onclick();
 if(mode==='image-error'){image.onerror();timers.find(t=>t.ms===1000&&t.active).fn();await new Promise(resolve=>setImmediate(resolve));}
 process.stdout.write(JSON.stringify({writes,hidden:image.hidden,empty:empty.hidden,status:status.textContent,aborted,
  retry:timers.some(t=>t.ms===1000&&t.active),src:image.url,alt:image.alt,selected:buttons[1]['aria-pressed']}));
})().catch(error=>{console.error(error);process.exitCode=1;});
'''


@unittest.skipUnless(shutil.which('node'),'Node is used only to exercise the embedded browser script')
class MobileBrowserTests(unittest.TestCase):
    def run_browser(self,mode):
        source=mobile.MobilePreviewServer()._html('session-token').split('<script>',1)[1].split('</script>',1)[0]
        result=subprocess.run([shutil.which('node'),'-e',_BROWSER_HARNESS.replace('__MODE__',json.dumps(mode))],
                              input=source,text=True,capture_output=True,timeout=5,check=True)
        return json.loads(result.stdout)

    def test_empty_preview_shows_waiting_without_requesting_missing_images(self):
        state=self.run_browser('empty')
        self.assertEqual(state['writes'],0)
        self.assertTrue(state['hidden']);self.assertFalse(state['empty'])
        self.assertIn('waiting',state['status'])

    def test_http_error_and_stalled_request_both_schedule_reconnect(self):
        for mode in ('http-error','stalled'):
            with self.subTest(mode=mode):
                state=self.run_browser(mode)
                self.assertIn('Connection lost',state['status'])
                self.assertTrue(state['retry']);self.assertTrue(state['hidden'])
                if mode=='stalled':self.assertTrue(state['aborted'])

    def test_available_view_is_accessible_and_loads_its_own_image(self):
        state=self.run_browser('original')
        self.assertEqual(state['writes'],1)
        self.assertEqual(state['src'],'/session-token/original.png?v=1')
        self.assertEqual(state['alt'],'Original image')
        self.assertEqual(state['selected'],'true')

    def test_failed_image_retries_when_server_revision_has_not_changed(self):
        state=self.run_browser('image-error')
        self.assertEqual(state['writes'],2)
        self.assertFalse(state['hidden'])
        self.assertTrue(state['empty'])
        self.assertEqual(state['src'],'/session-token/preview.png?v=1')


if __name__=='__main__':unittest.main()
