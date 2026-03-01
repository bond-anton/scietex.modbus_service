"""Worker module for modbus service."""

import asyncio
import time
from typing import Any

from scietex.service import ValkeyWorker
from scietex.hal.serial import ModbusSerialConnectionConfig, VirtualSerialNetwork

from .version import __version__

TASKS = [
    (1, {"data": "Read configuration", "timeout": 10.0}),
]


# pylint: disable=too-many-instance-attributes
class ModbusWorker(ValkeyWorker):
    """Worker class for modbus service."""

    tasks = asyncio.Queue()

    def __init__(self, **kwargs) -> None:
        super().__init__(service_name="modbus", version=__version__, **kwargs)
        self.modbus_port: ModbusSerialConnectionConfig | None = None
        self.vsn: VirtualSerialNetwork = VirtualSerialNetwork(
            virtual_ports_num=0, logger=self.logger, loopback=False
        )

    async def initialize(self) -> bool:
        if not await super().initialize():
            return False
        for task in TASKS:
            await self.tasks.put(task)
        return True

    async def fetch_tasks(self) -> None:
        try:
            task_id, task_data = await asyncio.wait_for(self.tasks.get(), timeout=1)
            await self.task_queue.put((task_id, task_data))
        except TimeoutError:
            pass

    async def process_task(
        self, task_id: int | str, task_data: dict[str, Any]
    ) -> dict[str, Any]:
        task_started = time.time_ns()
        elapsed: int = 0
        result = {"data": None}
        while elapsed < int(task_data.get("timeout", 10.0) * 1e9):
            if task_data.get("data") == "Read configuration":
                if configuration := await self.read_hash_complete(
                    f"scietex:configuration:{self.service_name}:{self.worker_id}"
                ):
                    result["data"] = {"type": "configuration", "payload": configuration}
                    break

            await asyncio.sleep(1.0)
            elapsed = task_started - time.time_ns()
        return result

    async def return_task_to_queue(
        self, task_id: int | str, task_data: dict[str, Any]
    ) -> None:
        """Return a task to queue."""
        await self.tasks.put((task_id, task_data))

    async def read_hash_complete(self, key: str) -> dict[str, Any]:
        if self.client:
            result = await self.client.hgetall(key)
            if result and isinstance(result, dict):
                if isinstance(next(iter(result)), bytes):
                    result = {k.decode(): v.decode() for k, v in result.items()}
                    return result
        return {}
