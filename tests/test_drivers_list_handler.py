"""Tests for the ``drivers:list`` control-plane task handler."""

import logging
from unittest.mock import patch
from uuid import uuid4

import msgspec
import pytest
from scietex.hal.serial.gateway.drivers import ModbusDriver
from scietex.service.task_handler import TaskCapabilities, TaskData, TaskHandlerContext

from scietex.modbus_service.task_handlers import (
    DRIVERS_LIST_TASK_NAME,
    DriverAvailability,
    DriversListHandler,
    DriversListResponse,
)


def _make_handler() -> DriversListHandler:
    context = TaskHandlerContext(service_name="test", instance_id="inst", logger=logging.getLogger("test"))
    return DriversListHandler("drivers-list", context)


def _make_capabilities() -> TaskCapabilities:
    async def _noop(_task_id, _value) -> None:
        return None

    return TaskCapabilities(task_id=uuid4(), _write_progress=_noop)


def _driver(name: str) -> ModbusDriver:
    return ModbusDriver(
        name=name,
        label=name.title(),
        description="",
        device_type="Vacuum Gauge",
        framer="RTU",
        decoder=None,
        pdus=[],
        translator=None,
    )


def test_handler_declares_control_lane_and_task_name():
    handler = _make_handler()
    assert handler.supported_tasks == [DRIVERS_LIST_TASK_NAME]
    assert DriversListHandler.control is True


@pytest.mark.asyncio
async def test_handle_reports_every_driver_with_availability():
    drivers = {"alpha": _driver("alpha"), "beta": _driver("beta")}

    def _verify(driver: ModbusDriver) -> str | None:
        return None if driver.name == "alpha" else "framer 'x': boom"

    with (
        patch(
            "scietex.modbus_service.task_handlers.drivers_list.discover_drivers",
            return_value=drivers,
        ),
        patch(
            "scietex.modbus_service.task_handlers.drivers_list.verify_driver",
            side_effect=_verify,
        ),
    ):
        result = await _make_handler().handle(
            TaskData(task_id="t1", task=DRIVERS_LIST_TASK_NAME),
            capabilities=_make_capabilities(),
        )

    assert result.status == "success"
    decoded = msgspec.json.decode(result.payload, type=DriversListResponse)
    assert [(d.name, d.available, d.reason) for d in decoded.drivers] == [
        ("alpha", True, ""),
        ("beta", False, "framer 'x': boom"),
    ]


@pytest.mark.asyncio
async def test_handle_empty_catalogue_is_success():
    with patch(
        "scietex.modbus_service.task_handlers.drivers_list.discover_drivers",
        return_value={},
    ):
        result = await _make_handler().handle(
            TaskData(task_id="t2", task=DRIVERS_LIST_TASK_NAME),
            capabilities=_make_capabilities(),
        )

    assert result.status == "success"
    decoded = msgspec.json.decode(result.payload, type=DriversListResponse)
    assert decoded.drivers == []


@pytest.mark.asyncio
async def test_handle_discovery_failure_is_error():
    with patch(
        "scietex.modbus_service.task_handlers.drivers_list.discover_drivers",
        side_effect=RuntimeError("boom"),
    ):
        result = await _make_handler().handle(
            TaskData(task_id="t3", task=DRIVERS_LIST_TASK_NAME),
            capabilities=_make_capabilities(),
        )

    assert result.status == "error"
    assert result.error_code == "DRIVERS_LIST_FAILED"
    assert result.retryable is False


def test_availability_struct_defaults_to_available():
    entry = DriverAvailability(name="alpha")
    assert entry.available is True
    assert entry.reason == ""
