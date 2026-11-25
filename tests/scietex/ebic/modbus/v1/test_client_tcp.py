"""Tests for the EBIC v1.0 Modbus/TCP transport.

``AsyncModbusTcpClient`` is replaced by a fake, so these cover the connection
lifecycle and the error mapping rather than a socket. The request layer itself
is exercised by the RTU tests, which share it unchanged.
"""

import asyncio

import pytest
from pymodbus.exceptions import ConnectionException, ModbusIOException
from pymodbus.pdu import ExceptionResponse
from pymodbus.pdu.bit_message import (
    ReadCoilsRequest,
    ReadCoilsResponse,
    WriteSingleCoilRequest,
    WriteSingleCoilResponse,
)
from scietex.hal.serial import ModbusOperationError

try:
    from src.scietex.hal.current_amplifier.base import AmplifierState
    from src.scietex.hal.current_amplifier.registry import resolve_driver
    from src.scietex.hal.current_amplifier.scietex.ebic.modbus.v1 import (
        EBICModbusV1PreampTcp,
        EBICModbusV1TcpAmplifier,
        GatewayBusy,
        GatewayTargetFailed,
        client_tcp,
    )
    from src.scietex.hal.current_amplifier.scietex.ebic.modbus.v1.constants import (
        DEFAULT_SLAVE_ADDRESS,
        RELAY_COUNT,
    )
except ModuleNotFoundError:
    from scietex.hal.current_amplifier.base import AmplifierState
    from scietex.hal.current_amplifier.registry import resolve_driver
    from scietex.hal.current_amplifier.scietex.ebic.modbus.v1 import (
        EBICModbusV1PreampTcp,
        EBICModbusV1TcpAmplifier,
        GatewayBusy,
        GatewayTargetFailed,
        client_tcp,
    )
    from scietex.hal.current_amplifier.scietex.ebic.modbus.v1.constants import (
        DEFAULT_SLAVE_ADDRESS,
        RELAY_COUNT,
    )


