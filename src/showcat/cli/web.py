"""CLI command: generate the showcat.favet.net static HTML page.

Usage:
    python -m showcat.cli.web [--output-dir ./public]

Reads scored shows from the database (last pipeline run) and writes
public/index.html. Point a web server at that directory or copy it to your
static host.
"""
import argparse

from showcat.core import config as _config  # noqa: F401  (loads .env on import)
from showcat.core.database import get_db_session
from showcat.outputs.web.adapter import WebOutputAdapter


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate showcat static HTML page.")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory to write index.html (default: WEB_OUTPUT_DIR env or ./public)",
    )
    args = parser.parse_args()

    adapter = WebOutputAdapter(output_dir=args.output_dir)
    with get_db_session() as session:
        out_path = adapter.write(session)
    print(f"Written: {out_path}")


if __name__ == "__main__":
    main()
