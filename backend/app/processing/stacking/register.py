"""Star-based registration: triangle-invariant matching + RANSAC similarity (rotation, uniform scale, shift).

Triangles of bright stars are described by their side-length ratios, which do not change under rotation, scale or
shift (an alt-az mount rotates the field during a session). Matching triangles propose star correspondences; each
proposal is checked by how many of all measured stars it maps onto reference stars, and the best is refined by a
least-squares fit on every inlier. The model maps frame coordinates to reference coordinates:
``x' = a*x - b*y + tx``, ``y' = b*x + a*y + ty``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import combinations

import numpy as np
from scipy.spatial import cKDTree

from .quality import StarList

N_TRIANGLE_STARS = 25
INVARIANT_TOL = 0.01
MATCH_RADIUS = 2.5  # reference pixels
MIN_INLIERS = 8
MAX_HYPOTHESES = 600


@dataclass(frozen=True)
class Transform:
    a: float
    b: float
    tx: float
    ty: float

    @property
    def scale(self) -> float:
        return float(np.hypot(self.a, self.b))

    @property
    def angle_deg(self) -> float:
        return float(np.degrees(np.arctan2(self.b, self.a)))

    def apply(self, x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return self.a * x - self.b * y + self.tx, self.b * x + self.a * y + self.ty

    def inverse(self) -> "Transform":
        d = self.a**2 + self.b**2
        ia, ib = self.a / d, -self.b / d
        return Transform(ia, ib, -(ia * self.tx - ib * self.ty), -(ib * self.tx + ia * self.ty))

    def scaled(self, s: float) -> "Transform":
        """The same mapping onto a reference grid scaled by ``s`` (pixel centres preserved)."""
        off = (s - 1.0) / 2.0  # centre-of-pixel convention: x_s = s*x + (s-1)/2
        return Transform(self.a * s, self.b * s, self.tx * s + off, self.ty * s + off)

    def to_dict(self) -> dict[str, float]:
        return {**asdict(self), "scale": self.scale, "rotation_deg": self.angle_deg}


IDENTITY = Transform(1.0, 0.0, 0.0, 0.0)


def fit_similarity(src: np.ndarray, dst: np.ndarray) -> Transform:
    n = len(src)
    A = np.zeros((2 * n, 4))
    A[0::2] = np.column_stack([src[:, 0], -src[:, 1], np.ones(n), np.zeros(n)])
    A[1::2] = np.column_stack([src[:, 1], src[:, 0], np.zeros(n), np.ones(n)])
    rhs = dst.reshape(-1)
    p, *_ = np.linalg.lstsq(A, rhs, rcond=None)
    return Transform(*map(float, p))


def _triangles(pts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    combos = np.array(list(combinations(range(len(pts)), 3)), dtype=np.int32)
    if combos.size == 0:
        return np.zeros((0, 2)), np.zeros((0, 3), np.int32)
    p = pts[combos]  # (T, 3, 2)
    # side opposite vertex k
    d = np.stack([np.linalg.norm(p[:, 1] - p[:, 2], axis=1), np.linalg.norm(p[:, 0] - p[:, 2], axis=1), np.linalg.norm(p[:, 0] - p[:, 1], axis=1)], 1)
    order = np.argsort(d, axis=1)  # vertices ordered by the length of their opposite side
    ds = np.take_along_axis(d, order, 1)
    ok = ds[:, 2] > 1e-6
    inv = np.column_stack([ds[:, 0] / np.maximum(ds[:, 2], 1e-9), ds[:, 1] / np.maximum(ds[:, 2], 1e-9)])
    verts = np.take_along_axis(combos, order, 1)
    return inv[ok], verts[ok]


@dataclass
class Match:
    ok: bool
    transform: Transform | None = None
    inliers: int = 0
    rms: float | None = None
    reason: str | None = None


def match(ref: StarList, cur: StarList, scale_range: tuple[float, float] = (0.9, 1.1)) -> Match:
    if len(ref.x) < 6 or len(cur.x) < 6:
        return Match(False, reason="too few stars to align")
    rp = np.column_stack([ref.x, ref.y])
    cp = np.column_stack([cur.x, cur.y])
    r_top, c_top = ref.top(N_TRIANGLE_STARS), cur.top(N_TRIANGLE_STARS)
    r_inv, r_tri = _triangles(np.column_stack([r_top.x, r_top.y]))
    c_inv, c_tri = _triangles(np.column_stack([c_top.x, c_top.y]))
    if len(r_inv) == 0 or len(c_inv) == 0:
        return Match(False, reason="too few stars to align")
    tree = cKDTree(r_inv)
    dist, idx = tree.query(c_inv, distance_upper_bound=INVARIANT_TOL)
    hits = np.nonzero(np.isfinite(dist))[0]
    if hits.size == 0:
        return Match(False, reason="no matching star patterns")
    hits = hits[np.argsort(dist[hits])][:MAX_HYPOTHESES]
    ref_tree = cKDTree(rp)
    r_top_xy = np.column_stack([r_top.x, r_top.y])
    c_top_xy = np.column_stack([c_top.x, c_top.y])
    best: tuple[int, Transform | None, np.ndarray | None] = (0, None, None)
    for h in hits:
        src = c_top_xy[c_tri[h]]
        dst = r_top_xy[r_tri[idx[h]]]
        t = fit_similarity(src, dst)
        if not (scale_range[0] <= t.scale <= scale_range[1]):
            continue
        tx, ty = t.apply(cp[:, 0], cp[:, 1])
        dd, ii = ref_tree.query(np.column_stack([tx, ty]), distance_upper_bound=MATCH_RADIUS)
        good = np.isfinite(dd)
        n_in = int(good.sum())
        if n_in > best[0]:
            best = (n_in, t, np.column_stack([np.nonzero(good)[0], ii[good]]))
            if n_in >= 0.8 * min(len(cp), len(rp)):
                break
    n_in, t, pairs = best
    if t is None or n_in < MIN_INLIERS:
        return Match(False, inliers=n_in, reason=f"alignment not confirmed ({n_in} matching stars)")
    for _ in range(2):  # refine on all inliers, then re-collect inliers
        t = fit_similarity(cp[pairs[:, 0]], rp[pairs[:, 1]])
        tx, ty = t.apply(cp[:, 0], cp[:, 1])
        dd, ii = ref_tree.query(np.column_stack([tx, ty]), distance_upper_bound=MATCH_RADIUS)
        good = np.isfinite(dd)
        pairs = np.column_stack([np.nonzero(good)[0], ii[good]])
        if len(pairs) < MIN_INLIERS:
            return Match(False, inliers=len(pairs), reason="alignment not confirmed after refinement")
    tx, ty = t.apply(cp[pairs[:, 0], 0], cp[pairs[:, 0], 1])
    rms = float(np.sqrt(np.mean((tx - rp[pairs[:, 1], 0]) ** 2 + (ty - rp[pairs[:, 1], 1]) ** 2)))
    return Match(True, t, int(len(pairs)), rms)
