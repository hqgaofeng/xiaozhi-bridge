"""Main entry point for xiaozhi-bridge.

Usage:
    python -m xiaozhi_bridge --config config.yaml
    xiaozhi-bridge --config config.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import signal
import sys
from pathlib import Path

from .config import AppConfig
from .server import XiaozhiBridgeServer
from .utils.logging import setup_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="xiaozhi-bridge",
        description="Lightweight WebSocket bridge for xiaozhi-esp32 devices",
    )
    parser.add_argument(
        "-c", "--config",
        type=Path,
        default=Path("config.yaml"),
        help="Path to config YAML file (default: config.yaml)",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=None,
        help="Override log level",
    )
    return parser.parse_args()


async def run_server(config: AppConfig) -> None:
    """Run the bridge server until interrupted."""
    server = XiaozhiBridgeServer(config)

    # Set up signal handlers
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _signal_handler():
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            # Windows doesn't support add_signal_handler
            loop.add_signal_handler(sig, _signal_handler)

    await server.start()
    try:
        await stop_event.wait()
    finally:
        await server.stop()


def main() -> int:
    """Entry point."""
    args = parse_args()

    if not args.config.exists():
        print(f"Error: config file not found: {args.config}", file=sys.stderr)
        print(f"Copy config/config.example.yaml to {args.config} and edit.", file=sys.stderr)
        return 1

    # Load config
    config = AppConfig.from_yaml(args.config)

    # Apply log level override
    if args.log_level:
        config.logging.level = args.log_level

    # Setup logging
    setup_logging(
        level=config.logging.level,
        fmt=config.logging.format,
        log_file=config.logging.file,
    )

    # Print startup info
    print("xiaozhi-bridge starting...")
    print(f"  config: {args.config}")
    print(f"  ws URL: ws://{config.server.host}:{config.server.port}{config.server.path}")
    print(f"  asr:    {config.asr.provider}")
    print(f"  tts:    {config.tts.provider}")
    print(f"  llm:    {config.openclaw.model} via {config.openclaw.base_url}")

    try:
        asyncio.run(run_server(config))
    except KeyboardInterrupt:
        print("\nShutdown requested...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
