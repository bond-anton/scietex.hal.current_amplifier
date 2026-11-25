"""Modbus/TCP transport for the EBIC v1.0 preamp relay layer.

The board speaks Modbus RTU over RS485; this module reaches the same coils and
registers through a Modbus/TCP gateway that translates the requests. It supplies
only a transport: :class:`~.client._RelayRequests` builds every request and
validates every response, so this class is the request layer plus a connection.

The connection is opened lazily, on the first
:meth:`EBICModbusV1PreampTcp.execute` or on an explicit
:meth:`EBICModbusV1PreampTcp.connect`, because ``AsyncModbusTcpClient`` binds to
the running event loop in its constructor. A dropped link is reopened before the
next request. The client is constructed with ``retries`` unchanged from the
constructor argument: a retried write after an ambiguous drop is a duplicate
relay transition, so no retry loop is layered on top of pymodbus.

Exception responses from the gateway are mapped onto the exception hierarchy
that the serial path already uses, with two named gateway outcomes: code 11
(the gateway could not reach the device) becomes
:class:`~.exceptions.GatewayTargetFailed`, and code 6 (server device busy)
becomes :class:`~.exceptions.GatewayBusy`.

Classes:
    EBICModbusV1PreampTcp: The EBIC v1.0 relay driver over Modbus/TCP.
"""

from logging import Logger, getLogger
from typing import ClassVar

from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ConnectionException, ModbusIOException
from pymodbus.pdu import ExceptionResponse, ModbusPDU
from scietex.hal.serial import ModbusOperationError

from .....base import (
    AmplifierState,
    CurrentAmplifierCapabilities,
    CurrentAmplifierProtocol,
    IndicationCapabilities,
    OutputVoltageCapabilities,
    PreampCapabilities,
)
from .client import _RelayRequests
from .constants import DEFAULT_SLAVE_ADDRESS
from .exceptions import (
    GATEWAY_BUSY,
    GATEWAY_TARGET_FAILED,
    GatewayBusy,
    GatewayTargetFailed,
)


