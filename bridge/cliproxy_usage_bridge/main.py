from __future__ import annotations

import argparse

from .config import load_config
from .server import serve
from .service import SummaryService


def main() -> None:
    parser = argparse.ArgumentParser(description="Local CLIProxyAPI usage bridge")
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    serve(SummaryService(load_config(args.config)))


if __name__ == "__main__":
    main()
