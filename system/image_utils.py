"""
Various functions for dealing with image data.

Author: Tal Eisenberg, 2021
"""
import io
from PIL import Image
import numpy as np
import collections


def _normalize_image_for_pillow(img: np.ndarray) -> np.ndarray:
    """
    Normalize numpy image layout to a format Pillow accepts.

    Supported outputs:
    - Grayscale: (H, W)
    - Color: (H, W, 3) or (H, W, 4)
    """
    if not isinstance(img, np.ndarray):
        raise TypeError(f"Expected numpy.ndarray image, got: {type(img).__name__}")

    if img.ndim == 2:
        return img

    if img.ndim == 3:
        # Allied Vision mono streams may produce (H, W, 1): convert to grayscale.
        if img.shape[2] == 1:
            return img.squeeze(axis=2)
        if img.shape[2] in (3, 4):
            return img

    raise ValueError(
        f"Unsupported image shape for PIL encoding: {img.shape}. "
        "Expected (H,W), (H,W,1), (H,W,3), or (H,W,4)."
    )


def resize_image(img: Image, size=(None, None)):
    """
    Resize an image to the desired size.

    :param img: The image as a PIL Image object.
    :param size: A (width, height) tuple.

    When both width and height are None, a copy of the original image is returned.
    When one of the size parameters is None, the returned image will retain the aspect
    ratio of the original image.
    """
    if (size[0] is None and size[1] is None) or (
        size[0] == img.size[0] and size[1] == img.size[1]
    ):
        return img.copy()

    elif size[0] is None or size[1] is None:
        ratio = img.size[0] / img.size[1]

        if size[0] is None:
            if size[1] == img.size[1]:
                return img.copy()
            else:
                size = (int(size[1] * ratio), size[1])

        elif size[1] is None:
            if size[0] == img.size[0]:
                return img.copy()
            else:
                size = (size[0], int(size[0] / ratio))

    return img.resize((int(size[0]), int(size[1])), resample=Image.BOX)


def encode_image(img, encoding="WebP", encode_params={}, shape=(None, None)):
    """
    Encode the supplied image using the Pillow library, possibly resizing it first.
    For possible encodings and encoding parameters see: https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html

    :param img: A numpy array containing image data.
    :param encoding: A string with the desired encoding (see Pillow docs)
    :param encode_params: A dict with encoding paramaeters (see Pillow docs)
    :param shape: The desired shape passed to resize_image (see above)

    Return the encoded image as a byte string.
    """
    img = _normalize_image_for_pillow(img)
    im = resize_image(Image.fromarray(img), shape)
    with io.BytesIO() as output:
        im.save(output, format=encoding, **encode_params)
        return output.getvalue()


def convert_to_8bit(img, scaling_param):
    """
    Convert an image numpy array to a uint8 numpy array, scaling each pixel channel intensity according to `scaling_param`.

    Args:
    - img: The original image (numpy array).
    - scaling_param: Any of the following:
        - "auto" (str): Scale pixel intensities linearly so that the image minimum becomes 0 and the maximum becomes 255.
        - "full_range" (str): Linear scaling which maps 0 to 0 and 65535 to 255.
        - [a, b] (any two-element sequence): Linear scaling which maps a to 0 and b to 255.

    """
    if isinstance(scaling_param, str):
        if scaling_param == "truncate":
            return img.astype("uint8")
        if scaling_param == "auto":
            smin, smax = img.min(), img.max()
        elif scaling_param == "full_range":
            smin, smax = 0, (2**16) - 1
        else:
            raise ValueError(f"Invalid scaling_8bit parameter value: {scaling_param}")
    elif isinstance(scaling_param, collections.abc.Sequence):
        smin, smax = scaling_param
    else:
        raise ValueError(f"Invalid scaling_8bit parameter value: {scaling_param}")

    if smax == smin:
        return img
    else:
        return np.clip(
            255.0 * (img.astype("int32") - smin) / (smax - smin), 0, 255
        ).astype("uint8")
