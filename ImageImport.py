"""Bounded, cancellable image imports with content-based format detection."""
from contextlib import closing
from pathlib import Path
from numbers import Integral
import base64
import binascii
import os
import stat
import tempfile
import time

from PIL import Image, ImageOps, UnidentifiedImageError

_SPOOL_MEMORY_BYTES = 2 * 1024 * 1024
_BLOCK_BYTES = 64 * 1024
_MAX_URL_CHARACTERS = 65536
_DOWNLOAD_SECONDS = 45
# Limit public image input to the advertised raster decoders. In particular,
# opening an EPS must not implicitly launch Ghostscript, and a metafile must
# not dispatch a platform/custom renderer. JPEG's own factory also reads MPO;
# APNG uses the PNG decoder. DIB retains the BMP-family raster representation.
_RASTER_FORMATS = ('PNG','JPEG','WEBP','BMP','DIB','GIF','TIFF','ICO','AVIF')
_UNSUPPORTED_IMAGE = (
    'Could not read the image. Choose PNG, APNG, JPG, WEBP, BMP, GIF, TIFF, ICO '
    'or AVIF. Export documents or vector artwork to one of these raster formats first.'
)


def _check(cancelled, deadline=None):
    if cancelled():raise InterruptedError('Image import cancelled.')
    if deadline is not None and time.monotonic()>=deadline:
        raise ValueError('The download took too long. Save the image to your computer and select it locally.')


def _write_chunks(stream,chunks,limit,cancelled,deadline=None):
    total=0
    for chunk in chunks:
        _check(cancelled,deadline)
        if not chunk:continue
        if not isinstance(chunk,(bytes,bytearray,memoryview)):
            raise ValueError('Image data must contain bytes.')
        total+=len(chunk)
        if total>limit:raise ValueError('The image exceeds its supported file-size limit. Choose a smaller image.')
        stream.write(chunk)
    _check(cancelled,deadline)
    return total


def _local_chunks(path,limit,cancelled):
    descriptor=None
    try:
        _check(cancelled)
        if not path.is_file():raise ValueError('The selected image file no longer exists or is not a regular file.')
        descriptor=os.open(path,os.O_RDONLY|getattr(os,'O_BINARY',0)|getattr(os,'O_NONBLOCK',0))
        metadata=os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):raise ValueError('Choose a regular image file.')
        if metadata.st_size>limit:raise ValueError('The image file exceeds its supported file-size limit. Choose a smaller image.')
        with os.fdopen(descriptor,'rb') as source:
            descriptor=None
            # Read the same open file that is snapshotted; a prior stat result
            # cannot authorize an unlimited read after file growth/replacement.
            total=0
            while True:
                _check(cancelled)
                chunk=source.read(min(_BLOCK_BYTES,limit+1-total))
                if not chunk:break
                total+=len(chunk)
                yield chunk
                if total>limit:break
    except InterruptedError:
        raise
    except FileNotFoundError as error:
        raise ValueError('The selected image file no longer exists.') from error
    except OSError as error:
        raise ValueError(f'Could not access the selected image: {error}') from error
    finally:
        if descriptor is not None:os.close(descriptor)


