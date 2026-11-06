"""Convert embedded source color profiles to the planner's sRGB color space."""
from contextlib import ExitStack, closing
from io import BytesIO

from PIL import ImageCms

MAX_ICC_BYTES = 4 * 1024 * 1024


def srgb_source(image, *, cancelled=lambda: False):
    """Return an owned RGBA image, preserving alpha and the borrowed source.

    Ordinary untagged images retain the existing sRGB assumption. An embedded
    profile is honored with relative colorimetric conversion, not merely copied
    onto unchanged RGB numbers. Invalid profiles stop the import with a useful
    error rather than silently painting with a different color interpretation.
    """
    if cancelled():raise InterruptedError('Image color conversion cancelled.')
    raw = image.info.get('icc_profile')
    if raw is None or raw == b'':
        return image.convert('RGBA')
    if not isinstance(raw, bytes) or len(raw) > MAX_ICC_BYTES:
        raise ValueError('The embedded image color profile is invalid or larger than 4 MiB. Export the image as sRGB and try again.')
    result = None
    try:
        source_profile = ImageCms.ImageCmsProfile(BytesIO(raw))
        target_profile = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB'))
        with ExitStack() as owned:
            alpha = None
            if image.mode in ('CMYK', 'LAB'):
                prepared = image
                alpha = 255
            elif image.mode in ('L', 'LA') and source_profile.profile.xcolor_space.strip() == 'GRAY':
                prepared = image if image.mode == 'L' else owned.enter_context(closing(image.getchannel('L')))
                if image.mode == 'LA':
                    alpha = owned.enter_context(closing(image.getchannel('A')))
                elif 'transparency' in image.info:
                    rgba = owned.enter_context(closing(image.convert('RGBA')))
                    alpha = owned.enter_context(closing(rgba.getchannel('A')))
                else:
                    alpha = 255
            else:
                # Resolve indexed/colorkey transparency before CMS, which does
                # not interpret Pillow's separate transparency metadata.
                prepared = image if image.mode == 'RGBA' else owned.enter_context(closing(image.convert('RGBA')))
            if cancelled():raise InterruptedError('Image color conversion cancelled.')
            result = ImageCms.profileToProfile(prepared, source_profile, target_profile,
                renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC, outputMode='RGBA')
            # CMS transforms from non-alpha modes can initialize the extra
            # output channel to zero. Source opacity/color-key transparency is
            # independent of the color transform and must be restored explicitly.
            if alpha is not None:result.putalpha(alpha)
            result.info.update(image.info)
            result.info.pop('transparency', None)
            result.info['icc_profile'] = target_profile.tobytes()
            result.info['draw_studio_color_managed'] = 'sRGB from embedded ICC'
            if cancelled():raise InterruptedError('Image color conversion cancelled.')
            return result
    except BaseException as error:
        if result is not None:result.close()
        if isinstance(error, InterruptedError):raise
        if isinstance(error, (ImageCms.PyCMSError, OSError, TypeError, ValueError)):
            raise ValueError('The embedded image color profile could not be converted. Export the image as sRGB and try again.') from error
        raise
