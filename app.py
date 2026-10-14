"""Hosting entry point; keep the same startup path as python -m bot.main."""

import runpy


if __name__ == "__main__":
    runpy.run_module("bot.main", run_name="__main__")