def _base64_chunks(raw,limit,cancelled):
    comma=raw.find(',')
    if not 0<=comma<=1024:raise ValueError('The dropped browser image data is malformed.')
    header=raw[:comma]
    if header.split(';')[-1].casefold()!='base64':
        raise ValueError('Only base64 browser image drops are supported.')
    encoded_length=len(raw)-comma-1
    if encoded_length>4*((limit+2)//3):
        raise ValueError('The dropped browser image is too large. Choose a smaller image.')
    padding=raw.find('=',comma+1)
    if encoded_length%4 or (padding!=-1 and (padding<len(raw)-2 or set(raw[padding:])!={'='})):
        raise ValueError('The dropped browser image could not be decoded.')
    try:
        for start in range(comma+1,len(raw),_BLOCK_BYTES):
            _check(cancelled)
            yield base64.b64decode(raw[start:start+_BLOCK_BYTES],altchars=b'-_',validate=True)
    except (binascii.Error,ValueError) as error:
        raise ValueError('The dropped browser image could not be decoded.') from error


def _network_chunks(response):
    # read1 returns available body data without waiting to fill a 64 KiB chunk.
    # This lets the caller observe Stop/deadline between slow/trickling body reads.
    # Connection/header blocking still follows Requests' connect/read timeouts.
    reader=getattr(getattr(response,'raw',None),'read1',None)
    if callable(reader):
        while True:
            chunk=reader(_BLOCK_BYTES,decode_content=True)
            if not chunk:break
            yield chunk
    else:
        yield from response.iter_content(_BLOCK_BYTES)


def _download(stream,url,limit,cancelled):
    import requests
    from urllib3.exceptions import HTTPError
    from CanvasDropPayload import _is_http_url
    if len(url)>_MAX_URL_CHARACTERS or not _is_http_url(url):
        raise ValueError('Choose a valid direct image URL.')
    deadline=time.monotonic()+_DOWNLOAD_SECONDS
    response=None

    class ImportSession(requests.Session):
        def send(self,prepared,**options):
            # The Requests resolver calls this before every actual hop, after
            # its normal quoting/auth/cookie/proxy handling. Validate the exact
            # prepared destination and observe Stop before another connection.
            _check(cancelled,deadline)
            destination=prepared.url
            if not isinstance(destination,str) or len(destination)>_MAX_URL_CHARACTERS or not _is_http_url(destination):
                raise ValueError('The image server redirected to an invalid image URL.')
            return super().send(prepared,**options)

    session=ImportSession()

    def close_safely(resource):
        if resource is not None:
            try:resource.close()
            except Exception:
                # Cleanup cannot replace Stop, a primary transfer error or a
                # successfully verified final body.
                pass

    def inspect_response(item,*_args,**_kwargs):
        """Keep Requests' auth/cookie/proxy redirect logic, without body drain."""
        keep_body=False
        try:
            _check(cancelled,deadline)
            if not item.is_redirect or not item.headers.get('Location'):
                keep_body=True
                return item
            return item
        finally:
            if not keep_body:
                # Session.resolve_redirects reads response.content even with
                # stream=True (and when preparing Response.next). Close the
                # unread socket first, then expose an empty intermediate body.
                # Headers/raw metadata remain available to cookie handling.
                close_safely(item)
                item._content=b''
                item._content_consumed=True
    try:
        _check(cancelled,deadline)
        response=session.get(url,timeout=(10,15),stream=True,hooks={'response':inspect_response},headers={
            'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36',
            'Accept':'image/avif,image/webp,image/apng,image/*,*/*;q=0.8',
        })
        _check(cancelled,deadline)
        response.raise_for_status()
        headers=response.headers
        if 'text/html' in headers.get('Content-Type','').lower():
            raise ValueError('The link points to a web page. Right-click the image and choose Copy image address.')
        declared=headers.get('Content-Length')
        if declared is not None:
            if not isinstance(declared,str):
                raise ValueError('The image server sent an invalid Content-Length.')
            declared=declared.strip(' \t')
            if not declared.isascii() or not declared.isdecimal() or len(declared)>20:
                raise ValueError('The image server sent an invalid Content-Length.')
            declared=int(declared)
            if declared>limit:raise ValueError('The image download exceeds its supported file-size limit. Choose a smaller image.')
        total=_write_chunks(stream,_network_chunks(response),limit,cancelled,deadline)
        if headers.get('Content-Encoding','identity').lower() in ('','identity') and declared is not None and total!=declared:
            raise ValueError('The image download did not match its declared size. Try again.')
    except (requests.RequestException,HTTPError) as error:
        raise ValueError(f'Could not download the image: {error}') from error
    finally:
        close_safely(response)
        close_safely(session)


def _check_source_size(width,height,limit):
    if width<1 or height<1:raise ValueError('The image has invalid dimensions.')
    if width*height>limit:
        raise ValueError('The image is larger than 25 megapixels. Resize it first.')


def _preflight_icon_size(stream,limit,cancelled):
    """Check the selected ICO payload before Pillow's eager icon decoder.

    ICO directory dimensions can disagree with the embedded PNG/DIB. Inspect
    only the chosen payload header, preserving Pillow's stable area/depth order
    without retaining a possibly 65,535-entry directory or decoding pixels.
    Other formats still use their normal content-based Pillow identification.
    """
    position=stream.tell()
    try:
        header=stream.read(6)
        if header[:4]!=b'\x00\x00\x01\x00':return
        if len(header)!=6:raise ValueError('The icon directory is incomplete.')
        count=int.from_bytes(header[4:6],'little')
        chosen=None
        for index in range(count):
            if index%64==0:_check(cancelled)
            entry=stream.read(16)
            if len(entry)!=16:raise ValueError('The icon directory is incomplete.')
            width,height=entry[0] or 256,entry[1] or 256
            depth=int.from_bytes(entry[6:8],'little')
            colors=entry[2]
            depth=depth or ((colors-1).bit_length() if colors else 0) or 256
            rank=(-width*height,depth)
            if chosen is None or rank<chosen[0]:
                chosen=(rank,int.from_bytes(entry[12:16],'little'))
        if chosen is None:return  # Pillow reports the invalid empty directory.
        _check(cancelled)
        stream.seek(chosen[1])
        payload=stream.read(24)
        if payload.startswith(b'\x89PNG\r\n\x1a\n'):
            if len(payload)<24 or payload[12:16]!=b'IHDR':
                raise ValueError('The icon image header is incomplete or invalid.')
            width=int.from_bytes(payload[16:20],'big')
            height=int.from_bytes(payload[20:24],'big')
        else:
            header_size=int.from_bytes(payload[:4],'little')
            if header_size==12 and len(payload)>=8:
                width=int.from_bytes(payload[4:6],'little')
                height=int.from_bytes(payload[6:8],'little')//2
            elif header_size in (40,52,56,64,108,124) and len(payload)>=12:
                width=int.from_bytes(payload[4:8],'little')
                height=int.from_bytes(payload[8:12],'little')
                if payload[11]==255:height=2**32-height
                height//=2  # The DIB includes the XOR image and its AND mask.
            else:
                return  # Leave unsupported/malformed DIB validation to Pillow.
        _check_source_size(width,height,limit)
        _check(cancelled)
    finally:
        stream.seek(position)


def read_image(source,cancelled=lambda:False,*,max_download_bytes=20*1024*1024,
               max_source_bytes=50*1024*1024,max_source_pixels=25_000_000):
    _check(cancelled)
    if any(isinstance(value,bool) or not isinstance(value,Integral) or value<1
           for value in (max_download_bytes,max_source_bytes,max_source_pixels)):
        raise ValueError('Image import byte and pixel budgets must be positive integers.')
    max_download_bytes,max_source_bytes,max_source_pixels=map(int,
        (max_download_bytes,max_source_bytes,max_source_pixels))
    raw=str(source).strip()
    if not raw:raise ValueError('Choose an image first.')
    prefix=raw[:16].lower()
    with tempfile.SpooledTemporaryFile(max_size=_SPOOL_MEMORY_BYTES,mode='w+b') as snapshot:
        if prefix.startswith('data:image/'):
            _write_chunks(snapshot,_base64_chunks(raw,max_download_bytes,cancelled),max_download_bytes,cancelled)
        elif prefix.startswith(('http://','https://')):
            _download(snapshot,raw,max_download_bytes,cancelled)
        elif '://' in raw:
            raise ValueError('The image URL must start with https:// or http://.')
        else:
            _write_chunks(snapshot,_local_chunks(Path(raw),max_source_bytes,cancelled),max_source_bytes,cancelled)
        _check(cancelled)
        snapshot.seek(0)
        result=None
        try:
            _preflight_icon_size(snapshot,max_source_pixels,cancelled)
            with closing(Image.open(snapshot,formats=_RASTER_FORMATS)) as image:
                _check_source_size(image.width,image.height,max_source_pixels)
                _check(cancelled)
                detected=image.format or 'Unknown'
                oriented=ImageOps.exif_transpose(image)
                oriented.info.pop('draw_studio_color_managed',None)
                oriented.info.pop('draw_studio_bit_depth',None)
                from SourcePixelDepth import UNSIGNED_16BIT_MODES
                if oriented.info.get('icc_profile') or oriented.mode in UNSIGNED_16BIT_MODES:
                    from ImageColorManagement import srgb_source
                    with closing(oriented):result=srgb_source(oriented,cancelled=cancelled)
                elif oriented.mode=='RGBA':result=oriented
                else:
                    with closing(oriented):result=oriented.convert('RGBA')
                _check(cancelled)
                result.info['draw_studio_format']=detected
                return result
        except BaseException as error:
            if result is not None:result.close()
            if isinstance(error,InterruptedError):raise
            if isinstance(error,UnidentifiedImageError):
                raise ValueError(_UNSUPPORTED_IMAGE) from error
            if isinstance(error,OSError):
                raise ValueError(f'Could not decode the image: {error}') from error
            raise
