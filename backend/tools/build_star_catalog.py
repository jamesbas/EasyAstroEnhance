"""Build the pinned star catalog for sky solving and catalog colour (spec amendment 1.7 A).

    uv run python tools/build_star_catalog.py --work <scratch dir> --out <scratch dir>/eae-stars-gaia-dr3-g13.5.bin

Source: ESA Gaia DR3 (gaiadr3.gaia_source), all stars with phot_g_mean_mag < 13.5, queried from the ESA Gaia archive TAP
service in source_id chunks (cached in --work so an interrupted build resumes). Credit: "This work has made use of data
from the European Space Agency (ESA) mission Gaia (https://www.cosmos.esa.int/gaia), processed by the Gaia Data
Processing and Analysis Consortium (DPAC)." Gaia DR3: Gaia Collaboration, Vallenari et al. 2023, A&A 674, A1.
Licence of the derived file: CC BY-SA 3.0 IGO, as the source data.

The output is deterministic for a given Gaia release and magnitude limit (rows are sorted). Its layout is documented in
``app/processing/catalogs/stars.py``; that module is the only reader.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.processing.catalogs.stars import G_LIMIT, write_catalog  # noqa: E402

TAP = "https://gea.esac.esa.int/tap-server/tap"
HPX12 = 34359738368  # source_id // 2**35 is the HEALPix level-12 nested index
N_PIX12 = 12 * 4**12
CHUNKS = 96


def _post(url: str, data: dict[str, str]) -> tuple[str, str]:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), method="POST")
    with urllib.request.urlopen(req, timeout=600) as r:
        return r.geturl(), r.read().decode()


def _get(url: str) -> str:
    with urllib.request.urlopen(url, timeout=600) as r:
        return r.read().decode()


def query_chunk(lo: int, hi: int) -> str:
    q = (f"SELECT source_id, ra, dec, phot_g_mean_mag, bp_rp FROM gaiadr3.gaia_source "
         f"WHERE source_id >= {lo} AND source_id < {hi} AND phot_g_mean_mag < {G_LIMIT} ORDER BY source_id")
    job_url, _ = _post(f"{TAP}/async", {"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "PHASE": "RUN", "QUERY": q})
    for _ in range(720):
        phase = _get(f"{job_url}/phase").strip()
        if phase == "COMPLETED":
            return _get(f"{job_url}/results/result")
        if phase in ("ERROR", "ABORTED"):
            raise RuntimeError(f"Gaia query {lo}..{hi} ended in {phase}: {_get(job_url)[:500]}")
        time.sleep(2)
    raise TimeoutError(f"Gaia query {lo}..{hi} did not finish")


ROW_CAP = 50_000  # the archive returns at most this many rows per anonymous query; capped ranges are split


def fetch_range(lo_pix: int, hi_pix: int, work: Path) -> list[Path]:
    """CSV files covering HEALPix-12 pixels [lo_pix, hi_pix), split recursively until no query hits the row cap."""
    f = work / f"range-{lo_pix:09d}-{hi_pix:09d}.csv"
    if not f.exists():
        for attempt in range(3):
            try:
                text = query_chunk(lo_pix * HPX12, hi_pix * HPX12)
                break
            except Exception as exc:  # noqa: BLE001 - network or archive time limit: retry, then split
                print(f"range {lo_pix}-{hi_pix}: {str(exc)[:120]}; retrying", flush=True)
                time.sleep(15 * (attempt + 1))
        else:
            if hi_pix - lo_pix < 4:
                raise SystemExit(f"range {lo_pix}-{hi_pix} failed")
            print(f"range {lo_pix}-{hi_pix} keeps failing; splitting", flush=True)
            edges = [lo_pix + round(k * (hi_pix - lo_pix) / 4) for k in range(5)]
            return [p for a, b in zip(edges, edges[1:]) for p in fetch_range(a, b, work)]
        tmp = f.with_suffix(".part")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(f)
    rows = f.read_text(encoding="utf-8").count("\n") - 1
    if rows < ROW_CAP:
        return [f]
    print(f"range {lo_pix}-{hi_pix} hit the {ROW_CAP}-row cap; splitting", flush=True)
    edges = [lo_pix + round(k * (hi_pix - lo_pix) / 4) for k in range(5)]
    return [p for a, b in zip(edges, edges[1:]) for p in fetch_range(a, b, work)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--parallel", type=int, default=6, help="concurrent archive queries")
    args = ap.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    edges = [round(i * N_PIX12 / CHUNKS) for i in range(CHUNKS + 1)]
    with ThreadPoolExecutor(args.parallel) as pool:
        groups = list(pool.map(lambda i: fetch_range(edges[i], edges[i + 1], args.work), range(CHUNKS)))
    files = [f for g in groups for f in g]
    print(f"{len(files)} query results", flush=True)
    parts = []
    for f in files:
        rows = list(csv.reader(io.StringIO(f.read_text(encoding="utf-8"))))[1:]
        parts.append(np.array([[float(r[1]), float(r[2]), float(r[3]), float(r[4]) if r[4] else np.nan] for r in rows], np.float64).reshape(-1, 4))
    data = np.concatenate(parts)
    info = write_catalog(args.out, data[:, 0], data[:, 1], data[:, 2], data[:, 3])
    h = hashlib.sha256(args.out.read_bytes()).hexdigest()
    print(f"wrote {args.out} ({args.out.stat().st_size} bytes, {info['n_stars']} stars) sha256 {h}")


if __name__ == "__main__":
    main()
