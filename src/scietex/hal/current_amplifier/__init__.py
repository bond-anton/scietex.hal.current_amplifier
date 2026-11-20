"""Scietex current amplifier HAL package.

A ``CurrentAmplifier`` converts a photodiode or ion-collector current into a
voltage: the driver layer exposes its capability set, its state snapshot, and
the transport-agnostic control contract that concrete protocols implement.
"""

from .version import __version__

__all__ = ["__version__"]
