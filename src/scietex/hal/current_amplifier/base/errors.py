"""Errors shared by current amplifier drivers.

These failures are transport-independent: they describe a driver that cannot
answer for a register or a response that cannot belong to its request, not a bus
that failed. Transport failures themselves are raised by
`scietex.hal.serial` and are allowed to propagate unchanged.

Classes:
    RegisterMapIncomplete: A register needed by the operation is not mapped.
    UnexpectedResponse: A response cannot belong to the register it answers.
"""


class RegisterMapIncomplete(RuntimeError):
    """Raised when a register the operation needs has no map entry.

    Args:
        register: The register the operation needs, by its map name.
        detail: What the map lacks; defaults to the address and function code.

    Attributes:
        register (str): The register name the message names.
    """

    def __init__(
        self,
        register: str,
        detail: str = "has no address and function code",
    ) -> None:
        self.register = register
        super().__init__(f"{register} {detail}")


class UnexpectedResponse(OSError):
    """Raised when a response cannot belong to the register it answers.

    Args:
        register: The register name the response was read for.
        detail: What is wrong with the response, such as its length or unit id.

    Attributes:
        register (str): The register name the message names.
    """

    def __init__(self, register: str, detail: str) -> None:
        self.register = register
        super().__init__(f"Unexpected response for {register}: {detail}")
