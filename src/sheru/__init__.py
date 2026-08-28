"""Sheru — a hands-free personal assistant for macOS."""


def main() -> int:
    from .app import main as _main
    return _main()
