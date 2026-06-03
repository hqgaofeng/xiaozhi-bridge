"""Allow `python -m xiaozhi_bridge.api` to start the HTTP API.

This file exists so the docker-compose `bridge-api` service can
launch the API with `python -m xiaozhi_bridge.api ...` (and so dev
users can do the same).

Without __main__.py, `python -m <package>` raises:
  "No module named xiaozhi_bridge.api.__main__; 'xiaozhi_bridge.api'
   is a package and cannot be directly executed"
"""

from .main import main

if __name__ == "__main__":
    raise SystemExit(main())
