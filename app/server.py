import os
import time
from typing import Dict

from flask import Flask, jsonify, render_template, request

from .config import load_config
from .gns3 import check_gns3
from .scanner import NetworkScanner
from .wol import send_magic_packet


def create_app() -> Flask:
    cfg = load_config()
    scan_interval = int(os.getenv("SCAN_INTERVAL", "30"))
    app = Flask(__name__, static_folder="static", template_folder="templates")
    scanner = NetworkScanner(cfg.get("devices", []), interval=scan_interval)
    scanner.start()

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/status")
    def status():
        devices = scanner.snapshot()
        return jsonify({
            "devices": devices,
            "gns3": check_gns3(),
            "scan_interval": scanner.interval,
            "generated": int(time.time()),
        })

    @app.route("/api/wol", methods=["POST"])
    def wol():
        data: Dict[str, str] = request.get_json(silent=True) or {}
        dev_id = data.get("id")
        mac = (data.get("mac") or "").lower()
        broadcast = data.get("broadcast") or ""
        if dev_id:
            dev = scanner.get(dev_id)
            if not dev:
                return jsonify({"ok": False, "error": "device not found"}), 404
            mac = mac or dev.mac
            broadcast = broadcast or dev.broadcast
        if not mac:
            return jsonify({"ok": False, "error": "mac required"}), 400
        try:
            send_magic_packet(mac, broadcast_ip=broadcast or None)
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.route("/api/scan-now", methods=["POST"])
    def scan_now():
        try:
            scanner.scan_now()
            return jsonify({"ok": True, "devices": scanner.snapshot(), "generated": int(time.time())})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    return app


def main():
    app = create_app()
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
