"""Start the local server: ``uv run python -m app.serve``. Binds to 127.0.0.1 only."""
from __future__ import annotations

import multiprocessing
import threading
import time
import webbrowser

import uvicorn

from .config import load_config
from .main import create_app


def main() -> None:
    cfg = load_config()
    app = create_app(cfg)
    url = f"http://127.0.0.1:{cfg.port}/"
    print(f"EasyAstroEnhance is running at {url}  (Ctrl+C to stop). Data folder: {cfg.data_dir}")
    if not cfg.frontend_dist:
        print("Note: the frontend is not built yet; run scripts\\setup.ps1")
    import os

    if os.environ.get("EASYASTRO_NO_BROWSER") != "1":
        threading.Thread(target=lambda: (time.sleep(1.5), webbrowser.open(url)), daemon=True).start()
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="warning")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
