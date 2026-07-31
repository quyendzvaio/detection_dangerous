"""Backward-compatible import path for the canonical product pipeline runner."""
from ai_engine.pipeline.runner import *  # noqa: F401,F403
from ai_engine.pipeline.runner import main


if __name__ == "__main__":
    raise SystemExit(main())
