"""pytest conftest: add src/ to sys.path so tests can import xiaozhi_bridge."""

import sys
from pathlib import Path

# Add src/ to Python path
src_path = Path(__file__).parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))
