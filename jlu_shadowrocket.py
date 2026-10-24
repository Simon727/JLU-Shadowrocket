"""A portable campus-only Shadowrocket relay. Python standard library only."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import http.server
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import secrets
import select
import shutil
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit
import uuid
import zipfile

ROOT = Path(__file__).resolve().parent
DOMAIN = re.compile(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+jlu\.edu\.cn$", re.I)
HOSTNAME = re.compile(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$", re.I)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_config(config):
    domains = config.get("allowed_domains")
    if not isinstance(domains, list) or not domains or len(domains) > 128:
        raise ValueError("allowed_domains must contain 1-128 explicit school domains")
    if any(not isinstance(item, str) or not DOMAIN.fullmatch(item) for item in domains):
        raise ValueError("Only explicit subdomains of jlu.edu.cn are accepted; no wildcards")
    name = config.get("node_name", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", name):
        raise ValueError("node_name must use 1-64 ASCII letters, numbers, dots, underscores or hyphens")
    ports = config.get("allowed_ports")
    if not isinstance(ports, list) or not ports or any(type(p) is not int or not 1 <= p <= 65535 for p in ports):
        raise ValueError("allowed_ports must contain valid TCP port numbers")
    local_ports = [config.get(key) for key in ("web_port", "vmess_port", "metrics_port", "check_port")]
    if any(type(p) is not int or not 1024 <= p <= 65535 for p in local_ports) or len(set(local_ports)) != 4:
        raise ValueError("The four local ports must be distinct numbers from 1024 to 65535")
    if config.get("tunnel_mode") not in {"quick", "named"}:
        raise ValueError("tunnel_mode must be quick or named")
    if config["tunnel_mode"] == "named" and not HOSTNAME.fullmatch(config.get("hostname", "")):
        raise ValueError("Named tunnels need a hostname without https:// or a path")
    return config


def initialize(root=ROOT):
    private = root / "private"
    private.mkdir(mode=0o700, exist_ok=True)
    config_path = private / "config.json"
    if not config_path.exists():
        write_json(config_path, read_json(root / "config.example.json"))
    config = validate_config(read_json(config_path))
    secret_path = private / "secrets.json"
    if not secret_path.exists():
        write_json(secret_path, {"uuid": str(uuid.uuid4()), "token": secrets.token_urlsafe(32), "ws_path": "/jlu-" + secrets.token_urlsafe(24)})
    secret = read_json(secret_path)
    uuid.UUID(secret["uuid"])
    if len(secret["token"]) < 32 or not re.fullmatch(r"/jlu-[A-Za-z0-9_-]{24,}", secret["ws_path"]):
        raise ValueError("Invalid private/secrets.json; existing secrets were not overwritten")
    return config, secret


def server_config(config, secret):
    return {
        "log": {"level": "warn", "timestamp": True},
        "dns": {"servers": [{"type": "local", "tag": "campus-dns"}]},
        "inbounds": [{"type": "vmess", "tag": "campus-in", "listen": "127.0.0.1", "listen_port": config["vmess_port"],
                      "users": [{"name": "owner", "uuid": secret["uuid"], "alterId": 0}],
                      "transport": {"type": "ws", "path": secret["ws_path"]}}],
        "outbounds": [{"type": "direct", "tag": "campus-only"}],
        "route": {"default_domain_resolver": "campus-dns", "rules": [
            {"domain": config["allowed_domains"], "network": "tcp", "port": config["allowed_ports"], "action": "route", "outbound": "campus-only"},
            {"action": "reject"},
        ]},
    }


def make_node(host, config, secret):
    if not HOSTNAME.fullmatch(host):
        raise ValueError("Invalid public hostname")
    return {"name": config["node_name"], "type": "vmess", "server": host, "port": 443, "uuid": secret["uuid"],
            "alterId": 0, "cipher": "aes-128-gcm", "tls": True, "servername": host, "sni": host,
            "network": "ws", "udp": False, "ws-opts": {"path": secret["ws_path"], "headers": {"Host": host}}}


def make_routing(config):
    # Exact named policy also works when inserted before an existing CN/DIRECT rule.
    rules = [f"DOMAIN,{host},{config['node_name']}" for host in config["allowed_domains"]]
    return "[General]\ndns-server = system\nipv6 = false\ntun-excluded-routes = 127.0.0.0/8\n\n[Rule]\n" + "\n".join(rules) + "\nFINAL,DIRECT\n"


def make_handler(config, secret, published):
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        rbufsize = 0  # Preserve frames sent immediately after the upgrade headers.

        def log_message(self, *_):
            pass  # Never log URLs, query tokens, headers or node credentials.

        def reply(self, status, body=b"", kind="text/plain; charset=utf-8"):
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not ipaddress.ip_address(self.client_address[0]).is_loopback:
                self.reply(403)
                return
            parsed = urlsplit(self.path)
            if parsed.path == "/_health":
                self.reply(200, b"running\n")
                return
            if parsed.path == secret["ws_path"] and self.headers.get("Upgrade", "").lower() == "websocket":
                self.forward_websocket()
                return
            token = parse_qs(parsed.query).get("token", [""])[0]
            if not hmac.compare_digest(token.encode(), secret["token"].encode()):
                self.reply(404)
                return
            if parsed.path == "/shadowrocket.conf":
                self.reply(200, make_routing(config).encode())
            elif parsed.path == "/subscription.yaml":
                if not published.get("host"):
                    self.reply(503, b"Public hostname not ready\n")
                    return
                body = "proxies:\n  - " + json.dumps(make_node(published["host"], config, secret)) + "\n"
                self.reply(200, body.encode())
            else:
                self.reply(404)

        def forward_websocket(self):
            self.close_connection = True
            try:
                with socket.create_connection(("127.0.0.1", config["vmess_port"]), timeout=5) as upstream:
                    lines = [f"GET {secret['ws_path']} HTTP/1.1", "Connection: Upgrade", "Upgrade: websocket"]
                    for name in ("Host", "Origin", "Sec-WebSocket-Key", "Sec-WebSocket-Version", "Sec-WebSocket-Protocol", "Sec-WebSocket-Extensions"):
                        value = self.headers.get(name)
                        if value:
                            lines.append(f"{name}: {value}")
                    upstream.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("latin1"))
                    response = b""
                    while b"\r\n\r\n" not in response:
                        block = upstream.recv(4096)
                        if not block or len(response) > 65536:
                            self.reply(502)
                            return
                        response += block
                    self.wfile.write(response)
                    self.wfile.flush()
                    if not response.startswith(b"HTTP/1.1 101 "):
                        return
                    upstream.settimeout(None)
                    peers = {self.connection: upstream, upstream: self.connection}
                    while True:
                        readable, _, _ = select.select(list(peers), [], [], 30)
                        for stream in readable:
                            block = stream.recv(65536)
                            if not block:
                                return
                            peers[stream].sendall(block)
            except (OSError, ConnectionError):
                return
    return Handler


def extract_verified_archive(archive, destination):
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            if not (destination / member.filename).resolve().is_relative_to(destination.resolve()):
                raise ValueError("Archive contains a path outside tools/")
            if (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Archive contains a symbolic link")
        bundle.extractall(destination)


def setup_tools(root, download_proxy=None):
    if sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise ValueError("This release packages Windows x64 tools only")
    curl = shutil.which("curl.exe")
    if not curl:
        raise ValueError("curl.exe is required (included in supported Windows 10/11)")
    folder = root / "tools"
    folder.mkdir(exist_ok=True)
    lock = read_json(root / "tools.lock.json")
    for name in ("sing-box", "cloudflared"):
        asset = lock[name]
        target = folder / asset["filename"]
        if not target.exists():
            command = [curl, "--fail", "--location", "--show-error", "--silent", "--proto", "=https", "--proto-redir", "=https", "--connect-timeout", "20", "--max-time", "180", "--output", str(target)]
            if download_proxy:
                command += ["--proxy", download_proxy]
            print(f"Downloading {name} {asset['version']} ...", flush=True)
            subprocess.run(command + [asset["url"]], check=True)
        if hashlib.sha256(target.read_bytes()).hexdigest() != asset["sha256"]:
            raise ValueError(f"Checksum mismatch: {target.name}. The file was retained; do not execute it.")
        if target.suffix == ".zip":
            extract_verified_archive(target, folder)
        print(f"Verified {name} {asset['version']}")
    initialize(root)


def executables(root):
    lock = read_json(root / "tools.lock.json")
    result = tuple(root / "tools" / lock[name]["executable"] for name in ("sing-box", "cloudflared"))
    if not all(item.is_file() for item in result):
        raise ValueError("Run setup first: python jlu_shadowrocket.py setup")
    return result


def prepare(root):
    config, secret = initialize(root)
    sing, cloud = executables(root)
    private = root / "private"
    server_path = private / "sing-box-server.json"
    write_json(server_path, server_config(config, secret))
    (private / "cloudflared.yml").write_text("{}\n", encoding="utf-8")
    subprocess.run([str(sing), "check", "-c", str(server_path)], check=True, cwd=private)
    return config, secret, sing, cloud


def token_path(root, config):
    private = (root / "private").resolve()
    result = (private / config["cloudflare_token_file"]).resolve()
    if not result.is_relative_to(private) or not result.is_file():
        raise ValueError("Named tunnel token must be an existing file inside private/")
    return result


def cloud_command(root, config, cloud):
    private = root / "private"
    command = [str(cloud), "tunnel", "--config", str(private / "cloudflared.yml"), "--no-autoupdate", "--protocol", "http2", "--edge-ip-version", "4", "--metrics", f"127.0.0.1:{config['metrics_port']}"]
    if config["tunnel_mode"] == "quick":
        command += ["--url", f"http://127.0.0.1:{config['web_port']}"]
    else:
        command += ["run", "--token-file", str(token_path(root, config))]
    return command


def wait_listening(port, child):
    for _ in range(100):
        if child.poll() is not None:
            raise RuntimeError("Child process exited; inspect private/ logs")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=.1):
                return
        except OSError:
            time.sleep(.1)
    raise TimeoutError("Local service did not start")


def start(root):
    config, secret, sing, cloud = prepare(root)
    private = root / "private"
    published = {}
    # Binding before starting children also prevents duplicate instances.
    server = http.server.ThreadingHTTPServer(("127.0.0.1", config["web_port"]), make_handler(config, secret, published))
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    children = []
    environment = os.environ.copy()
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy", "TUNNEL_TOKEN"):
        environment.pop(key, None)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    runtime = {"status": "starting", "mode": config["tunnel_mode"]}
    runtime_path = private / "runtime.json"
    write_json(runtime_path, runtime)
    try:
        with (private / "sing-box.log").open("a", encoding="utf-8") as sing_log, (private / "cloudflared.log").open("a", encoding="utf-8") as cloud_log:
            children.append(subprocess.Popen([str(sing), "run", "-c", str(private / "sing-box-server.json")], cwd=private, env=environment, stdout=sing_log, stderr=sing_log, creationflags=flags))
            wait_listening(config["vmess_port"], children[0])
            offset = (private / "cloudflared.log").stat().st_size
            children.append(subprocess.Popen(cloud_command(root, config, cloud), cwd=private, env=environment, stdout=cloud_log, stderr=cloud_log, creationflags=flags))
            print("Starting Cloudflare transport; keep this window open. Ctrl+C stops this instance.", flush=True)
            started = time.monotonic()
            while all(child.poll() is None for child in children):
                if not published:
                    if config["tunnel_mode"] == "named":
                        host = config["hostname"]
                    else:
                        with (private / "cloudflared.log").open(encoding="utf-8", errors="replace") as reader:
                            reader.seek(offset)
                            match = re.search(r"https://([a-z0-9-]+\.trycloudflare\.com)", reader.read())
                        host = match.group(1) if match else ""
                    if host:
                        published["host"] = host
                        links = {"subscription": f"https://{host}/subscription.yaml?token={secret['token']}",
                                 "config": f"https://{host}/shadowrocket.conf?token={secret['token']}"}
                        write_json(private / "links.json", links)
                        write_json(private / "node.json", make_node(host, config, secret))
                        (private / "shadowrocket.conf").write_text(make_routing(config), encoding="utf-8")
                        runtime.update(status="running", host=host, pids=[p.pid for p in children])
                        write_json(runtime_path, runtime)
                        print("\nPhone import links (private; do not publish):", flush=True)
                        print("Subscription: " + links["subscription"], flush=True)
                        print("Config:       " + links["config"], flush=True)
                        print("\nWait for the tunnel to connect, then run: python jlu_shadowrocket.py check", flush=True)
                    elif time.monotonic() - started > 180:
                        raise TimeoutError("No public hostname after 180 seconds; inspect private/cloudflared.log")
                time.sleep(.5)
            raise RuntimeError("A relay child exited; inspect private/ logs")
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
        server.shutdown()
        server.server_close()
        runtime["status"] = "stopped"
        write_json(runtime_path, runtime)


def check(root):
    config, secret = initialize(root)
    runtime = read_json(root / "private/runtime.json")
    if runtime.get("status") != "running":
        raise ValueError("Start the relay in another terminal first")
    sing, _ = executables(root)
    host = runtime["host"]
    outbound = {"type": "vmess", "tag": "relay", "server": host, "server_port": 443,
                "uuid": secret["uuid"], "security": "aes-128-gcm", "alter_id": 0,
                "tls": {"enabled": True, "server_name": host},
                "transport": {"type": "ws", "path": secret["ws_path"], "headers": {"Host": host}}}
    client = {"log": {"level": "warn"}, "dns": {"servers": [{"type": "local", "tag": "system"}]},
              "inbounds": [{"type": "http", "listen": "127.0.0.1", "listen_port": config["check_port"]}],
              "outbounds": [outbound], "route": {"final": "relay", "default_domain_resolver": "system"}}
    client_path = root / "private/check-client.json"
    write_json(client_path, client)
    subprocess.run([str(sing), "check", "-c", str(client_path)], check=True)
    with (root / "private/check.log").open("a", encoding="utf-8") as log:
        child = subprocess.Popen([str(sing), "run", "-c", str(client_path)], cwd=root / "private", stdout=log, stderr=log, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            wait_listening(config["check_port"], child)
            targets = {"yjs.jlu.edu.cn": "/gsapp/sys/yjsemaphome/portal/index.do", "oa.jlu.edu.cn": "/defaultroot/login.jsp", "cas.jlu.edu.cn": "/tpass/login", "cwsf.jlu.edu.cn": "/WF_PAYMENT/"}
            results = []
            for domain in config["allowed_domains"]:
                command = ["curl.exe", "--silent", "--show-error", "--proxy", f"http://127.0.0.1:{config['check_port']}", "--noproxy", "", "--connect-timeout", "8", "--max-time", "30", "--max-redirs", "5", "--proto-redir", "=http,https", "-L", "-o", "NUL", "-w", "%{json}", "https://" + domain + targets.get(domain, "/")]
                response = subprocess.run(command, capture_output=True, text=True, timeout=35)
                if response.returncode:
                    results.append({"target": domain, "ok": False, "error": response.stderr.strip()})
                    continue
                metadata = json.loads(response.stdout)
                final_url = urlsplit(metadata["url_effective"])
                results.append({"target": domain, "final_host": final_url.hostname, "final_scheme": final_url.scheme,
                                "status": metadata["http_code"], "tls_verify_result": metadata["ssl_verify_result"], "bytes": int(metadata["size_download"]),
                                "ok": metadata["http_code"] == 200 and metadata["ssl_verify_result"] == 0})
            denied = subprocess.run(["curl.exe", "--silent", "--proxy", f"http://127.0.0.1:{config['check_port']}", "--noproxy", "", "--max-time", "8", "-o", "NUL", "-w", "%{http_code}", "http://example.org/"], capture_output=True, text=True, timeout=10)
            report = {"sites": results, "empty_response_hosts": [item["target"] for item in results if item.get("bytes") == 0], "other_domain_rejected": denied.returncode != 0 or denied.stdout.strip() in {"403", "502"}}
            write_json(root / "private/check-result.json", report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return all(item["ok"] for item in results) and report["other_domain_rejected"]
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=8)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "setup", "prepare", "start", "check", "status"))
    parser.add_argument("--download-proxy", help="Optional HTTP proxy for GitHub tool downloads only")
    args = parser.parse_args()
    if args.command == "setup":
        setup_tools(ROOT, args.download_proxy)
    elif args.command == "init":
        initialize(ROOT)
        print("Created local private/ configuration and independent keys. Existing keys were preserved.")
    elif args.command == "prepare":
        prepare(ROOT)
        print("Configuration validated; no tunnel or listener was started.")
    elif args.command == "start":
        start(ROOT)
    elif args.command == "check":
        return 0 if check(ROOT) else 1
    elif args.command == "status":
        print(json.dumps(read_json(ROOT / "private/runtime.json"), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nStopped this relay instance. No files were deleted.")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
