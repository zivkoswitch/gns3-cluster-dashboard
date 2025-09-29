import os
import yaml
from typing import Any, Dict, List


def load_config(path: str | None = None) -> Dict[str, Any]:
    cfg_path = path or os.getenv("CONFIG_PATH", "config/devices.yaml")
    if not os.path.exists(cfg_path):
        return {"devices": []}
    with open(cfg_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    # Normalize
    devices: List[Dict[str, Any]] = []
    for idx, d in enumerate(data.get("devices", []) or []):
        devices.append({
            "id": str(idx),
            "name": d.get("name") or f"device-{idx}",
            "ip": d.get("ip"),
            "mac": (d.get("mac") or "").lower(),
            "broadcast": d.get("broadcast", ""),
            "gns3key": d.get("gns3key") or {},
            "ssh": d.get("ssh") or {},
        })
    return {"devices": devices}
