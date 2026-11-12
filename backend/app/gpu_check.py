"""``uv run python -m app.gpu_check`` - the same probe the app's "Check GPU setup" uses. Exit code 0 = GPU usable."""
from __future__ import annotations

import json
import sys

from .processing.backends import probe_cuda


def main() -> int:
    info = probe_cuda()
    print(json.dumps(info, indent=2))
    return 0 if info.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
