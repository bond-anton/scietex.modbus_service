"""Tests for the ``serial:list`` data-plane task handler."""

import logging
from unittest.mock import patch

import msgspec
import pytest
from scietex.hal.serial import SerialPortInfo
from scietex.service.task_handler import TaskCapabilities, TaskData, TaskHandlerContext

from scietex.modbus_service.task_handlers import (
    SERIAL_LIST_TASK_NAME,
    SerialListHandler,
    SerialListResponse,
)


def _make_handler() -> SerialListHandler:
    context = TaskHandlerContext(service_name="test", instance_id="inst", logger=logging.getLogger("test"))
    return SerialListHandler("serial-list", context)


def _make_capabilities() -> TaskCapabilities:
    async def _noop(_task_id, _value) -> None:
        return None

    from uuid import uuid4

    return TaskCapabilities(task_id=uuid4(), _write_progress=_noop)


def test_handler_declares_data_lane_and_task_name():
    handler = _make_handler()
    assert handler.supported_tasks == [SERIAL_LIST_TASK_NAME]
    assert SerialListHandler.control is False


@pytest.mark.asyncio
async def test_handle_returns_ports_as_json():
    ports = [
        SerialPortInfo(device="/dev/ttyUSB0", description="USB Serial"),
        SerialPortInfo(device="/dev/ttyS0", description=""),
    ]
    with patch(
        "scietex.modbus_service.task_handlers.serial_list.list_serial_ports",
        return_value=ports,
    ):
        result = await _make_handler().handle(
            TaskData(task_id="t1", task=SERIAL_LIST_TASK_NAME),
            capabilities=_make_capabilities(),
        )
    assert result.status == "success"
    decoded = msgspec.json.decode(result.payload, type=SerialListResponse)
    assert [(p.device, p.description) for p in decoded.ports] == [
        ("/dev/ttyUSB0", "USB Serial"),
        ("/dev/ttyS0", ""),
    ]


@pytest.mark.asyncio
async def test_handle_empty_list_is_success():
    with patch(
        "scietex.modbus_service.task_handlers.serial_list.list_serial_ports",
        return_value=[],
    ):
        result = await _make_handler().handle(
            TaskData(task_id="t2", task=SERIAL_LIST_TASK_NAME),
            capabilities=_make_capabilities(),
        )
    assert result.status == "success"
    decoded = msgspec.json.decode(result.payload, type=SerialListResponse)
    assert decoded.ports == []


@pytest.mark.asyncio
async def test_handle_enumeration_failure_is_error():
    with patch(
        "scietex.modbus_service.task_handlers.serial_list.list_serial_ports",
        side_effect=RuntimeError("boom"),
    ):
        result = await _make_handler().handle(
            TaskData(task_id="t3", task=SERIAL_LIST_TASK_NAME),
            capabilities=_make_capabilities(),
        )
    assert result.status == "error"
    assert result.error_code == "SERIAL_LIST_FAILED"
    assert result.retryable is False