class EBICModbusV1PreampTcp(_RelayRequests, CurrentAmplifierProtocol):
    """Modbus/TCP client for the EBIC v1.0 relay outputs behind a gateway.

    The relay and register surface comes from :class:`_RelayRequests`; this
    class owns one TCP connection to the gateway and addresses the device by its
    Modbus address, which the gateway routes to the RS485 bus.

    Attributes:
        capabilities: The static analog geometry the board fixes: the pre-amp
            clip point, the booster linear range and the physical Overcurrent
            comparator. No selectable control is declared here, because this
            class drives coils rather than functions; the semantic layer owns the
            relay map and declares the selectable groups.
    """

    # Same geometry as the serial driver: this transport changes how a request
    # reaches the board, not what the board can do.
    capabilities: ClassVar[CurrentAmplifierCapabilities] = CurrentAmplifierCapabilities(
        preamp=PreampCapabilities(max_output_v=5.0),
        output_voltage=OutputVoltageCapabilities(min_v=-10.0, max_v=10.0),
        input_overcurrent=IndicationCapabilities(present=True, read=False),
    )

    def __init__(  # noqa: PLR0913, PLR0917
        self,
        host: str,
        port: int = 502,
        address: int = DEFAULT_SLAVE_ADDRESS,
        label: str = "",
        timeout: float = 6.0,
        retries: int = 0,
        logger: Logger | None = None,
    ) -> None:
        """
        Initialize the client.

        Args:
            host: Gateway host name or address.
            port: Gateway TCP port.
            address: Modbus address the gateway routes to the device.
            label: Human-readable label prefixed to error messages. Empty by
                default; the semantic layer supplies one.
            timeout: Per-request timeout in seconds.
            retries: Retries pymodbus performs per request. The default of zero
                keeps an ambiguous write from being sent twice.
            logger: Optional logger for transport diagnostics.
        """
        self.address = address
        self.label = label
        self.logger = logger if logger is not None else getLogger()
        self._host = host
        self._port = port
        self._timeout = timeout
        self._retries = retries
        # `AsyncModbusTcpClient` binds to the running event loop in its
        # constructor, so it cannot be built here: the client is created in
        # `connect()`, which always runs inside the loop.
        self._client: AsyncModbusTcpClient | None = None

    async def connect(self) -> bool:
        """
        Open the TCP connection to the gateway.

        Creating the client is lazy and the call is idempotent: an already
        connected client short-circuits, and pymodbus is never asked for a
        second transport on top of a live one.

        Returns:
            bool: ``True`` once the connection is open.

        Raises:
            ModbusOperationError: If the gateway is unreachable. pymodbus
                reports a failed connect by returning ``False`` rather than
                raising, so the result is checked here; otherwise a caller would
                treat an unreachable gateway as connected and only fail later,
                on the first request.
        """
        if self._client is not None and self._client.connected:
            return True
        self.logger.debug(
            "%sConnecting to Modbus/TCP gateway %s:%s.",
            self._prefix,
            self._host,
            self._port,
        )
        if self._client is None:
            self._client = AsyncModbusTcpClient(
                self._host,
                port=self._port,
                timeout=self._timeout,
                retries=self._retries,
            )
        if not await self._client.connect():
            raise ModbusOperationError(
                f"{self._prefix}failed to connect to Modbus/TCP gateway at "
                f"{self._host}:{self._port}"
            )
        return True

    async def close(self) -> None:
        """Close the TCP connection and drop the client."""
        if self._client is not None:
            self._client.close()
            self._client = None

    async def execute(
        self,
        request: ModbusPDU,
        no_response_expected: bool = False,
        raise_on_error: bool = True,
    ) -> ModbusPDU | None:
        """
        Send one request to the gateway and return its response.

        The connection is opened or reopened first, so call sites never manage
        it. The response contract matches
        :meth:`scietex.hal.serial.RS485Client.execute`: ``None`` when no
        response is expected or when an error is swallowed, otherwise the PDU.

        Args:
            request: The request to send.
            no_response_expected: Send the request without waiting for a reply.
            raise_on_error: Raise on a transport failure or an exception
                response instead of returning ``None``. Pass ``False`` to keep
                the error-swallowing behaviour.

        Returns:
            ModbusPDU | None: The response, or ``None`` when none was read.

        Raises:
            GatewayBusy: If the gateway or the device reports that it is busy
                (exception code 6). The request may succeed shortly.
            GatewayTargetFailed: If the gateway reports that it could not reach
                the addressed device (exception code 11).
            ModbusOperationError: If the connection fails, pymodbus raises a
                connection or I/O error, or the device returns another
                exception response.
        """
        # The request layer stamps the address on every PDU it builds, but this
        # method is public: a caller-built request keeps pymodbus's default
        # (0) unless the transport attaches the configured address here.
        request.dev_id = self.address
        if self._client is None or not self._client.connected:
            try:
                await self.connect()
            except ModbusOperationError:
                if no_response_expected or not raise_on_error:
                    return None
                raise
        try:
            response = await self._require_client().execute(
                no_response_expected, request
            )
        except (ConnectionException, ModbusIOException) as exc:
            if no_response_expected or not raise_on_error:
                return None
            raise ModbusOperationError(
                f"{self._prefix}Modbus/TCP request to {self._host}:{self._port} "
                f"failed: {exc}"
            ) from exc
        if no_response_expected:
            return None
        if isinstance(response, ExceptionResponse):
            if not raise_on_error:
                return None
            if response.exception_code == GATEWAY_TARGET_FAILED:
                raise GatewayTargetFailed(
                    f"{self._prefix}gateway at {self._host}:{self._port} could "
                    f"not reach device {self.address}: exception code "
                    f"{response.exception_code}"
                )
            if response.exception_code == GATEWAY_BUSY:
                raise GatewayBusy(
                    f"{self._prefix}gateway at {self._host}:{self._port} "
                    f"reported device {self.address} busy: exception code "
                    f"{response.exception_code}"
                )
            raise ModbusOperationError(
                f"{self._prefix}device {self.address} returned exception code "
                f"{response.exception_code}"
            )
        return response

    async def read_data(self) -> AmplifierState:
        """
        Return an empty snapshot.

        The EBIC v1.0 firmware reports no output voltage, current, gain, bias,
        bandwidth, filter or status value, so every field stays ``None`` and the
        filter tuple stays empty. Relay levels are read through
        :meth:`~.client._RelayRequests.read_relays` instead.

        Returns:
            AmplifierState: A snapshot with every field unset.
        """
        return AmplifierState()

    def _require_client(self) -> AsyncModbusTcpClient:
        """
        Return the connected client.

        ``connect()`` always constructs one, so the guard only makes the
        invariant explicit for type checkers and for a future transport that
        stops constructing eagerly.

        Raises:
            RuntimeError: If no client exists.
        """
        if self._client is None:
            raise RuntimeError(
                "Modbus/TCP client is not connected; call connect() first"
            )
        return self._client

    @property
    def _prefix(self) -> str:
        """Return the label with its separator, or nothing when unlabeled."""
        return f"{self.label}: " if self.label else ""
