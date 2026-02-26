"""script to run the worker"""

import asyncio
import sys
import argparse
from pathlib import Path

from scietex.modbus_service import ModbusWorker


async def main_async(args) -> int:
    """Main function for modbus service."""

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--conf-dir", type=Path, help="Path to configuration directory (optional)"
    )
    parser.add_argument(
        "--worker-id",
        type=int,
        help="Worker id (integer value, optional, defaults to 1)",
    )
    parsed_args = parser.parse_args(args)

    if parsed_args.conf_dir is not None:
        print(f"Using custom config directory: {parsed_args.conf_dir}")

        # Validate the directory
        if not parsed_args.conf_dir.exists():
            print(f"Error: Directory {parsed_args.conf_dir} does not exist!")
            return 1
        if not parsed_args.conf_dir.is_dir():
            print(f"Error: {parsed_args.conf_dir} is not a directory!")
            return 1

    modbus_service = ModbusWorker(
        config_dir=parsed_args.conf_dir, worker_id=parsed_args.worker_id
    )
    await modbus_service.run()
    return 0


def main() -> int:
    """Synchronous wrapper for console_scripts"""
    try:
        return asyncio.run(main_async(sys.argv[1:]))
    # pylint: disable=broad-exception-caught
    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
