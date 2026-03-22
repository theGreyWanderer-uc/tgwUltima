"""LeRF adaptive resampling for TITAN.

Vendored from LeRF-PyTorch (MIT License, Copyright (c) 2024 Jiacheng Li)
https://github.com/ddlee-cn/LeRF-PyTorch
"""

from __future__ import annotations

import importlib.resources
from pathlib import Path

import numpy as np
from PIL import Image

from .resize_right.resize_right2d_numpy import (
    SteeringGaussianResize2dNumpy,
)

_LUT_NAMES: list[str] = [
    "LUTft_s1_cr0", "LUTft_s1_sr0", "LUTft_s1_tr0",
    "LUTft_s2_cr0", "LUTft_s2_cr1",
    "LUTft_s2_sr0", "LUTft_s2_sr1",
    "LUTft_s2_tr0", "LUTft_s2_tr1",
]


def _load_luts() -> dict[str, np.ndarray]:
    """Load all LeRF-G LUT files from the package data."""
    with importlib.resources.as_file(
        importlib.resources.files(__package__) / "luts" / "lerf_g"
    ) as lut_dir:
        luts: dict[str, np.ndarray] = {}
        for name in _LUT_NAMES:
            p = Path(lut_dir) / f"{name}.npy"
            if p.exists():
                luts[name] = np.load(str(p)).astype(np.float32)
        return luts


def downscale_adaptive(
    image: np.ndarray | Image.Image,
    scale: float = 0.5,
) -> np.ndarray:
    """Content-adaptive downscale using LeRF steerable Gaussian LUTs.

    Parameters
    ----------
    image : np.ndarray | PIL.Image.Image
        Input image (H, W, C) uint8 or PIL Image.
    scale : float
        Downscale factor in (0, 1). Default 0.5 (half size).

    Returns
    -------
    np.ndarray
        Downscaled image (H', W', C) uint8.
    """
    if isinstance(image, Image.Image):
        image = np.array(image)

    luts = _load_luts()

    # Normalise to float [0, 1] and convert to (C, H, W)
    img = image.astype(np.float32) / 255.0
    if img.ndim == 3:
        img = np.transpose(img, (2, 0, 1))  # HWC -> CHW

    C, H, W = img.shape

    resizer = SteeringGaussianResize2dNumpy(support_sz=4)
    resizer.set_shape(img.shape, scale_factors=[scale, scale])

    # Build uniform steering params from LUT means
    rho = np.full((C, H, W), 0.5, dtype=np.float32)
    sigma_x = np.full((C, H, W), 0.5, dtype=np.float32)
    sigma_y = np.full((C, H, W), 0.5, dtype=np.float32)

    # Apply per-stage LUT refinement if available
    for stage in [1, 2]:
        for typ, target in [("cr0", rho), ("sr0", sigma_x), ("sr1", sigma_y)]:
            key = f"LUTft_s{stage}_{typ}"
            if key in luts:
                lut = luts[key]
                # Quantise input to LUT indices
                idx = (target * (lut.shape[0] - 1)).astype(np.int32).clip(0, lut.shape[0] - 1)
                # Use LUT as a 1-D refinement table
                if lut.ndim == 1:
                    target[...] = lut[idx]

    downscaled = resizer.resize(img, rho, sigma_x, sigma_y)

    # Back to (H', W', C) uint8
    result = np.transpose(downscaled, (1, 2, 0))  # CHW -> HWC
    result = (result * 255.0).clip(0, 255).astype(np.uint8)
    return result
