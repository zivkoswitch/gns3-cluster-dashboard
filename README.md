# Wake-on-LAN Dashboard (Docker)

Ein leichtgewichtiges, webbasiertes Dashboard zum Überwachen von Hosts (Ping), Anzeigen von Host-Informationen (Hostname, MAC soweit ermittelbar), Prüfen ob GNS3 installiert ist, und zum Senden von Wake-on-LAN Magic-Paketen.

## Features

- Konfiguration per `config/devices.yaml` (Name, IP, optional MAC/Broadcast)
- Hintergrund-Scan (Ping) im Intervall, Reverse-DNS und MAC-Ermittlung (ARP) bei aktiven Hosts
- WoL-Button, wenn ein Host als inaktiv erkannt wird
- GNS3-Prüfung (existieren `gns3`, `gns3server`, `gns3-gui` in PATH?)
- Einfache Weboberfläche (Flask) + REST-API
- Docker-Image inklusive Ping/ARP Tools
 - Pro Gerät: Port-Check für GNS3 (80/443/3080/3443) und Link-Anzeige

## Quickstart (Docker)

1. Passe `config/devices.yaml` an (Beispiel vorhanden).
2. Baue das Image:

   ```bash
   docker build -t wol-dashboard .
   ```

3. Starte den Container (Netzwerkzugriff auf dein LAN vorausgesetzt):

   ```bash
   docker run --name wol-dashboard \
     --restart unless-stopped \
     -p 8000:8000 \
     -v $(pwd)/config:/app/config:ro \
     -e SCAN_INTERVAL=30 \
     wol-dashboard
   ```

4. Öffne das Dashboard: http://localhost:8000

Hinweis: Der Container enthält `iputils-ping`, `iproute2` und `net-tools`, damit Ping und ARP-Auflösung funktionieren.

### Troubleshooting: Base Image Pull/Proxy/DNS

Wenn der Build beim Ziehen des Base Images (z. B. `python:3.11-slim`) mit einem DNS-/Proxy-Fehler abbricht:

- Teste DNS/Netz vom Host:
  - `nslookup registry-1.docker.io`
  - `curl -I https://registry-1.docker.io/v2/`
- Baue mit Host-Netzwerk (nutzt die Resolver des Hosts):
  - `docker build --network=host -t wol-dashboard .`
  - oder via Compose (bereits konfiguriert): `docker compose up -d --build`
- Hinter Proxy: Setze Umgebungsvariablen vor dem Build und Compose reicht diese weiter:
  - `export HTTP_PROXY=http://user:pass@proxy:port`
  - `export HTTPS_PROXY=http://user:pass@proxy:port`
  - `export NO_PROXY=localhost,127.0.0.1,10.0.0.0/8,192.168.0.0/16`
- Docker Daemon DNS einstellen (Linux): `/etc/docker/daemon.json` mit `"dns": ["8.8.8.8","1.1.1.1"]` und Docker neu starten.

## Konfiguration

Datei: `config/devices.yaml` (Vorlage unter `config/devices.yaml.template`)

Kopiere die Vorlage:

```bash
cp config/devices.yaml.template config/devices.yaml
```

```yaml
devices:
  - name: "Server-1"
    ip: "10.21.34.205"
    # optional Wake-on-LAN Felder
    mac: "00:11:22:33:44:55"
    broadcast: "10.21.34.255"
    # optional GNS3 API Zugang
    gns3key:
      server_url: "http://10.21.34.205:3080"
      user: "admin"
      access_token: "<TOKEN>"
      token_type: "bearer"
    # optional SSH (für Systemmetriken)
    ssh:
      username: "user"
      password: "user"
      # port: 22
  - name: "Server-2"
    ip: "10.21.34.206"
    gns3key:
      server_url: "http://10.21.34.206:3080"
      user: "admin"
      access_token: "<TOKEN>"
      token_type: "bearer"
```

Environment-Variablen:

- `CONFIG_PATH` Pfad zur Konfig (Default: `/app/config/devices.yaml`)
- `SCAN_INTERVAL` Scanintervall in Sekunden (Default: `30`)
- `PORT` HTTP-Port (Default: `8000`)

## API

- `GET /api/status` → `{ devices: [...], gns3: {...}, generated: <epoch> }`
- `POST /api/wol` → JSON Body: `{ id?: string, mac?: string, broadcast?: string }`
  - Wenn `id` angegeben ist, werden fehlende Felder aus der Konfiguration aufgefüllt.
  
Rückgabefelder pro Device (Auszug): `up`, `hostname`, `mac`, `last_seen`, `gns3_active`, `gns3_port`, `gns3_url`.
Zusätzlich bei GNS3-API-Konfiguration: `gns3_api_ok`, `gns3_projects_open`, `gns3_cpu_percent`, `gns3_mem_percent`.
Zusätzlich bei SSH-Konfiguration: `ssh_ok`, `ssh_users_active`, `ssh_cpu_percent`, `ssh_mem_percent`, `ssh_disk_percent`.

## Hinweise zur Erkennung

- Ping: `ping -c 1 -w 1 <ip>`
- MAC: bevorzugt `ip neigh show <ip>`, Fallback `arp -n <ip>` und `/proc/net/arp`
- Hostname: Reverse DNS (`gethostbyaddr`)
- GNS3: Prüft auf Binaries im Container-PATH. Wenn GNS3 nur auf dem Host installiert ist, wird es im Container i. d. R. als nicht installiert angezeigt.

## Entwicklung (ohne Docker)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export CONFIG_PATH=config/devices.yaml
export SCAN_INTERVAL=30
python -m app.server
```

Öffne http://localhost:8000

## Docker Compose

Mit dem mitgelieferten `docker-compose.yml` kannst du das Dashboard bequem starten.

- Standard (Bridge-Netzwerk, Port-Mapping):

  ```bash
  docker compose up -d --build
  # danach: http://localhost:8000
  ```

- Linux Host-Netzwerk (bessere Broadcast-Erreichbarkeit für WoL):

  ```bash
  docker compose --profile hostnet up -d --build
  # bei hostnet kein Port-Mapping nötig; läuft auf :8000 der Host-IP
  ```

Hinweis: `network_mode: host` wird von Docker Desktop auf macOS/Windows nicht unterstützt. Nutze hier den Standardmodus oder starte nativ.
