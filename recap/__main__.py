"""python -m recap --courses DIR --listen HOST:PORT
    starts PoliTo Recap, listening on HOST:PORT. The container launches it
    (docker-compose.yml). The settings come from the environment (settings.py).
"""
from __future__ import annotations

import argparse
from pathlib import Path

from . import server


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m recap", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--courses", type=Path, required=True, help="where the courses live")
    p.add_argument("--listen", required=True, help="where to listen, e.g. 0.0.0.0:8470")
    a = p.parse_args()
    server.run(a.courses, a.listen)


if __name__ == "__main__":
    main()
