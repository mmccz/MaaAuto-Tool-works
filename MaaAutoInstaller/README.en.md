# MaaAuto Installer

> English summary of [README.md](README.md) (Chinese is the primary doc)｜App repo: [MaaAuto-Tool-works](https://github.com/mmccz/MaaAuto-Tool-works)｜User docs: [Wiki](https://github.com/mmccz/MaaAuto-Tool-works/wiki)

Installer / updater / uninstaller for MaaAuto, plus the build and release scripts. Everything is Inno Setup + Python; there is no runtime dependency on PySide6.

## What it is

- **Setup wizard** (Inno Setup): per-user install by default (`%LOCALAPPDATA%\Programs\MaaAuto`), optional "install for all users" via UAC, optional Start-menu and desktop shortcuts, English and Simplified Chinese wizard languages.
- **Payload**: the app directory is shipped as `MaaAuto_payload_v<version>.zip`; Setup embeds it.
- **Delta updates**: file-level binary patches (`MaaAuto_delta_v<old>_to_<new>.zip`, a few hundred KB) with automatic chaining across skipped versions.
- **`upgrade.exe`**: a small GUI-subsystem stub that waits for the running app to exit, applies the payload/delta, then restarts it.

### Artifacts

| Artifact | Purpose |
| --- | --- |
| `MaaAuto_Setup_v<ver>-Windows-x64.exe` | Full installer (~59 MB) |
| `MaaAuto_Online_v<ver>-Windows-x64.exe` | Online bootstrap (~2 MB): downloads the installer, verifies SHA256, starts the wizard |
| `MaaAuto_payload_v<ver>.zip` | Payload used by `upgrade.exe` |
| `MaaAuto_delta_v<old>_to_<new>.zip` | Delta used by the in-app updater |
| `SHA256SUMS.txt` | Checksums for all of the above |

## Installer behaviour

- `AppId {6F3A2C1E-8B4D-4E7A-9C15-3D02A7B9E4C1}` — shared across every MaaAuto install on the machine, so **uninstalling one copy removes the "Settings → Apps" entry of all copies**. Never install/uninstall test builds while relying on a production install; use a scratch folder such as `%LOCALAPPDATA%\Programs\MaaAuto_verify`.
- Writes `.maaauto.json` (version + file list) into the install directory.
- Detects a running app and asks it to exit before replacing files.
- `[UninstallDelete]` removes the Start-menu group; user data (`config\`, `logs\`) is intentionally kept.
- Post-install launch uses `shellexec` because the app manifest requires administrator rights (a direct `CreateProcess` fails with error 740).

## Upgrade flow

1. The app finds a newer Release (stable or beta channel).
2. It prefers a delta from the current version; when none exists it falls back to the full payload.
3. `upgrade.exe` is started with the target archive; it asks the app to exit (`config\.upgrading`) and waits.
4. Files are replaced; on failure the previous files are restored and `config\upgrade_failed.flag` is written for the next launch to report.
5. `config\` and `logs\` are never touched.

## Build

### Requirements

- Windows 10/11 x64, Python 3.15 (`py`)
- Inno Setup 6 at `%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe`
- The main app built first: `cd MaaAuto-Tool-works\MaaAutoProject && py build.py`

### One command

```powershell
cd MaaAuto-Installer\MaaAutoInstaller
py build_release.py                    # build app + stub + Setup + payload + delta + checksums
py build_release.py --skip-main-build  # reuse ..\..\MaaAuto-Tool-works\MaaAutoProject\dist
py build_release.py --skip-stub        # reuse _build\stub\upgrade.exe
py build_release.py --no-trim          # keep every file in the payload
py build_release.py --debug            # keep the console on upgrade.exe
```

### Tests

```powershell
py -m pip install pytest
py -m pytest tests -q      # 98 tests, run from the repo root
```

### Manual upgrade test (no release needed)

```powershell
# 1. fake release server (also points the test install's update_api at localhost)
py tools\fake_release_server.py --payload ..\dist\MaaAuto_payload_v1.0.x.zip

# 2. in another window: check only, then upgrade for real.
#    upgrade.exe is a GUI-subsystem binary: use Start-Process -Wait -PassThru if you
#    need to wait for it or read its exit code.
```

### Release checks

```powershell
py tools\verify_release.py 1.4.6         # E2E: silent install -> content check -> fake upgrade -> uninstall
py tools\smoke_install.py 1.4.6          # smoke: install -> manifest check -> clean uninstall (CI runs this every release)
py tools\verify_release_meta.py mmccz/MaaAuto-Tool-works 1.4.6   # Release/digest/announcement metadata
py tools\repair_integration.py --dir D:\MaaAuto                  # rebuild shortcuts / "Settings → Apps" entry
```

`verify_release.py` and `smoke_install.py` refuse to target a real installation; they use `%LOCALAPPDATA%\Programs\MaaAuto_verify`.

### CI

`.github/workflows/release.yml` builds both repositories on a `v*` tag with Python 3.15, runs the installer tests and the smoke install, then publishes the Release using the app repo's `RELEASE_NOTES.md` as the body (pre-release tags are marked as such).

## Contracts

`installer/contract.py` mirrors `MaaAutoProject/app_info.py`:

| Value | Meaning |
| --- | --- |
| `APP_UPDATE_API` | GitHub API base used by both the app and `upgrade.exe` |
| `APP_MIN_INSTALLER_VERSION` | Below this version the app tells the user to download the full installer |
| `APP_PAYLOAD_ASSET_PREFIX` | Asset-name prefix for payloads and deltas |

Changing any of them is a protocol change: release both repositories together.

## Directory layout

```
MaaAutoInstaller/
  installer/         contract, manifest, payload/delta logic, native progress UI, shell integration
  packaging/         installer.iss, online.iss, trim_payload.py
  tools/             upgrade.exe stub, fake release server, verify/smoke/repair scripts
  build_release.py   one-command build
  tests/             pytest suite (98)
```

## Known limitations

- Only x64 Windows 10/11 is supported.
- The `AppId` is shared, so a test uninstall can remove a production install's registration — repair with `repair_integration.py`.
- Deltas are built per adjacent version pair; skipped versions are chained, and a long chain costs more time than a full payload.
- Without Inno Setup installed, only the payload and delta can be built.

## License

MIT, see [LICENSE](LICENSE).
