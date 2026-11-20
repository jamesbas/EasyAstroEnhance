"""Pinned reference data (spec amendment 1.7 A): the star catalog and the deep-sky object catalog.

Downloaded only when the user asks, from fixed URLs, and verified by size and SHA-256 like the AI models."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..ai.registry import installed as _installed

GAIA_CREDIT = ("This work has made use of data from the European Space Agency (ESA) mission Gaia, processed by the Gaia "
               "Data Processing and Analysis Consortium (DPAC). Gaia DR3: Gaia Collaboration, Vallenari et al. 2023, A&A 674, A1.")
OPENNGC_COMMIT = "be3cd6c5498806a2fbb2f7e0452ef802dbb02be0"
OPENNGC_RAW = f"https://raw.githubusercontent.com/mattiaverga/OpenNGC/{OPENNGC_COMMIT}/database_files"


@dataclass(frozen=True)
class ReferenceSpec:
    id: str
    group: str  # stars | objects
    title: str
    file: str
    version: str
    url: str
    sha256: str
    size: int
    license: str
    license_url: str
    attribution: str
    source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DATA: dict[str, ReferenceSpec] = {
    s.id: s for s in (
        ReferenceSpec(
            id="stars-gaia-dr3", group="stars", title="Star catalog (Gaia DR3, stars to magnitude 13.5)",
            file="eae-stars-gaia-dr3-g13.5.bin", version="1",
            url="https://github.com/jamesbas/EasyAstroEnhance/releases/download/reference-data-1/eae-stars-gaia-dr3-g13.5.bin",
            sha256="81f828a15f6dd66fc4fd73e16cd492570968f9fdfdbbcbb327ca1795480a63b8", size=134_653_124,
            license="CC BY-SA 3.0 IGO", license_url="https://creativecommons.org/licenses/by-sa/3.0/igo/",
            attribution=GAIA_CREDIT, source="https://www.cosmos.esa.int/gaia (built by backend/tools/build_star_catalog.py)",
        ),
        ReferenceSpec(
            id="objects-openngc", group="objects", title="Deep-sky objects (OpenNGC: NGC, IC and Messier)",
            file="openngc-NGC.csv", version=OPENNGC_COMMIT[:7], url=f"{OPENNGC_RAW}/NGC.csv",
            sha256="54abea0b57b0a103831bfc7a8e3a99a23acfbf4bb581fcf3d8af539cbb826c84", size=3_942_946,
            license="CC BY-SA 4.0", license_url="https://creativecommons.org/licenses/by-sa/4.0/",
            attribution="OpenNGC by Mattia Verga and contributors", source="https://github.com/mattiaverga/OpenNGC",
        ),
        ReferenceSpec(
            id="objects-openngc-addendum", group="objects", title="Deep-sky objects (OpenNGC addendum: other Messier objects)",
            file="openngc-addendum.csv", version=OPENNGC_COMMIT[:7], url=f"{OPENNGC_RAW}/addendum.csv",
            sha256="c93f983dda6780b76b7b2e9271a856a892627710148a982ee98101a54c642fdd", size=17_496,
            license="CC BY-SA 4.0", license_url="https://creativecommons.org/licenses/by-sa/4.0/",
            attribution="OpenNGC by Mattia Verga and contributors", source="https://github.com/mattiaverga/OpenNGC",
        ),
    )
}

GROUPS = {"stars": ["stars-gaia-dr3"], "objects": ["objects-openngc", "objects-openngc-addendum"]}


def installed(data_dir: Path | None, key: str) -> Path | None:
    return _installed(data_dir, DATA[key])


def group_ready(data_dir: Path | None, group: str) -> bool:
    return all(installed(data_dir, k) is not None for k in GROUPS[group])