class _FakeTcpClient:
    """Stand-in for ``AsyncModbusTcpClient`` that records every call."""

    connect_result: bool = True
    next_responses: list[object] = []

    def __init__(
        self,
        host: str,
        *,
        port: int = 502,
        timeout: float = 3.0,
        retries: int = 3,
        name: str = "comm",
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.retries = retries
        self.name = name
        self.connected = False
        self.connect_calls = 0
        self.closed = False
        self.requests: list[tuple[bool, object]] = []
        self.responses = list(self.next_responses)
        self.error: Exception | None = None

    async def connect(self) -> bool:
        self.connect_calls += 1
        self.connected = self.connect_result
        return self.connect_result

    def close(self) -> None:
        self.closed = True
        self.connected = False

    async def execute(self, no_response_expected: bool, request):
        self.requests.append((no_response_expected, request))
        if self.error is not None:
            raise self.error
        if no_response_expected:
            return None
        return self.responses.pop(0)


@pytest.fixture
def fake_tcp(monkeypatch):
    """Replace the pymodbus TCP client constructor for one test."""
    instances: list[_FakeTcpClient] = []

    class FakeTcpClient(_FakeTcpClient):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            instances.append(self)

    FakeTcpClient.instances = instances
    monkeypatch.setattr(client_tcp, "AsyncModbusTcpClient", FakeTcpClient)
    return FakeTcpClient


def _run_with(driver: EBICModbusV1PreampTcp, scenario) -> None:
    """Run one scenario against ``driver`` inside a live event loop."""

    async def main() -> None:
        try:
            await scenario(driver)
        finally:
            await driver.close()

    asyncio.run(main())


def _run(scenario) -> None:
    """Run one scenario against a driver with default constructor arguments."""
    _run_with(
        EBICModbusV1PreampTcp("gateway.local", address=DEFAULT_SLAVE_ADDRESS),
        scenario,
    )


def _relay_response(levels: list[bool]) -> ReadCoilsResponse:
    padding = [False] * (RELAY_COUNT - len(levels))
    return ReadCoilsResponse(bits=[*levels, *padding])


# -- connection lifecycle --------------------------------------------------


def test_constructor_does_not_create_a_client(fake_tcp):
    """The client binds to the loop, so it is built only inside connect()."""
    driver = EBICModbusV1PreampTcp("gateway.local")

    assert fake_tcp.instances == []
    assert driver._client is None
    assert driver.label == ""
    assert driver.address == DEFAULT_SLAVE_ADDRESS


def test_connect_forwards_the_client_arguments(fake_tcp):
    """connect() constructs the client with the configured parameters."""
    levels = [index % 2 == 0 for index in range(RELAY_COUNT)]
    driver = EBICModbusV1PreampTcp("gateway.local", port=1502, timeout=2.5, retries=0)

    async def scenario(driver) -> None:
        assert fake_tcp.instances == []

        await driver.connect()
        client = fake_tcp.instances[0]
        assert (client.host, client.port) == ("gateway.local", 1502)
        assert (client.timeout, client.retries) == (2.5, 0)

        client.responses.append(_relay_response(levels))
        assert await driver.read_relays() == tuple(levels)

        request = client.requests[0][1]
        assert isinstance(request, ReadCoilsRequest)
        assert request.address == 0
        assert request.count == RELAY_COUNT
        assert request.dev_id == DEFAULT_SLAVE_ADDRESS

    _run_with(driver, scenario)


def test_execute_connects_on_first_request_without_an_explicit_connect(fake_tcp):
    """The relay accessor opens the transport itself."""
    fake_tcp.next_responses = [_relay_response([False] * RELAY_COUNT)]

    async def scenario(driver) -> None:
        assert fake_tcp.instances == []

        assert await driver.read_relays() == (False,) * RELAY_COUNT

        assert len(fake_tcp.instances) == 1
        assert fake_tcp.instances[0].connect_calls == 1

    _run(scenario)


def test_connect_is_idempotent(fake_tcp):
    """A second connect reuses the live transport instead of replacing it."""

    async def scenario(driver) -> None:
        assert await driver.connect() is True
        assert await driver.connect() is True

        assert len(fake_tcp.instances) == 1
        assert fake_tcp.instances[0].connect_calls == 1

    _run(scenario)


def test_execute_reconnects_a_dropped_link(fake_tcp):
    """A client that reports itself disconnected is reconnected in place."""
    levels = [False] * RELAY_COUNT

    async def scenario(driver) -> None:
        await driver.connect()
        client = fake_tcp.instances[0]
        client.connected = False
        client.responses.append(_relay_response(levels))

        assert await driver.read_relays() == tuple(levels)
        assert client.connect_calls == 2
        assert len(fake_tcp.instances) == 1

    _run(scenario)


def test_close_drops_the_client_and_execute_rebuilds_it(fake_tcp):
    """close() releases the transport; the next connect builds a new client."""

    async def scenario(driver) -> None:
        await driver.connect()
        first = fake_tcp.instances[0]

        await driver.close()
        assert first.closed is True
        assert driver._client is None

        await driver.connect()
        assert len(fake_tcp.instances) == 2
        assert fake_tcp.instances[1] is not first

    _run(scenario)


def test_connect_failure_raises_modbus_operation_error(fake_tcp):
    """pymodbus reports a refused connection as False, which must become an error."""
    fake_tcp.connect_result = False

    async def scenario(driver) -> None:
        with pytest.raises(ModbusOperationError, match="failed to connect"):
            await driver.connect()

    _run(scenario)


def test_connect_failure_is_swallowed_when_errors_are_disabled(fake_tcp):
    """A failed lazy connect returns None when raise_on_error is False."""
    fake_tcp.connect_result = False

    async def scenario(driver) -> None:
        request = WriteSingleCoilRequest(
            address=0, bits=[True], dev_id=DEFAULT_SLAVE_ADDRESS
        )
        assert await driver.execute(request, raise_on_error=False) is None

    _run(scenario)


def test_connect_failure_raises_from_execute(fake_tcp):
    """A failed lazy connect surfaces as the shared operation error."""
    fake_tcp.connect_result = False

    async def scenario(driver) -> None:
        with pytest.raises(ModbusOperationError, match="failed to connect"):
            await driver.read_relays()

    _run(scenario)


# -- unit id on the wire ---------------------------------------------------


def test_read_request_carries_the_configured_unit_id(fake_tcp):
    """A coil read reaches the gateway addressed to the configured device."""
    driver = EBICModbusV1PreampTcp("gateway.local", address=7)
    fake_tcp.next_responses = [_relay_response([False] * RELAY_COUNT)]

    async def scenario(driver) -> None:
        await driver.read_relays()

        request = fake_tcp.instances[0].requests[0][1]
        assert isinstance(request, ReadCoilsRequest)
        assert request.dev_id == 7

    _run_with(driver, scenario)


def test_write_request_carries_the_configured_unit_id(fake_tcp):
    """A coil write reaches the gateway addressed to the configured device."""
    driver = EBICModbusV1PreampTcp("gateway.local", address=7)
    fake_tcp.next_responses = [WriteSingleCoilResponse(address=3, bits=[True])]

    async def scenario(driver) -> None:
        await driver.set_relay(3, True)

        request = fake_tcp.instances[0].requests[0][1]
        assert isinstance(request, WriteSingleCoilRequest)
        assert request.dev_id == 7

    _run_with(driver, scenario)


def test_execute_stamps_the_configured_unit_id_on_a_bare_request(fake_tcp):
    """execute() addresses a caller-built request that carries no unit id."""
    driver = EBICModbusV1PreampTcp("gateway.local", address=7)
    fake_tcp.next_responses = [_relay_response([False] * RELAY_COUNT)]
    request = ReadCoilsRequest(address=0, count=RELAY_COUNT)
    # pymodbus defaults dev_id to 0, so this asserts the stamp, not the builder.
    assert request.dev_id == 0

    async def scenario(driver) -> None:
        await driver.execute(request)

        forwarded = fake_tcp.instances[0].requests[0][1]
        assert forwarded is request
        assert forwarded.dev_id == 7

    _run_with(driver, scenario)


# -- error mapping ---------------------------------------------------------


def _write_coil() -> WriteSingleCoilRequest:
    return WriteSingleCoilRequest(address=0, bits=[True], dev_id=DEFAULT_SLAVE_ADDRESS)


def test_exception_code_eleven_raises_gateway_target_failed(fake_tcp):
    """Code 11 means the gateway reached the bus but not the device."""

    async def scenario(driver) -> None:
        await driver.connect()
        fake_tcp.instances[0].responses.append(
            ExceptionResponse(0x05, exception_code=0x0B)
        )

        with pytest.raises(GatewayTargetFailed) as excinfo:
            await driver.set_relay(0, True)

        assert isinstance(excinfo.value, ModbusOperationError)
        assert "exception code 11" in str(excinfo.value)

    _run(scenario)


def test_other_exception_codes_raise_a_plain_operation_error(fake_tcp):
    """A rejected request is not a gateway target failure."""

    async def scenario(driver) -> None:
        await driver.connect()
        fake_tcp.instances[0].responses.append(
            ExceptionResponse(0x05, exception_code=0x02)
        )

        with pytest.raises(ModbusOperationError) as excinfo:
            await driver.set_relay(0, True)

        assert not isinstance(excinfo.value, GatewayTargetFailed)
        assert "exception code 2" in str(excinfo.value)

    _run(scenario)


def test_exception_code_six_raises_gateway_busy(fake_tcp):
    """Code 6 is a retryable contention signal, not a dead board."""

    async def scenario(driver) -> None:
        await driver.connect()
        fake_tcp.instances[0].responses.append(
            ExceptionResponse(0x05, exception_code=0x06)
        )

        with pytest.raises(GatewayBusy) as excinfo:
            await driver.set_relay(0, True)

        assert isinstance(excinfo.value, ModbusOperationError)
        assert not isinstance(excinfo.value, GatewayTargetFailed)
        assert "exception code 6" in str(excinfo.value)

    _run(scenario)


def test_gateway_busy_is_distinct_from_gateway_target_failed():
    """A busy gateway must not be classified as an unreachable board."""
    assert issubclass(GatewayBusy, ModbusOperationError)
    assert not issubclass(GatewayBusy, GatewayTargetFailed)
    assert not issubclass(GatewayTargetFailed, GatewayBusy)


@pytest.mark.parametrize(
    "error",
    [ConnectionException("link lost"), ModbusIOException("no response")],
)
def test_pymodbus_transport_errors_raise_modbus_operation_error(fake_tcp, error):
    """Both transport failure classes map onto the shared error."""

    async def scenario(driver) -> None:
        await driver.connect()
        fake_tcp.instances[0].error = error

        with pytest.raises(ModbusOperationError) as excinfo:
            await driver.execute(_write_coil())

        assert not isinstance(excinfo.value, GatewayTargetFailed)
        assert str(error) in str(excinfo.value)

    _run(scenario)


@pytest.mark.parametrize(
    "outcome",
    [
        ExceptionResponse(0x05, exception_code=0x0B),
        ExceptionResponse(0x05, exception_code=0x06),
        ExceptionResponse(0x05, exception_code=0x02),
        ConnectionException("link lost"),
        ModbusIOException("no response"),
    ],
)
def test_raise_on_error_false_returns_none(fake_tcp, outcome):
    """Every error path honours the serial client's error-swallowing flag."""

    async def scenario(driver) -> None:
        await driver.connect()
        client = fake_tcp.instances[0]
        if isinstance(outcome, Exception):
            client.error = outcome
        else:
            client.responses.append(outcome)

        assert await driver.execute(_write_coil(), raise_on_error=False) is None

    _run(scenario)


def test_no_response_expected_returns_none_without_reading(fake_tcp):
    """The gateway is told not to reply, so no response is parsed."""

    async def scenario(driver) -> None:
        await driver.connect()
        client = fake_tcp.instances[0]
        request = _write_coil()

        assert await driver.execute(request, no_response_expected=True) is None
        assert client.requests == [(True, request)]
        assert client.responses == []

    _run(scenario)


# -- snapshot and semantic layer -------------------------------------------


def test_read_data_returns_an_empty_snapshot_without_a_request(fake_tcp):
    """The firmware reports no amplifier value, and no request is needed."""

    async def scenario(driver) -> None:
        assert await driver.read_data() == AmplifierState()
        assert fake_tcp.instances == []

    _run(scenario)


def test_semantic_subclass_injects_the_tcp_preamp(fake_tcp):
    """The TCP semantic driver drives the TCP relay transport."""
    amplifier = EBICModbusV1TcpAmplifier(
        "gateway.local",
        port=1502,
        address=3,
        label="TCP Preamp",
        timeout=1.5,
        retries=0,
    )

    assert isinstance(amplifier.relays, EBICModbusV1PreampTcp)
    assert amplifier.relays.address == 3
    assert amplifier.relays.label == "TCP Preamp"
    assert (amplifier.relays._host, amplifier.relays._port) == ("gateway.local", 1502)
    assert (amplifier.relays._timeout, amplifier.relays._retries) == (1.5, 0)


# -- entry points ----------------------------------------------------------


def test_tcp_entry_points_resolve():
    """Both TCP classes are advertised under the driver entry point group."""
    preamp = resolve_driver("ebic_modbus_tcp_v1_preamp")
    amplifier = resolve_driver("ebic_modbus_tcp_v1")

    assert preamp.__qualname__ == "EBICModbusV1PreampTcp"
    assert preamp.__module__.endswith("scietex.ebic.modbus.v1.client_tcp")
    assert amplifier.__qualname__ == "EBICModbusV1TcpAmplifier"
    assert amplifier.__module__.endswith("scietex.ebic.modbus.v1.semantic")
