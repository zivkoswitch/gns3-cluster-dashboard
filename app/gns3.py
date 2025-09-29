import shutil
import subprocess
from typing import Dict


def check_gns3() -> Dict[str, str | bool]:
    bins = ["gns3", "gns3server", "gns3-gui"]
    found: dict[str, bool] = {b: shutil.which(b) is not None for b in bins}
    versions: dict[str, str] = {}
    for b, ok in found.items():
        if not ok:
            continue
        try:
            out = subprocess.check_output([b, "--version"], stderr=subprocess.STDOUT, timeout=2)
            versions[b] = out.decode(errors="ignore").strip().splitlines()[0]
        except Exception:
            versions[b] = "installed (version unknown)"
    installed = any(found.values())
    return {"installed": installed, "found": found, "versions": versions}

