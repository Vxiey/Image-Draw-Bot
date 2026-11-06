"""Exercise byte budgets and real PNG decoding without external network access."""
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import base64
import threading
import unittest
from unittest.mock import Mock,patch
import numpy as np

from PIL import Image,ImageOps
import ImageImport as imports


def png_data():
    buffer=BytesIO();Image.new('RGBA',(5,4),(10,30,50,120)).save(buffer,format='PNG')
    return buffer.getvalue()


def response(data,headers=None,*,reader=False):
    item=SimpleNamespace(headers=headers or {},raise_for_status=Mock(),close=Mock(),raw=None)
    item.iter_content=Mock(return_value=iter([data]))
    if reader:item.raw=SimpleNamespace(read1=Mock(side_effect=[data,b'']))
    return item


class ImageImportTests(unittest.TestCase):
    def test_precancelled_import_does_not_open_source_or_allocate_snapshot(self):
        with patch.object(imports.tempfile,'SpooledTemporaryFile') as spool,patch('requests.Session.get') as request:
            for source in ('missing.png','https://example.test/image.png','data:image/png;base64,YQ=='):
                with self.subTest(source=source),self.assertRaises(InterruptedError):imports.read_image(source,lambda:True)
        spool.assert_not_called();request.assert_not_called()

    def test_local_snapshot_survives_source_replacement_during_decode(self):
        data=png_data()
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'source.png';path.write_bytes(data)
            opened=Image.open
            def replace_source(stream,*args,**kwargs):
                path.write_bytes(b'now invalid')
                return opened(stream,*args,**kwargs)
            with patch.object(imports.Image,'open',side_effect=replace_source):result=imports.read_image(path)
        self.assertEqual(result.getpixel((0,0)),(10,30,50,120))
        self.assertEqual(result.info['draw_studio_format'],'PNG')

    def test_growing_local_file_is_bounded_by_actual_bytes_before_decoder(self):
        data=png_data()
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'source.png';path.write_bytes(data)
            fstat=imports.os.fstat
            def lie(descriptor):
                result=fstat(descriptor)
                return SimpleNamespace(st_mode=result.st_mode,st_size=1)
            with patch.object(imports.os,'fstat',side_effect=lie),patch.object(imports.Image,'open') as decoder:
                with self.assertRaisesRegex(ValueError,'file-size limit'):imports.read_image(path,max_source_bytes=20)
            decoder.assert_not_called()

    def test_stop_during_local_read_stays_an_interruption(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'source.png';path.write_bytes(png_data())
            calls=0
            def cancelled():
                nonlocal calls
                calls+=1;return calls>=4
            with self.assertRaises(InterruptedError):imports.read_image(path,cancelled)

    def test_data_uri_decode_is_block_bounded_and_accepts_parser_urlsafe_alphabet(self):
        data=png_data()+bytes(range(256))*500
        encoded=base64.urlsafe_b64encode(data).decode();calls=[];decode=base64.b64decode
        def traced(value,**kwargs):
            calls.append(len(value));return decode(value,**kwargs)
        with patch.object(imports.base64,'b64decode',side_effect=traced):
            image=imports.read_image('data:image/png;base64,'+encoded)
        self.assertEqual(image.size,(5,4));self.assertGreater(len(calls),1)
        self.assertLessEqual(max(calls),imports._BLOCK_BYTES)

    def test_oversized_base64_rejected_before_decoding(self):
        with patch.object(imports.base64,'b64decode') as decode:
            with self.assertRaisesRegex(ValueError,'too large'):imports.read_image('data:image/png;base64,'+'A'*28,max_download_bytes=12)
        decode.assert_not_called()

    def test_invalid_import_budgets_cannot_turn_a_bounded_read_into_an_unlimited_read(self):
        for key in ('max_download_bytes','max_source_bytes','max_source_pixels'):
            for value in (0,-1,True,float('inf'),'64'):
                with self.subTest(key=key,value=value),patch.object(imports.tempfile,'SpooledTemporaryFile') as spool:
                    with self.assertRaises(ValueError):imports.read_image('example.png',**{key:value})
                    spool.assert_not_called()

    def test_numpy_integral_budget_cannot_overflow_into_an_unlimited_file_read(self):
        reads=[];opened=imports.os.fdopen
        class CheckedReader:
            def __init__(self,source):self.source=source
            def __enter__(self):self.source.__enter__();return self
            def __exit__(self,*args):return self.source.__exit__(*args)
            def read(self,size):
                reads.append(size)
                self_test.assertGreater(size,0);self_test.assertLessEqual(size,imports._BLOCK_BYTES)
                return self.source.read(size)
        self_test=self
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'source.png';path.write_bytes(png_data())
            with patch.object(imports.os,'fdopen',side_effect=lambda *args,**kwargs:CheckedReader(opened(*args,**kwargs))):
                result=imports.read_image(path,max_source_bytes=np.int64(2**63-1))
        self.assertEqual(result.size,(5,4));self.assertTrue(reads)

    def test_base64_padding_cannot_hide_trailing_encoded_payload(self):
        for value in ('YQ==AAAA','YQ=','====','YQ==YQ=='):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'decoded'):
                imports.read_image('data:image/png;base64,'+value)

    def test_download_uses_available_body_reads_instead_of_waiting_for_large_chunk(self):
        item=response(png_data(),reader=True)
        with patch('requests.Session.get',return_value=item):result=imports.read_image('https://example.test/image.png')
        self.assertEqual(result.size,(5,4));item.iter_content.assert_not_called()
        item.raw.read1.assert_called_with(imports._BLOCK_BYTES,decode_content=True)
        item.close.assert_called_once()

    def test_content_length_is_checked_and_compressed_lengths_are_not_decoded_lengths(self):
        data=png_data()
        for length in ('-1','x','12, 12','9'*21,str(len(data)+1)):
            item=response(data,{'Content-Length':length})
            with self.subTest(length=length),patch('requests.Session.get',return_value=item),self.assertRaises(ValueError):
                imports.read_image('https://example.test/image.png')
            item.close.assert_called_once()
        item=response(data,{'Content-Length':'20','Content-Encoding':'gzip'})
        with patch('requests.Session.get',return_value=item):self.assertEqual(imports.read_image('https://example.test/image.png').size,(5,4))
        item=response(data,{'Content-Length':f'\t {len(data)} '})
        with patch('requests.Session.get',return_value=item):self.assertEqual(imports.read_image('https://example.test/image.png').size,(5,4))

    def test_cancel_during_download_preserves_interruption_even_if_close_fails(self):
        stop=threading.Event();item=response(png_data())
        def chunks(size):stop.set();yield png_data()
        item.iter_content=chunks;item.close.side_effect=OSError('cleanup failed')
        with patch('requests.Session.get',return_value=item),self.assertRaises(InterruptedError):
            imports.read_image('https://example.test/image.png',stop.is_set)

    def test_stop_after_decoding_closes_unpublished_result(self):
        stop=threading.Event();outputs=[];transpose=ImageOps.exif_transpose
        def traced(image):
            result=transpose(image);outputs.append(result);stop.set();return result
        with patch.object(imports.ImageOps,'exif_transpose',side_effect=traced),self.assertRaises(InterruptedError):
            imports.read_image('data:image/png;base64,'+base64.b64encode(png_data()).decode(),stop.is_set)
        with self.assertRaises(ValueError):outputs[0].getpixel((0,0))

    def test_large_encoded_input_rolls_to_private_disk_storage(self):
        data=png_data();spools=[];factory=imports.tempfile.SpooledTemporaryFile
        def observed(*args,**kwargs):
            stream=factory(*args,**kwargs);spools.append(stream);return stream
        with patch.object(imports,'_SPOOL_MEMORY_BYTES',32),patch.object(imports.tempfile,'SpooledTemporaryFile',side_effect=observed):
            result=imports.read_image('data:image/png;base64,'+base64.b64encode(data).decode())
        self.assertTrue(spools[0]._rolled);self.assertTrue(spools[0].closed)
        self.assertEqual(result.getpixel((0,0)),(10,30,50,120))


if __name__=='__main__':unittest.main()
