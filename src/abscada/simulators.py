"""Access to the development PLC simulators (package ``plc_simulators``, kept in tools/).

In the .exe the package is bundled; from a checkout, tools/ is added to the import path. An
installation without either simply offers no simulators.
"""
import sys
from pathlib import Path

try:
    import plc_simulators  # noqa: F401
except ImportError:
    _tools = Path(__file__).resolve().parents[2] / "tools"
    if (_tools / "plc_simulators").is_dir():
        sys.path.append(str(_tools))

try:
    from plc_simulators import SIMULATORS, for_example
except ImportError:
    SIMULATORS = {}

    def for_example(example):
        return None
