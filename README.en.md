<div align="center">

<img src="docs/images/logo.png" width="112" alt="MaaAuto logo">

# MaaAuto

**A scheduling console for MAA & MaaEnd**

[![Version](https://img.shields.io/badge/version-1.4.6-2f81f7.svg)](CHANGELOG.md)
[![Python](https://img.shields.io/badge/Python-3.15%2B-3776AB.svg)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/GUI-PySide6-41CD52.svg)](https://pypi.org/project/PySide6/)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%20%2F%2011-0078D4.svg)](#requirements)
[![License](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

[简体中文](README.md) ｜ **English** ｜ 📘 [Full user guide](docs/guide/en-US.md) ｜ 🌐 [Wiki](https://github.com/mmccz/MaaAuto-Tool-works/wiki) (bilingual)

</div>

---


> **The installer now lives in this repository**: build scripts, Inno packaging and the updater are under `MaaAutoInstaller/`.

## What it is

MaaAuto is a Windows desktop **scheduling shell**: at the time you set it launches [MAA](https://github.com/MaaAssistantArknights/MaaAssistantArknights) or [MaaEnd](https://github.com/MaaEnd/MaaEnd), lets them run the task queue you already configured, judges the outcome from their logs, then pushes the result to WeChat or a webhook.

It contains **no game logic** — no patching, no memory reading, no input replay. It does three things: **start on schedule, drive the upstream, judge the result**.

> **Since 2.0 clicking is no longer the default**: MAA is started through its own config
> ("start the queue directly" written into the active scheme) and MaaEnd through
> `--autostart --instance <name> --quit-after-run`, with the outcome read from their logs.
> The 1.x find-and-click path is kept as a compatibility mode (`control: "click"`).

---

## ✨ Features

**Scheduling**

- Multiple slots per day (e.g. 08:00 / 20:30) and weekday filters; a missed slot is caught up after startup
- Background scheduler checks every 10 seconds; "Run now" and "Stop" are always available
- Foreground strategy: do nothing / close all foreground apps / close a blacklist
- Optional logon autostart using a scheduled task (highest privileges, no UAC prompt)

**Updates**

- In-app update check with stable / beta channels
- Delta updates (usually < 1 MB) with automatic chaining across versions, falling back to the full payload
- Rollback on failure; `config/`, `logs/` and `.maaauto.json` are preserved

**Notifications**

- ServerChan (WeChat) and generic webhooks, with a "Test" button
- Tray balloons for success / failure / aborted runs

**UI**

- Light / dark / system theme, accent colour, background image, UI scale (100/125/150%)
- Chinese and English interface, announcement centre with search, first-run tutorial

---

## 🚀 Quick start

### Requirements

| Item | Requirement |
| --- | --- |
| OS | Windows 10 / 11 (x64) |
| Display | Any resolution; 100% / 125% / 150% scaling supported (multi-scale matching; "Capture template" recalibrates) |
| Python (source only) | 3.11+; development and CI use **3.15**; use the [python.org](https://www.python.org/downloads/) build, **not** the Microsoft Store build (`%APPDATA%` gets redirected) |
| Companion apps | [MAA](https://github.com/MaaAssistantArknights/MaaAssistantArknights) and/or [MaaEnd](https://github.com/MaaEnd/MaaEnd) |

> The installer build needs no Python and works offline.

### Option 1: installer (recommended)

Download from [Releases](https://github.com/mmccz/MaaAuto-Tool-works/releases):

| File | Purpose |
| --- | --- |
| `MaaAuto_Setup_v2.0.0-Windows-x64.exe` | **Full installer (~62 MB)**, embeds the app, works offline |
| `MaaAuto_Online_v2.0.0-Windows-x64.exe` | Online bootstrap (~2 MB), downloads the full installer |

Installs in about 30 seconds, needs no Python and no network; per-user install goes to `%LOCALAPPDATA%\Programs\MaaAuto`, and "install for all users" (Program Files) is offered in the wizard — that one shows UAC.

The Start menu shortcut is optional (on by default); the desktop icon is optional (off by default).

The app itself requires administrator rights (it starts/stops the upstreams, may message their windows and writes MAA's config file), so **each launch shows one UAC prompt** — that is expected.

### Option 2: from source

```powershell
cd MaaAutoProject
py -m pip install -r requirements.txt
py main.py
```

> Start from inside `MaaAutoProject`; `main.py` relies on relative paths there.

### Image templates (compatibility mode)

> This section only matters with `control: "click"` (the 1.x vision/click path). The default config-injection mode never looks at the screen, so upstream redesigns, themes and window resizes cannot break it.

| File | Purpose |
| --- | --- |
| `resources/maa_start.png` | MAA's bottom-right "Link Start!" |
| `resources/maaend_start.png` | MaaEnd's "Start task" |

Matching runs a **60%–200% multi-scale search**, so 100% / 125% / 150% usually hit directly. When it still misses (different UI language, redesigned button, non-integer scaling) you do not need to touch code:

1. Settings → **Matching & clicking** → **Capture template**;
2. Pick the target (MAA / MaaEnd / custom name) → "Start capture";
3. The screen dims; drag a box around the button (button only) → release to save into `config/templates/`;
4. The dialog reports the self-check score; re-capture if it is below 0.85.

Files in `config/templates/` **override** the bundled ones, so a fresh capture takes effect immediately. Use **Test match** first: it reports score / scale / coordinates without clicking.

### First-run setup

> ⚠️ **Do these two first, or automation cannot finish:**
>
> 1. **MAA → Settings → Startup settings → enable "Exit emulator when done"**
>    Without it the emulator keeps holding memory and ADB after the tasks. 2.0 judges the end from MAA's log instead, but the switch is still required: MAA finishes cleanly and the next round does not have to fight over the same emulator.
> 2. **MaaEnd → task list → add "Close program" or "Close emulator" as the LAST task**
>    It is the "round is over" signal; without it a run can still wait until the timeout (2 hours by default).

1. Fix MAA / MaaEnd as above.
2. **Settings → Paths**: `MAA.exe`, `MaaEnd.exe` (empty = skip that phase).
3. **Settings → Process & timeouts**: emulator process (`MuMuPlayer.exe`), game process (`Endfield.exe`).
4. **Settings → Foreground handling**: pick a strategy; the blacklist accepts picked processes.
5. **Settings → Run control**: control mode (default "config injection"), MaaEnd instance, stage retries, update timing, whether to keep the upstreams after a run.
6. **Settings → Matching & clicking** (compatibility mode only): appears when control mode is "Click"; keep defaults first, adjust threshold / scale range or capture templates only when it misses.
7. **Settings → Schedule & push**: times, ServerChan SendKey, webhook, system notifications.
8. **Settings → Appearance**: theme / accent / language / background / UI scale.
9. **Settings → General**: autostart, close behaviour, update checks, auto download.
10. Back on the home page press **▶ Run now**; failures are in the home log or `logs/.../task.log`.

---

## ⚙️ Configuration

Stored in `config/config.json` (inside the install folder for installed builds); in-app changes apply immediately. **Do not edit it while the app is running** — the app rewrites the whole file.

| Field | Meaning | Default |
| --- | --- | --- |
| `maa_path` | MAA executable; empty skips the MAA phase | `""` |
| `maaend_path` | MaaEnd executable; empty skips the MaaEnd phase | `""` |
| `emulator_proc` | Emulator process name | `MuMuPlayer.exe` |
| `pc_game_proc` | PC game process name | `Endfield.exe` |
| `foreground_action` | `none` / `kill_all` / `blacklist` | `none` |
| `blacklist_apps` | Comma-separated process names | `""` |
| `enable_schedule` | Enable scheduling | `false` |
| `schedule_times` | Time slots, e.g. `["08:00", "20:30"]`; empty = use `execute_time` | `[]` |
| `schedule_weekdays` | 1=Mon … 7=Sun; empty = every day | `[]` |
| `serverchan_key` / `webhook_url` | Push credentials | `""` |
| `wait_timeout` | Matching timeout (s) | `60` |
| `game_start_timeout` / `game_exit_timeout` | Wait for game start / exit (s) | `120` / `7200` |
| `retry_times` / `retry_interval` | Retry policy | `3` / `30` |
| `min_emulator_runtime` | An emulator dying sooner counts as failure (0 = off) | `60` |
| `match_threshold` | Similarity threshold 0–1 | `0.80` |
| `match_scale_min` / `match_scale_max` | Scale search range | `0.60` / `2.00` |
| `click_mode` | `sendinput` (real click) / `postmessage` (background, experimental) | `sendinput` |
| `click_activate` | Bring the target to the foreground before clicking | `true` |
| `click_verify` | Compare pixels after the click to confirm it landed | `true` |
| `template_dir` | Custom template folder (empty = `config/templates`) | `""` |
| `theme` / `accent_color` / `language` | Appearance | `system` / `#3b82f6` / `zh_CN` |
| `ui_scale` | UI scale (1.0 / 1.25 / 1.5) | `1.0` |
| `auto_start` / `minimize_to_tray` / `kill_on_exit` | Behaviour toggles | `false` / `true` / `true` |
| `log_retention_days` | Keep logs for N days (0 = keep all) | `90` |
| `auto_check_update` / `auto_download_update` / `update_channel` | Update behaviour | `true` / `false` / `stable` |

> **Editing announcements needs no release**: edit `MaaAutoProject/resources/announcements.json` and push to `main`. Clients fetch it in the background (falling back to a jsDelivr mirror) and cache it. New ids show as unread; when you only change the text, bump the top-level `updated` so readers see the red dot again.

---

## 🔔 Notifications

**ServerChan**: with a SendKey, each finished run sends a WeChat message containing the log; the settings page has a "Test" button.

**Generic webhook**: POSTs JSON to your URL:

```http
Content-Type: application/json

{
  "title": "09-18 | MaaAuto success",
  "content": "Start: 2026-09-18 08:00:00, End: 2026-09-18 10:23:45\n\nLast log output:\n...\n\nFrom MaaAuto"
}
```

**System notifications**: tray balloons for success / failure / aborted, toggleable in settings.

---

## 🔄 Updates and versions

Current version **1.4.6**; see [CHANGELOG.md](CHANGELOG.md).

Any installed 1.x can update in-app: the delta package `MaaAuto_delta_v{old}_to_{new}.zip` is preferred (usually under 1 MB; skipping versions chains deltas automatically), falling back to the full `MaaAuto_payload_v{version}.zip`; failures roll back.

An update replaces program files only — `config/`, `logs/` and `.maaauto.json` are always kept. A failed update rolls back and writes `config/upgrade_failed.flag`, which the next launch reports.

### Channels

| Channel | Behaviour |
| --- | --- |
| **stable** (default) | Only GitHub `releases/latest`, i.e. official releases |
| **beta** | Reads the release list including pre-releases (`1.0.1b1` / `1.0.1rc1`) |

> Channels only change *which* versions are visible; the update mechanism is identical. To go back to stable, wait for a higher stable version or reinstall the full package.

---

## 🛠️ FAQ

**Q1 Matching keeps failing.** Look at `logs/find_fail_*.png` (a screenshot is saved on timeout), then run "Test match" and check the score: lower the threshold to 0.70 and widen the scale range for misses; tune the click offset for off-centre hits; re-capture a template when the UI language/theme differs a lot (saved under `config/templates/`, which overrides bundled templates). `py diagnose.py` prints screen resolution, DPI awareness, matching parameters and template sources.

**Q2 I started the app after the scheduled time — will it still run?** Yes. It checks every 10 seconds and catches up once for a slot that has passed and has not run today.

**Q2b Autostart is enabled but nothing happens at sign-in.** Since 1.4.5 the installed build uses the `MaaAuto` scheduled task (at logon, highest privileges) instead of the Run key, because the executable requires administrator rights and a Run key cannot launch an elevated program. Check "Task Scheduler → Task Scheduler Library" for `MaaAuto` with "Last Run Result" `0x0`; if security software blocks it, whitelist `MaaAuto.exe` or toggle the setting off/on to recreate the task.

**Q3 No push after a run.** Check SendKey / webhook with the "Test" button.

**Q4 MAA / MaaEnd is already running — will it launch twice?** No. A running instance is brought to the foreground instead.

**Q5 The window is up but buttons do not respond.** Usually a run is in progress; the home button shows "■ Stop".

**Q6 How do I really quit?** The X button minimises to tray; right-click the tray icon → Quit.

**Q7 The app will not start with the Microsoft Store Python.** The Store build's `sys.executable` is a forwarder with odd permissions and paths. Use the python.org build.

**Q8 The app will not start after a failed update.** Check for a leftover `config/.upgrading`; it is cleaned after 5 minutes, or delete it manually. Details are in `config/upgrade_failed.flag` and `logs/upgrading.log`.

**Q9 Update checks are slow.** Network calls run on background threads and never block the UI; the GitHub API is unreliable on some networks — retry later.

**Q10 "Missing `serverchan_sdk`".** Incomplete install: reinstall the full package or use a webhook.

---

## ⚠️ About "close all foreground apps"

This strategy only runs when **you** select it: before a task it force-closes every visible foreground app (system processes, the emulator, MAA / MaaEnd and other allowlisted ones excluded).

> **Unsaved Word / Excel / Notepad / browser content will be lost.** Use it only on a dedicated machine.

The default strategy is "do nothing".

---

## ⚠️ Disclaimer

- This project is for learning Python automation, GUI development and process management.
- It is not affiliated with MAA or MaaEnd; it is a third-party scheduler.
- Do not use it commercially.
- Any direct or indirect consequence of using this software (game account bans, data loss, system issues) is your own responsibility.

---

## 🔌 Contract with the installer

Installed builds are installed, updated and removed by [MaaAuto-Installer](https://github.com/mmccz/MaaAuto-Installer). The two sides only hand-shake through three files:

| File | Written by | Read by | Meaning |
| --- | --- | --- | --- |
| `config/.upgrading` | updater | app (startup + 1 s polling) | present = exit; the updater deletes it on the normal path, leftovers are cleaned after 5 minutes |
| `config/upgrade_failed.flag` | updater | app (300 ms after start) | JSON; the app reports it and deletes it |
| `config/last_launch_args.json` | app | updater | restores `--autostart` and friends on restart |

Release assets: `MaaAuto_Setup_v*.exe` (full installer), `MaaAuto_Online_v*.exe` (bootstrap), `MaaAuto_payload_v*.zip` (payload used by the updater), `MaaAuto_delta_v{old}_to_{new}.zip` (file-level delta, a few hundred KB, chained across versions) and `SHA256SUMS.txt`.

> Releasing: push both repositories, push a `v*` tag; CI builds the assets above (Python 3.15) and publishes the Release directly using `RELEASE_NOTES.md` as the body (pre-release tags are marked as such).

The values `APP_UPDATE_API`, `APP_MIN_INSTALLER_VERSION` and `APP_PAYLOAD_ASSET_PREFIX` in `app_info.py` are a **frozen contract** with `installer/contract.py`: changing any of them is a protocol change and requires releasing both repositories together.

---

## 📄 License and repositories

**MIT License**, see [LICENSE](LICENSE).

| Repository | Purpose |
| --- | --- |
| [MaaAuto-Tool-works](https://github.com/mmccz/MaaAuto-Tool-works) | The app (this repo) |
| [MaaAuto-Installer](https://github.com/mmccz/MaaAuto-Installer) | Installer / updater / uninstaller |
| [CHANGELOG.md](CHANGELOG.md) | Per-version changes |
