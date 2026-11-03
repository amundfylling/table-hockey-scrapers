import argparse
import sys

from ..common.context import add_common_args, build_context
from . import run


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m scrapers.finland")
    add_common_args(parser)
    ctx = build_context(parser.parse_args())
    run(ctx)
    return 0


if __name__ == "__main__":
    sys.exit(main())
