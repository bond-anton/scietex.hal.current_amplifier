"""Tests for the driver entry point registry."""

import re

import pytest

try:
    from src.scietex.hal.current_amplifier.registry import (
        ENTRY_POINT_GROUP,
        discover_drivers,
        resolve_driver,
    )
    from src.scietex.hal.current_amplifier.scietex.ebic.modbus.v1 import (
        EBICModbusV1Preamp,
    )
except ModuleNotFoundError:
    from scietex.hal.current_amplifier.registry import (
        ENTRY_POINT_GROUP,
        discover_drivers,
        resolve_driver,
    )
    from scietex.hal.current_amplifier.scietex.ebic.modbus.v1 import (
        EBICModbusV1Preamp,
    )


def test_entry_point_group_name():
    """The group name is the documented constant."""
    assert ENTRY_POINT_GROUP == "scietex.hal.current_amplifier.drivers"


def test_discover_drivers_lists_the_ebic_preamp():
    """The EBIC v1.0 relay driver is advertised under its entry point name."""
    drivers = discover_drivers()

    assert set(drivers) == {"ebic_modbus_v1_preamp"}
    # The entry point loads the installed package while the test may import
    # the same module through ``src``; compare the qualified name, not identity.
    assert drivers["ebic_modbus_v1_preamp"].__qualname__ == (
        EBICModbusV1Preamp.__qualname__
    )
    assert drivers["ebic_modbus_v1_preamp"].__module__.endswith(
        "scietex.ebic.modbus.v1.client"
    )


def test_resolve_driver_loads_the_ebic_preamp():
    """Resolving the advertised name returns the driver class."""
    driver = resolve_driver("ebic_modbus_v1_preamp")

    assert driver.__qualname__ == EBICModbusV1Preamp.__qualname__
    assert driver.__module__.endswith("scietex.ebic.modbus.v1.client")


def test_resolve_unknown_driver_raises_with_available_names():
    """An unadvertised name raises ``ValueError`` and lists what is available."""
    with pytest.raises(
        ValueError,
        match=re.escape("Unknown current amplifier driver 'nope'"),
    ) as excinfo:
        resolve_driver("nope")

    message = str(excinfo.value)
    assert "scietex.hal.current_amplifier.drivers" in message
    assert "available: ebic_modbus_v1_preamp" in message
