"""Ensure the ``src`` layout is importable during test collection.

``pytest.ini`` declares ``pythonpath = src``, but that ini option is only
honored by some pytest versions/invocations. pytest always imports the
root ``conftest.py`` before collecting tests, so prepending ``src`` to
``sys.path`` here guarantees ``import depeg_monitor`` works on a clean
checkout regardless of pytest version or how the suite is launched.
"""

import sys
from pathlib import Path

_SRC = Path(__file__).parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
