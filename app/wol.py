import socket
from typing import Optional


def _mac_to_bytes(mac: str) -> bytes:
    mac = mac.replace("-", ":").lower()
    parts = mac.split(":")
    if len(parts) != 6:
        raise ValueError("Invalid MAC address format")
    return bytes(int(p, 16) for p in parts)


def send_magic_packet(mac: str, broadcast_ip: Optional[str] = None, port: int = 9, repeats: int = 3, interval_ms: int = 120) -> None:
    mac_bytes = _mac_to_bytes(mac)
    payload = b"\xff" * 6 + mac_bytes * 16
    addr = (broadcast_ip or "255.255.255.255", port)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for _ in range(max(1, repeats)):
            s.sendto(payload, addr)
            if interval_ms > 0:
                try:
                    import time as _t
                    _t.sleep(interval_ms / 1000.0)
                except Exception:
                    pass
