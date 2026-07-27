"""
Limb-hierarchy world-space flattening for Ultima 9: Ascension models.

A :class:`titan.u9.model.U9Model` is a hierarchy of rigid **limbs**
(see that module's docstring): each limb's mesh is defined in a local
coordinate space relative to its parent limb, via a scale + quaternion
rotation + translation (TRS). Formats with no node/hierarchy concept
(OBJ, STL, PLY) need the geometry flattened into one shared world
space first; this module does that.

Matrix convention: 4x4, row-major, applied to **row vectors on the
right** (``p' = M @ p``), composed as ``M = T @ R @ S`` per limb --
i.e. a point is scaled first, then rotated, then translated. This
matches how the reference importer (``ultimaModelImporter.py``)
applies each limb's transform in Blender (``location``, then
``rotation_quaternion``, then ``scale``, as independent TRS channels
on a parented object -- Blender composes parented object transforms
the same T*R*S way). A limb's world matrix is its parent's world
matrix times its own local matrix; a root limb (``parent_id ==
limb_id``) has no parent multiplication.

Normals are transformed by the **inverse-transpose** of the 3x3
rotation+scale part, not the matrix itself -- required for correct
results whenever a limb's scale is non-uniform (X/Y/Z scaled
differently), which the model format explicitly allows (see
``U9Limb.scale``).
"""

from __future__ import annotations

__all__ = ["Mat4", "IDENTITY", "mat4_trs", "mat4_multiply", "transform_point", "transform_normal"]

import math

Vec3 = tuple[float, float, float]
Quat = tuple[float, float, float, float]
Mat4 = tuple[
    float, float, float, float,
    float, float, float, float,
    float, float, float, float,
    float, float, float, float,
]  # fmt: skip

IDENTITY: Mat4 = (
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
)  # fmt: skip


def _quat_to_mat3(q: Quat) -> tuple[float, ...]:
    """(w, x, y, z) unit quaternion -> row-major 3x3 rotation matrix (9 floats)."""
    w, x, y, z = q
    n = math.sqrt(w * w + x * x + y * y + z * z)
    if n > 0:
        w, x, y, z = w / n, x / n, y / n, z / n

    return (
        1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w),
        2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w),
        2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y),
    )  # fmt: skip


def mat4_trs(position: Vec3, rotation: Quat, scale: Vec3) -> Mat4:
    """Build a local TRS matrix: ``point' = T @ R @ S @ point``."""
    r = _quat_to_mat3(rotation)
    sx, sy, sz = scale
    tx, ty, tz = position

    return (
        r[0] * sx, r[1] * sy, r[2] * sz, tx,
        r[3] * sx, r[4] * sy, r[5] * sz, ty,
        r[6] * sx, r[7] * sy, r[8] * sz, tz,
        0.0, 0.0, 0.0, 1.0,
    )  # fmt: skip


def mat4_multiply(a: Mat4, b: Mat4) -> Mat4:
    result = [0.0] * 16
    for row in range(4):
        for col in range(4):
            result[row * 4 + col] = sum(a[row * 4 + k] * b[k * 4 + col] for k in range(4))
    return tuple(result)  # type: ignore[return-value]


def transform_point(m: Mat4, p: Vec3) -> Vec3:
    x, y, z = p
    return (
        m[0] * x + m[1] * y + m[2] * z + m[3],
        m[4] * x + m[5] * y + m[6] * z + m[7],
        m[8] * x + m[9] * y + m[10] * z + m[11],
    )


def _mat3_from_mat4(m: Mat4) -> tuple[float, ...]:
    return (m[0], m[1], m[2], m[4], m[5], m[6], m[8], m[9], m[10])


def _mat3_inverse_transpose(r: tuple[float, ...]) -> tuple[float, ...]:
    a, b, c, d, e, f, g, h, i = r
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if det == 0:
        return (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
    inv_det = 1.0 / det
    # inverse of r, then transposed -- written directly as the transpose-of-inverse's rows.
    inv = (
        (e * i - f * h) * inv_det, (c * h - b * i) * inv_det, (b * f - c * e) * inv_det,
        (f * g - d * i) * inv_det, (a * i - c * g) * inv_det, (c * d - a * f) * inv_det,
        (d * h - e * g) * inv_det, (b * g - a * h) * inv_det, (a * e - b * d) * inv_det,
    )  # fmt: skip
    # `inv` above is inverse(r) in row-major; its transpose swaps off-diagonal pairs.
    return (inv[0], inv[3], inv[6], inv[1], inv[4], inv[7], inv[2], inv[5], inv[8])


def transform_normal(m: Mat4, n: Vec3) -> Vec3:
    """Transform a normal by the inverse-transpose of ``m``'s 3x3 part, then re-normalize."""
    r = _mat3_from_mat4(m)
    it = _mat3_inverse_transpose(r)
    x, y, z = n
    tx = it[0] * x + it[1] * y + it[2] * z
    ty = it[3] * x + it[4] * y + it[5] * z
    tz = it[6] * x + it[7] * y + it[8] * z
    length = math.sqrt(tx * tx + ty * ty + tz * tz)
    if length == 0:
        return (0.0, 0.0, 0.0)
    return (tx / length, ty / length, tz / length)
