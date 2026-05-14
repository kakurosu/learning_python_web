"""pytest configuration: register the ``kernel`` marker."""

import sys
from pathlib import Path


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "kernel: tests that require a running Jupyter kernel"
    )


# Ensure the project root is on sys.path so ``import app...`` works when running
# pytest from the repo root.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
