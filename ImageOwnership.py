"""Dispose owned Pillow images without replacing an in-flight failure."""
from contextlib import contextmanager


def close_image(image, failure=None):
    """Preserve a primary error; a lone disposal error remains visible."""
    try:
        image.close()
    except BaseException as cleanup:
        if failure is None:
            raise
        failure.add_note(f'Owned image cleanup also failed: {type(cleanup).__name__}.')


@contextmanager
def closing_image(image):
    try:
        yield image
    except BaseException as failure:
        close_image(image, failure)
        raise
    else:
        close_image(image)
