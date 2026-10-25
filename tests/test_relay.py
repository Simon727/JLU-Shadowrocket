import copy
import base64
import http.client
import http.server
import json
from pathlib import Path
import socket
import socketserver
import sys
import threading
import unittest
import uuid
import zipfile
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import jlu_shadowrocket as app

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = app.read_json(ROOT / "config.example.json")


def workspace():
    # Keep test artifacts inside the ignored workspace; never delete user files.
    folder = ROOT / "private/test-runs" / uuid.uuid4().hex
    folder.mkdir(parents=True)
    app.write_json(folder / "config.example.json", DEFAULT)
    return folder


def read_until(stream, marker):
    data = b""
    while marker not in data:
        block = stream.recv(1)
        if not block:
            raise EOFError("connection ended")
        data += block
    return data


class RelayTests(unittest.TestCase):
    def test_each_installation_has_independent_persistent_secrets(self):
        first, second = workspace(), workspace()
        _, first_secret = app.initialize(first)
        _, second_secret = app.initialize(second)
        self.assertNotEqual(first_secret, second_secret)
        self.assertEqual(app.initialize(first)[1], first_secret)

    def test_invalid_config_rejected(self):
        for changes in ({"allowed_domains": ["example.org"]}, {"allowed_domains": ["*.jlu.edu.cn"]},
                        {"allowed_domains": ["yjs.jlu.edu.cn\r\nINJECT"]}, {"node_name": "bad,name"},
                        {"web_port": DEFAULT["vmess_port"]}, {"allowed_ports": [0]},
                        {"tunnel_mode": "named", "hostname": "https://example.org/path"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                app.validate_config(dict(DEFAULT, **changes))

    def test_generated_route_rejects_other_hosts_and_needs_no_session(self):
        _, secret = app.initialize(workspace())
        server = app.server_config(DEFAULT, secret)
        rules = server["route"]["rules"]
        self.assertEqual(rules[0]["domain"], DEFAULT["allowed_domains"])
        self.assertEqual(rules[0]["network"], "tcp")
        self.assertEqual(rules[-1], {"action": "reject"})
        self.assertEqual(server["inbounds"][0]["listen"], "127.0.0.1")
        self.assertNotIn("cookie", json.dumps(server).lower())
        self.assertNotIn("certificate", json.dumps(server).lower())

    def test_subscription_token_and_named_school_routing(self):
        config, secret = app.initialize(workspace())
        published = {"host": "fixture.trycloudflare.com"}
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), app.make_handler(config, secret, published))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for filename in ("subscription.txt", "subscription.yaml"):
                for query in ("", "?token=wrong"):
                    connection = http.client.HTTPConnection(*server.server_address, timeout=3)
                    connection.request("GET", "/" + filename + query)
                    response = connection.getresponse()
                    self.assertEqual(response.status, 404)
                    self.assertNotIn(secret["uuid"].encode(), response.read())
                    connection.close()
            for filename in ("subscription.txt", "subscription.yaml", "shadowrocket.conf"):
                connection = http.client.HTTPConnection(*server.server_address, timeout=3)
                connection.request("GET", "/" + filename + "?token=" + secret["token"])
                response = connection.getresponse()
                body = response.read().decode()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.getheader("Cache-Control"), "no-store")
                if filename.endswith(".txt"):
                    uri = base64.b64decode(body).decode().strip()
                    parsed = urlsplit(uri)
                    self.assertEqual(parsed.scheme, "vmess")
                    self.assertEqual(base64.b64decode(parsed.netloc).decode(),
                                     f"aes-128-gcm:{secret['uuid']}@{published['host']}:443")
                    fields = parse_qs(parsed.query)
                    self.assertEqual(fields["obfsParam"], [published["host"]])
                    self.assertEqual(fields["peer"], [published["host"]])
                    self.assertEqual(fields["path"], [secret["ws_path"]])
                    self.assertEqual(fields["tls"], ["1"])
                    self.assertNotIn("allowInsecure", fields)
                elif filename.endswith(".yaml"):
                    node = json.loads(body.split("  - ", 1)[1])
                    self.assertEqual(node["uuid"], secret["uuid"])
                    self.assertTrue(node["tls"])
                else:
                    self.assertIn("DOMAIN,yjs.jlu.edu.cn,JLU-Campus", body)
                    self.assertTrue(body.endswith("FINAL,DIRECT\n"))
                    self.assertNotIn(secret["uuid"], body)
                    self.assertNotIn(secret["token"], body)
                connection.close()
        finally:
            server.shutdown()
            server.server_close()

    def test_native_subscription_roundtrips_name_and_websocket_path(self):
        config = dict(DEFAULT, node_name="Campus + test")
        secret = {"uuid": str(uuid.uuid4()), "ws_path": "/private path?ed=2048&key=a+b"}
        encoded = app.make_shadowrocket_subscription("campus.example.com", config, secret)
        uri = base64.b64decode(encoded).decode().strip()
        fields = parse_qs(urlsplit(uri).query)
        self.assertEqual(fields["remarks"], [config["node_name"]])
        self.assertEqual(fields["path"], [secret["ws_path"]])
        self.assertEqual(fields["obfsParam"], ["campus.example.com"])
        with self.assertRaises(ValueError):
            app.make_shadowrocket_subscription("bad.example.com\r\nHost: attacker", config, secret)

    def test_websocket_preserves_pipelined_binary_frames(self):
        config, secret = app.initialize(workspace())
        payload = b"\x82\x84\x01\x02\x03\x04test"
        greeting = b"\x82\x02ok"
        failures = []

        class Upstream(socketserver.BaseRequestHandler):
            def handle(self):
                try:
                    headers = read_until(self.request, b"\r\n\r\n")
                    if not headers.startswith(("GET " + secret["ws_path"] + " HTTP/1.1").encode()):
                        failures.append("wrong path")
                    self.request.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n" + greeting)
                    data = b""
                    while len(data) < len(payload):
                        data += self.request.recv(len(payload) - len(data))
                    self.request.sendall(data)
                except Exception as error:
                    failures.append(type(error).__name__)

        upstream = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Upstream)
        upstream.daemon_threads = True
        config["vmess_port"] = upstream.server_address[1]
        front = http.server.ThreadingHTTPServer(("127.0.0.1", 0), app.make_handler(config, secret, {}))
        front.daemon_threads = True
        for server in (upstream, front):
            threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with socket.create_connection(front.server_address, timeout=3) as client:
                client.sendall((f"GET {secret['ws_path']} HTTP/1.1\r\nHost: fixture.test\r\nConnection: Upgrade\r\nUpgrade: websocket\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: fixture\r\n\r\n").encode() + payload)
                response = read_until(client, b"\r\n\r\n")
                self.assertTrue(response.startswith(b"HTTP/1.1 101"))
                data = b""
                while len(data) < len(greeting + payload):
                    data += client.recv(len(greeting + payload) - len(data))
                self.assertEqual(data, greeting + payload)
            self.assertEqual(failures, [])
        finally:
            for server in (front, upstream):
                server.shutdown()
                server.server_close()

    def test_zip_paths_cannot_escape_tools_directory(self):
        folder = workspace()
        archive = folder / "unsafe.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("../escape.txt", "blocked")
        with self.assertRaises(ValueError):
            app.extract_verified_archive(archive, folder / "tools")

    def test_named_token_stays_in_private_and_out_of_process_arguments(self):
        folder = workspace()
        config, _ = app.initialize(folder)
        config.update(tunnel_mode="named", hostname="relay.example.org")
        (folder / "private/cloudflare-token.txt").write_text("fixture-private-token", encoding="utf-8")
        command = app.cloud_command(folder, config, Path("cloudflared.exe"))
        self.assertIn("--token-file", command)
        self.assertNotIn("fixture-private-token", " ".join(command))
        config["cloudflare_token_file"] = "../config.example.json"
        with self.assertRaises(ValueError):
            app.token_path(folder, config)


if __name__ == "__main__":
    unittest.main()
