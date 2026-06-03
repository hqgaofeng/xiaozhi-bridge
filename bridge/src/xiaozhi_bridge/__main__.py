"""Allow `python -m xiaozhi_bridge` invocation."""

from .main import main

if __name__ == "__main__":
    import sys
    sys.exit(main())
