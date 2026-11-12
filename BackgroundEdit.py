"""Source-bound background edits transfer their existing private Undo snapshot."""
from dataclasses import dataclass

from PIL import Image


@dataclass(frozen=True)
class BackgroundEditResult:
    image: Image.Image
    metadata: dict
    source: Image.Image
    undo_image: Image.Image | None = None

    def release(self, *, keep=(), failure=None):
        """Retire unpublished buffers while preserving the borrowed live source."""
        retained = {id(image) for image in (*keep, self.source)}
        errors = []
        images = {id(image): image for image in (self.image, self.undo_image)
                  if isinstance(image, Image.Image)}
        for key, image in images.items():
            if key not in retained:
                try:
                    image.close()
                except BaseException as error:
                    errors.append(error)
        if errors:
            if failure is not None:
                failure.add_note('Background edit cleanup also failed: ' + type(errors[0]).__name__)
            else:
                raise errors[0]
