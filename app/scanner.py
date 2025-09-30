import os
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class DeviceState:
    id: str
    name: str
    ip: str
    mac: str = ""
    broadcast: str = ""
    up: bool = False
    hostname: str = ""
    last_seen: Optional[float] = None
    last_checked: Optional[float] = None
    gns3_active: bool = False
    gns3_port: Optional[int] = None
    gns3_url: str = ""
    gns3_api_ok: bool = False
    gns3_projects_open: int = 0
    gns3_cpu_percent: Optional[float] = None
    gns3_mem_percent: Optional[float] = None
    # SSH metrics
    ssh_ok: bool = False
    ssh_users_active: Optional[int] = None
    ssh_cpu_percent: Optional[float] = None
    ssh_mem_percent: Optional[float] = None
    ssh_disk_percent: Optional[float] = None
    ips: List[str] = field(default_factory=list)


class NetworkScanner:
    def __init__(self, devices: List[Dict[str, str]], interval: int = 30):
        self.interval = max(5, int(interval))
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._state: Dict[str, DeviceState] = {}
        for d in devices:
            self._state[d["id"]] = DeviceState(
                id=d["id"], name=d["name"], ip=d["ip"], mac=d.get("mac", ""), broadcast=d.get("broadcast", "")
            )
        # Preserve original device dictionaries for auth details
        self._devices_cfg = {d["id"]: d for d in devices}

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="scanner", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def snapshot(self) -> List[Dict[str, object]]:
        with self._lock:
            return [vars(v).copy() for v in self._state.values()]

    def get(self, dev_id: str) -> Optional[DeviceState]:
        with self._lock:
            return self._state.get(dev_id)

    def scan_now(self) -> None:
        # Run one scan cycle synchronously
        self._scan_once()

    def _run(self):
        while not self._stop.is_set():
            self._scan_once()
            self._stop.wait(self.interval)

    def _scan_once(self):
        for dev in list(self._state.values()):
            try:
                up = self._ping(dev.ip)
                hostname = ""
                mac = dev.mac
                gns3_active = False
                gns3_port: Optional[int] = None
                gns3_url = ""
                if up:
                    hostname = self._reverse_dns(dev.ip)
                # Try to resolve MAC even if host seems down (ARP cache may still have it)
                mac = mac or self._get_mac(dev.ip)
                # Probe GNS3 ports regardless of ICMP ping result (ping may be blocked)
                gns3_port = self._check_gns3_ports(dev.ip)
                if gns3_port:
                    gns3_active = True
                    scheme = "https" if gns3_port in (443, 3443) else "http"
                    gns3_url = f"{scheme}://{dev.ip}:{gns3_port}"

                # GNS3 API (if credentials configured)
                api_ok = False
                projects_open = 0
                cpu_p = None
                mem_p = None
                cfg = self._devices_cfg.get(dev.id, {})
                gkey = cfg.get("gns3key") or {}
                if gkey and gkey.get("server_url") and gkey.get("access_token"):
                    try:
                        api_ok, projects_open, cpu_p, mem_p = self._query_gns3_api(gkey)
                        # prefer configured URL for link
                        gns3_url = gkey.get("server_url") or gns3_url
                        gns3_active = gns3_active or api_ok
                    except Exception:
                        pass

                # SSH metrics (users, CPU, RAM, disk)
                ssh_ok = False
                ssh_users = None
                ssh_cpu = None
                ssh_mem = None
                ssh_disk = None
                ssh_ips: List[str] = []
                ssh_conf = cfg.get("ssh") or {}
                if ssh_conf and ssh_conf.get("username") and ssh_conf.get("password"):
                    try:
                        ssh_ok, ssh_users, ssh_cpu, ssh_mem, ssh_disk, ssh_ips = self._ssh_fetch_metrics(dev.ip, ssh_conf)
                    except Exception:
                        pass
                now = time.time()
                with self._lock:
                    cur = self._state.get(dev.id)
                    if not cur:
                        continue
                    cur.up = up
                    cur.hostname = hostname
                    if mac:
                        cur.mac = mac
                    cur.last_checked = now
                    if up:
                        cur.last_seen = now
                    cur.gns3_active = gns3_active
                    cur.gns3_port = gns3_port
                    cur.gns3_url = gns3_url
                    cur.gns3_api_ok = api_ok
                    cur.gns3_projects_open = projects_open
                    cur.gns3_cpu_percent = cpu_p
                    cur.gns3_mem_percent = mem_p
                    cur.ssh_ok = ssh_ok
                    cur.ssh_users_active = ssh_users
                    cur.ssh_cpu_percent = ssh_cpu
                    cur.ssh_mem_percent = ssh_mem
                    cur.ssh_disk_percent = ssh_disk
                    # IPs: prefer SSH-discovered addresses, else ensure configured IP present
                    ips_list: List[str] = []
                    if ssh_ips:
                        ips_list = ssh_ips[:]
                    if dev.ip and dev.ip not in ips_list:
                        ips_list.insert(0, dev.ip)
                    cur.ips = ips_list
            except Exception:
                # ignore per-device failures to keep scanning
                pass

    @staticmethod
    def _ping(ip: str) -> bool:
        # Use a quick, cross-compatible ping (Linux-compatible) inside Docker
        cmd = ["ping", "-c", "1", "-w", "1", ip]
        try:
            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            return res.returncode == 0
        except Exception:
            return False

    @staticmethod
    def _reverse_dns(ip: str) -> str:
        try:
            name, _, _ = socket.gethostbyaddr(ip)
            return name
        except Exception:
            return ""

    @staticmethod
    def _get_mac(ip: str) -> str:
        # Try ip neigh
        try:
            out = subprocess.check_output(["ip", "-o", "neigh", "show", ip], stderr=subprocess.DEVNULL, timeout=1)
            text = out.decode(errors="ignore")
            for part in text.split():
                if ":" in part and len(part) == 17:
                    return part.lower()
        except Exception:
            pass
        # Try arp -n
        try:
            out = subprocess.check_output(["arp", "-n", ip], stderr=subprocess.DEVNULL, timeout=1)
            text = out.decode(errors="ignore").lower()
            for token in text.replace("\t", " ").split():
                if token.count(":") == 5 and len(token) == 17:
                    return token
        except Exception:
            pass
        # Try /proc/net/arp
        try:
            with open("/proc/net/arp", "r", encoding="utf-8") as f:
                lines = f.read().strip().splitlines()[1:]
            for line in lines:
                cols = [c for c in line.split(" ") if c]
                if cols and cols[0] == ip and len(cols) >= 4:
                    mac = cols[3].strip().lower()
                    if mac and mac != "00:00:00:00:00:00":
                        return mac
        except Exception:
            pass
        return ""

    @staticmethod
    def _tcp_connect(ip: str, port: int, timeout: float = 0.4) -> bool:
        import socket as _s
        try:
            with _s.socket(_s.AF_INET, _s.SOCK_STREAM) as s:
                s.settimeout(timeout)
                r = s.connect_ex((ip, port))
                return r == 0
        except Exception:
            return False

    def _check_gns3_ports(self, ip: str) -> Optional[int]:
        # Prefer typical GNS3 ports first
        ports = [3080, 3443, 80, 443]
        for p in ports:
            if self._tcp_connect(ip, p):
                # Optionally we could try a lightweight HTTP GET on 80/3080 to confirm
                return p
        return None

    @staticmethod
    def _normalize_base(url: str) -> str:
        if not url:
            return ""
        url = url.rstrip("/")
        return url

    def _query_gns3_api(self, gkey: Dict[str, str]) -> tuple[bool, int, Optional[float], Optional[float]]:
        import requests
        base = self._normalize_base(str(gkey.get("server_url")))
        token = str(gkey.get("access_token"))
        ttype = (gkey.get("token_type") or "bearer").lower()
        headers = {"Authorization": f"Bearer {token}" if ttype == "bearer" else token}
        sess = requests.Session()
        sess.headers.update(headers)
        verify = False  # allow self-signed
        timeout = 1.5

        def _get(path: str):
            return sess.get(base + path, timeout=timeout, verify=verify)

        # Prefer v3, fallback to v2
        api_base_paths = ["/v3", "/v2"]

        # Reachability check (version)
        api_ok = False
        version_ok = False
        chosen_api = None
        for root in api_base_paths:
            try:
                r = _get(root + "/version")
                if r.ok:
                    version_ok = True
                    chosen_api = root
                    break
            except Exception:
                continue
        api_ok = version_ok and chosen_api is not None

        # Projects opened
        def _count_open(items):
            n = 0
            if isinstance(items, list):
                for it in items:
                    st = str((it or {}).get("state", (it or {}).get("status", ""))).lower()
                    if st in ("open", "opened"):
                        n += 1
            return n

        projects_open = 0
        if chosen_api:
            # v3 uses query param 'state=opened'; v2 used 'status=opened'.
            # Some servers ignore the filter and return all projects; always filter client-side.
            r = _get(f"{chosen_api}/projects?state=opened")
            if not r.ok:
                r = _get(f"{chosen_api}/projects?status=opened")
            if r.ok:
                try:
                    arr = r.json() or []
                    projects_open = _count_open(arr)
                except Exception:
                    pass
            if projects_open == 0:
                r2 = _get(f"{chosen_api}/projects")
                if r2.ok:
                    try:
                        arr = r2.json() or []
                        projects_open = _count_open(arr)
                    except Exception:
                        pass

        # Load statistics: try multiple known endpoints; parse best-effort
        stats_paths = []
        if chosen_api == "/v3":
            stats_paths.extend([
                "/v3/system/statistics",
                "/v3/statistics",
                "/v3/compute/statistics",
            ])
        else:
            stats_paths.extend([
                "/v2/compute/statistics",
                "/v2/statistics",
                "/v2/compute/stats",
                "/v2/system/statistics",
            ])
        cpu_p: Optional[float] = None
        mem_p: Optional[float] = None
        stats = None
        for p in stats_paths:
            try:
                rs = _get(p)
                if rs.ok:
                    j = rs.json()
                    if isinstance(j, dict):
                        stats = j
                        break
            except Exception:
                continue
        if isinstance(stats, dict):
            # common keys guess
            candidates_cpu = [
                "cpu_percent", "cpu_usage_percent", "system_cpu_percent", "cpu_usage",
            ]
            candidates_mem_percent = [
                "memory_percent", "mem_percent", "system_memory_percent",
            ]
            for k in candidates_cpu:
                if k in stats and isinstance(stats[k], (int, float)):
                    cpu_p = float(stats[k])
                    break
            for k in candidates_mem_percent:
                if k in stats and isinstance(stats[k], (int, float)):
                    mem_p = float(stats[k])
                    break
            # derive mem % if total/used present
            if mem_p is None:
                used = None
                total = None
                for k in ["memory_used", "mem_used", "system_memory_used"]:
                    if k in stats and isinstance(stats[k], (int, float)):
                        used = float(stats[k])
                        break
                for k in ["memory_total", "mem_total", "system_memory_total"]:
                    if k in stats and isinstance(stats[k], (int, float)):
                        total = float(stats[k])
                        break
                if used is not None and total:
                    mem_p = (used / total) * 100.0

        return api_ok, projects_open, cpu_p, mem_p

    def _ssh_fetch_metrics(self, ip: str, ssh_conf: Dict[str, str]) -> tuple[bool, Optional[int], Optional[float], Optional[float], Optional[float], List[str]]:
        import paramiko

        username = str(ssh_conf.get("username"))
        password = str(ssh_conf.get("password"))
        port = int(ssh_conf.get("port") or 22)

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(ip, port=port, username=username, password=password,
                           timeout=2.0, banner_timeout=2.0, auth_timeout=2.0, allow_agent=False, look_for_keys=False)

            def run(cmd: str, timeout: float = 2.0) -> str:
                stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
                return stdout.read().decode(errors="ignore")

            # Active users: count sessions excluding the monitoring user
            users_active = None
            try:
                who_list = run("who")
                names: list[str] = []
                for line in who_list.splitlines():
                    if not line.strip():
                        continue
                    parts = line.split()
                    if parts:
                        names.append(parts[0])
                if names:
                    users_active = sum(1 for n in names if n != username)
            except Exception:
                users_active = None
            if users_active is None:
                # Fallback: parse uptime users but subtract one if same user seems logged
                try:
                    up_raw = run("uptime")
                    import re as _re
                    m = _re.search(r"(\d+)\s+users?", up_raw)
                    if m:
                        users_active = int(m.group(1))
                        who_list = run("who")
                        if username and username in who_list:
                            users_active = max(0, users_active - who_list.count(username))
                except Exception:
                    users_active = None
            if users_active is None:
                # Last resort
                try:
                    wc = run("who | wc -l")
                    users_active = int((wc.strip() or "0").splitlines()[-1])
                    if username and users_active:
                        who_list = run("who")
                        cnt = who_list.count(username)
                        users_active = max(0, users_active - cnt)
                except Exception:
                    users_active = None

            # CPU percent using /proc/stat delta
            cpu_raw = run("sh -c \"grep '^cpu ' /proc/stat; sleep 0.4; grep '^cpu ' /proc/stat\"")
            cpu_percent = None
            try:
                lines = [l for l in cpu_raw.strip().splitlines() if l.startswith("cpu ")]
                if len(lines) >= 2:
                    def parse(line: str) -> tuple[int, int]:
                        parts = line.split()
                        if parts[0] != 'cpu':
                            raise ValueError('bad cpu line')
                        nums = list(map(int, parts[1:]))
                        idle = nums[3] + (nums[4] if len(nums) > 4 else 0)  # idle + iowait
                        total = sum(nums)
                        return idle, total
                    idle1, total1 = parse(lines[0])
                    idle2, total2 = parse(lines[1])
                    delta_idle = max(0, idle2 - idle1)
                    delta_total = max(1, total2 - total1)
                    cpu_percent = 100.0 * (1.0 - (delta_idle / delta_total))
            except Exception:
                cpu_percent = None

            # Memory percent using /proc/meminfo
            meminfo_raw = run("cat /proc/meminfo")
            mem_percent = None
            try:
                info = {}
                for line in meminfo_raw.splitlines():
                    if ':' in line:
                        k, v = line.split(':', 1)
                        info[k.strip()] = v.strip()
                def parse_kb(val: str) -> float:
                    # e.g., '16342456 kB'
                    num = ''.join(ch for ch in val if ch.isdigit())
                    return float(num or 0)
                mt = parse_kb(info.get('MemTotal', '0'))
                ma = parse_kb(info.get('MemAvailable', '0'))
                if mt > 0 and ma >= 0:
                    mem_percent = 100.0 * (1.0 - (ma / mt))
            except Exception:
                mem_percent = None

            # Disk percent usage for root filesystem
            df_raw = run("df -P /")
            disk_percent = None
            try:
                lines = df_raw.strip().splitlines()
                if len(lines) >= 2:
                    cols = [c for c in lines[1].split() if c]
                    if len(cols) >= 5:
                        use = cols[4]
                        if use.endswith('%'):
                            use = use[:-1]
                        disk_percent = float(use)
            except Exception:
                disk_percent = None

            client.close()
            # Discover additional IPv4 addresses (exclude localhost/link-local)
            addrs: list[str] = []
            try:
                ip_out = run("ip -4 -o addr show scope global || hostname -I")
                import re as _re
                for token in ip_out.replace("/", " ").replace("\n", " ").split():
                    # crude IPv4 match
                    if _re.match(r"^(?:\d{1,3}\.){3}\d{1,3}$", token):
                        addrs.append(token)
            except Exception:
                pass
            # Dedup and filter
            seen = set()
            filtered: list[str] = []
            for a in addrs:
                if a.startswith("127.") or a.startswith("169.254."):
                    continue
                if a not in seen:
                    seen.add(a)
                    filtered.append(a)
            return True, users_active, cpu_percent, mem_percent, disk_percent, filtered
        except Exception:
            try:
                client.close()
            except Exception:
                pass
            return False, None, None, None, None, []
