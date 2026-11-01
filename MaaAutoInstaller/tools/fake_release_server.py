#!/usr/bin/env python
"""Local fake Release server: run the whole upgrade path **offline**.

Why this exists
---------------
A real upgrade needs a published GitHub Release to test against, and the upgrade
path (check version -> download -> sha256 verify -> stop main app -> unpack and
replace -> rollback -> update manifest -> restart) is the most failure-prone
part. This script mimics the GitHub Releases API shape with `http.server` and
serves a locally built payload as the remote asset, so the updater runs the real
flow, only with URLs pointing at 127.0.0.1.

Usage (two steps)
-----------------
1. Start the server (it prints the command to inject):

    python tools/fake_release_server.py --payload ..\\dist\\MaaAuto_payload_v1.0.2.zip

2. Point the target install directory at the local server, then run the updater:

    # this script can patch .maaauto.json for you (only extra.update_api)
    python tools/fake_release_server.py --payload ..\\dist\\MaaAuto_payload_v1.0.2.zip ^
        --patch-manifest C:\\MaaAutoTest\\app

    C:\\MaaAutoTest\\app\\upgrade.exe --from-main --check-only --no-ui
    C:\\MaaAutoTest\\app\\upgrade.exe --from-main --no-ui

Notes
-----
* Local testing only. `--patch-manifest` rewrites `extra.update_api` to
  `http://127.0.0.1:<port>/releases/latest`; reinstall from the full package or
  change the field back to the GitHub URL afterwards, otherwise the app keeps
  querying the local address.
* The server returns `digest: "sha256:..."` in GitHub shape, so the updater's
  **verification branch** really runs (mismatch -> rollback + upgrade_failed.flag).
* Add `--corrupt-digest` to make verification fail on purpose (rollback test).
"""

import argparse
import hashlib
import json
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_PORT = 8765


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def guess_version(payload: Path) -> str:
    m = re.search(r"payload_v(.+)\.zip$", payload.name)
    return m.group(1) if m else "0.0.0"


def build_release(base_url: str, version: str, tag: str, payload: Path,
                  sha: str, size: int, notes: str,
                  delta: Path = None, delta_sha: str = "") -> dict:
    assets = [
        {
            "name": payload.name,
            "browser_download_url": f"{base_url}/download/{payload.name}",
            "size": size,
            "content_type": "application/zip",
            "digest": f"sha256:{sha}",
        }
    ]
    if delta is not None:
        assets.append({
            "name": delta.name,
            "browser_download_url": f"{base_url}/download/{delta.name}",
            "size": delta.stat().st_size,
            "content_type": "application/zip",
            "digest": f"sha256:{delta_sha}",
        })
    return {
        "tag_name": tag,
        "name": f"MaaAuto {tag}",
        "body": notes,
        "html_url": f"{base_url}/releases/{tag}",
        "draft": False,
        "prerelease": bool(re.search(r"(?:a|b|rc)\d+$", version)),
        "published_at": "2026-01-01T00:00:00Z",
        "assets": assets,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "MaaAutoFakeRelease/1.0"

    # ---- injected by main() ----
    release: dict = None
    payload_path: Path = None
    asset_paths: dict = {}          # asset name -> local file (delta included)

    def log_message(self, fmt, *args):        # default is noisy; keep it short
        print(f"  [http] {self.address_string()} {fmt % args}")

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):                          # noqa: N802 (http.server convention)
        path = self.path.split("?")[0]

        if path in ("/releases/latest", "/releases/latest/"):
            return self._send_json(self.release)

        if path.rstrip("/") == "/releases":
            return self._send_json([self.release])

        if path.startswith("/download/"):
            name = path[len("/download/"):]
            local = self.asset_paths.get(name)
            if local is None:
                return self._send_json({"message": "not found"}, 404)
            size = local.stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(size))
            self.end_headers()
            with open(local, "rb") as f:
                while True:
                    chunk = f.read(1024 * 256)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
            return

        if path == "/health":
            return self._send_json({"ok": True, "payload": self.payload_path.name})

        return self._send_json({"message": "not found"}, 404)


def patch_manifest(install_dir: Path, api: str) -> bool:
    """Point the test install directory's extra.update_api at the local fake server."""
    path = install_dir / ".maaauto.json"
    if not path.exists():
        print(f"[!] 找不到 {path}，先跑一次完整安装包")
        return False
    data = json.loads(path.read_text(encoding="utf-8"))
    extra = data.setdefault("extra", {})
    old = extra.get("update_api")
    extra["update_api"] = api
    # Make the updater see an older version; otherwise the same version never upgrades
    data["version"] = "1.0.0"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] 已把 {path} 的 version 改成 1.0.0，update_api 改为本地：")
    print(f"     旧值: {old}")
    print(f"     新值: {api}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="本地假 Release 服务器（升级链路离线测试）")
    ap.add_argument("--payload", required=True, help="本地 payload zip 路径")
    ap.add_argument("--version", default="", help="版本号，默认从文件名推断")
    ap.add_argument("--tag", default="", help="tag 名，默认 v{version}")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--base-url", default="", help="对外地址，默认 http://host:port")
    ap.add_argument("--notes", default="本地假 Release，用于离线验证升级链路")
    ap.add_argument("--corrupt-digest", action="store_true",
                    help="故意返回错误 sha256（测校验失败 → 回滚）")
    ap.add_argument("--delta", default="",
                    help="可选的差分包（测试差分升级链路时给）")
    ap.add_argument("--patch-manifest", default="",
                    help="顺手把这个安装目录的 extra.update_api 指向本服务")
    args = ap.parse_args()

    payload = Path(args.payload).resolve()
    if not payload.exists():
        print(f"[!] payload 不存在: {payload}")
        return 2

    version = args.version or guess_version(payload)
    tag = args.tag or f"v{version}"
    base_url = args.base_url or f"http://{args.host}:{args.port}"
    api = f"{base_url}/releases/latest"

    sha = sha256_of(payload)
    if args.corrupt_digest:
        sha = "0" * 64
        print("[!] --corrupt-digest：返回的 sha256 是假的，升级应在校验阶段失败并回滚")

    delta = Path(args.delta).resolve() if args.delta else None
    delta_sha = sha256_of(delta) if delta else ""
    release = build_release(base_url, version, tag, payload, sha,
                            payload.stat().st_size, args.notes,
                            delta=delta, delta_sha=delta_sha)
    Handler.release = release
    Handler.payload_path = payload
    Handler.asset_paths = {payload.name: payload}
    if delta is not None:
        Handler.asset_paths[delta.name] = delta

    print("=" * 68)
    print(f"假 Release 已就绪：{tag}（payload {payload.name}，"
          f"{payload.stat().st_size / 1048576:.1f} MB）")
    print(f"  更新接口: {api}")
    print(f"  channel : stable → /releases/latest ；beta → /releases")
    print("=" * 68)

    if args.patch_manifest:
        patch_manifest(Path(args.patch_manifest), api)

    print("\n接下来在另一个终端执行：")
    print(f"  # 只检查（应报「发现新版本」）")
    print(f"  upgrade.exe --from-main --check-only --no-ui")
    print(f"  # 真正升级（下载→校验→替换→更新 manifest）")
    print(f"  upgrade.exe --from-main --no-ui")
    print(f"  # 想验证回滚：加 --corrupt-digest 重启本服务后重跑上面两条\n")

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"监听 http://{args.host}:{args.port} … Ctrl+C 结束")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[ok] 已停止")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
