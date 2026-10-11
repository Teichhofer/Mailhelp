"""The PC's address in the local network, for links that open on a phone."""

from __future__ import annotations

import ipaddress
import socket

# A documentation address (RFC 5737): connecting a UDP socket only selects the
# outgoing interface; no packet is sent.
_PROBE = ("192.0.2.1", 80)


def lan_ip() -> str | None:
    """The private IPv4 address of the interface used for outgoing traffic, or None."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(_PROBE)
            address = probe.getsockname()[0]
    except OSError:
        return None
    return address if is_lan_address(address) else None


def is_lan_address(value: str) -> bool:
    """A private, non-loopback IPv4 address such as 192.168.1.20."""
    try:
        address = ipaddress.IPv4Address(value)
    except ValueError:
        return False
    return address.is_private and not address.is_loopback and not address.is_link_local


def lan_host(host: str, port: int) -> bool:
    """Whether a Host header names a LAN address of this service, e.g. 192.168.1.20:8765.

    An IP literal cannot be re-pointed by DNS, so accepting it does not weaken the
    protection against DNS rebinding.
    """
    address, separator, given_port = host.rpartition(":")
    return separator == ":" and given_port == str(port) and is_lan_address(address)


__all__ = ["is_lan_address", "lan_host", "lan_ip"]
