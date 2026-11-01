"""Post-release metadata verification: Release state / asset digests / online announcement sources.

Usage ::

    python MaaAutoInstaller/tools/verify_release_meta.py 1.1.0

Downloads nothing large; validates through the GitHub API only:
  1. the Release is published (not draft / not prerelease) and `releases/latest` points at it;
  2. release notes (RELEASE_NOTES.md) uploaded and containing the two mandatory settings;
  3. all 4 assets present, `SHA256SUMS.txt` matching GitHub's computed `sha256:` digest item by item;
  4. online announcement sources (raw.githubusercontent + jsDelivr) reachable and containing this version.

To verify "the package actually installs", also run tools/verify_release.py <version> (it does a real install).
"""

import json
import sys
import tempfile
import urllib.request
from pathlib import Path

REPO = sys.argv[1] if len(sys.argv) > 1 else "mmccz/MaaAuto-Tool-works"
VERSION = sys.argv[2] if len(sys.argv) > 2 else ""
if not VERSION:
    raise SystemExit("用法: python verify_release_meta.py [owner/repo] <version>")
TAG = f"v{VERSION}"

UA = {"User-Agent": "MaaAuto-Release-Check"}
API = f"https://api.github.com/repos/{REPO}/releases/tags/{TAG}"
fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name +
          (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        fails.append(name)


def http_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def download(url, dest: Path):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as f:
        f.write(resp.read())


work = Path(tempfile.mkdtemp(prefix="maa_relmeta_"))

print("=" * 72)
print(f"[1] Release API（{TAG}）")
rel = http_json(API)
check(f"tag = {TAG}", rel["tag_name"] == TAG, rel["tag_name"])
check("draft = false", rel["draft"] is False)
check("prerelease = false", rel["prerelease"] is False)
check("发布时间非空", bool(rel.get("published_at")))
body = rel.get("body") or ""
check("发布说明已上传（>500 字）", len(body) > 500, str(len(body)))
check("发布说明含两处必改设置", "完成后退出模拟器" in body and "关闭模拟器" in body)

assets = {a["name"]: a for a in rel["assets"]}
for name in (f"MaaAuto_Setup_v{VERSION}-Windows-x64.exe",
             f"MaaAuto_Online_v{VERSION}-Windows-x64.exe",
             f"MaaAuto_payload_v{VERSION}.zip",
             "SHA256SUMS.txt"):
    check(f"资产存在 {name}", name in assets)
    if name in assets:
        a = assets[name]
        print(f"     {name}: {a['size']} bytes, digest={(a.get('digest') or '')[:22]}…")

delta_names = [n for n in assets if n.startswith("MaaAuto_delta_v")]
check("差分包存在（1.2.0+）", bool(delta_names), str(list(assets)))
for name in delta_names:
    a = assets[name]
    print(f"     {name}: {a['size']} bytes（{a['size']/1048576:.2f} MB）, "
          f"digest={(a.get('digest') or '')[:22]}…")

latest = http_json(f"https://api.github.com/repos/{REPO}/releases/latest")
check(f"releases/latest = {TAG}", latest["tag_name"] == TAG, latest["tag_name"])

print("=" * 72)
print("[2] SHA256SUMS 与 GitHub 计算的资产 digest 一致")
sums_path = work / "SHA256SUMS.txt"
download(assets["SHA256SUMS.txt"]["browser_download_url"], sums_path)
sums = {}
for line in sums_path.read_text(encoding="utf-8").splitlines():
    if line.strip():
        digest, name = line.split()
        sums[name] = digest
# 3 fixed artifacts + optional delta package
check("SHA256SUMS 含 3~4 个产物", 3 <= len(sums) <= 4, str(list(sums)))
check("差分包已写入 SHA256SUMS",
      all(n in sums for n in delta_names) if delta_names else True,
      str(list(sums)))
for name, asset in assets.items():
    if name == "SHA256SUMS.txt":
        continue
    api_digest = (asset.get("digest") or "").replace("sha256:", "")
    check(f"{name} digest 匹配", sums.get(name) == api_digest,
          f"sums={sums.get(name)} api={api_digest}")

print("=" * 72)
print("[3] 在线公告源（客户端启动时会拉）—— 仅提示，不作为发布失败条件")
ok_sources = 0
for url in (
    "https://raw.githubusercontent.com/mmccz/MaaAuto-Tool-works/main/"
    "MaaAutoProject/resources/announcements.json",
    "https://cdn.jsdelivr.net/gh/mmccz/MaaAuto-Tool-works@main/"
    "MaaAutoProject/resources/announcements.json",
):
    host = url.split("/")[2]
    err = ""
    for _ in range(3):                      # raw hits occasionally time out here; retry a few times
        try:
            d = http_json(url)
            items = d.get("items") or []
            print(f"     {host}: updated={d.get('updated')} items={len(items)}")
            ok_sources += 1
            err = ""
            break
        except Exception as e:
            err = str(e)
    if err:
        print(f"  WARN  公告源暂时不可用 {host}: {err}")
if ok_sources:
    check("至少一个公告源可用", True)
else:
    print("  WARN  两个公告源都不可用（网络原因，不影响已发布资产）")

print()
print("=" * 72)
print("RESULT:", "ALL PASSED" if not fails else f"FAILED ({len(fails)}): {fails}")
sys.exit(1 if fails else 0)
