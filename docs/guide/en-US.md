# MaaAuto User Guide (English)

> Applies to **v1.4.5** (2026-10-31)｜[简体中文](zh-CN.md)｜[Back to README](../../README.en.md)
> This guide is written for users: install, first-run setup, daily unattended runs, and troubleshooting — follow it step by step.

---

## Contents

1. [What it is](#1-what-it-is)
2. [Requirements](#2-requirements)
3. [Install](#3-install)
4. [First run: three hard requirements](#4-first-run-three-hard-requirements)
5. [Tour of the UI](#5-tour-of-the-ui)
6. [Settings reference](#6-settings-reference)
7. [Schedules](#7-schedules)
8. [Runs, logs and notifications](#8-runs-logs-and-notifications)
9. [Updates](#9-updates)
10. [Start with Windows](#10-start-with-windows)
11. [Moving, uninstalling, cleaning up](#11-moving-uninstalling-cleaning-up)
12. [FAQ](#12-faq)
13. [Troubleshooting](#13-troubleshooting)
14. [Privacy, permissions and security](#14-privacy-permissions-and-security)
15. [Feedback and versions](#15-feedback-and-versions)

---

## 1. What it is

MaaAuto is a Windows **scheduling shell**: at the time you set, it launches [MAA](https://github.com/MaaAssistantArknights/MaaAssistantArknights) or [MaaEnd](https://github.com/MaaEnd/MaaEnd), clicks "Link Start!" / "Start task" by image matching, waits for the game to exit, then pushes the result to WeChat or a webhook.

It contains **no game logic**: it does not patch the game, read memory, or replay input sequences. It does three things — **start on schedule, find-and-click, guard processes**.

| Good fit | Not a fit |
| --- | --- |
| Fixed daily sessions you want fully automated | Multi-instance / multi-account farming |
| Using MAA and MaaEnd side by side | Zero-config "just works" (two paths must be set) |
| Wanting local logs and push reports | Non-Windows users |

---

## 2. Requirements

| Item | Requirement |
| --- | --- |
| OS | Windows 10 / 11 (x64) |
| Privileges | **Install** is per-user by default and needs no admin (only "install for all users" does); **the app** runs elevated, so each launch shows one UAC prompt |
| Disk | ~59 MB installed, plus log space (retention is configurable) |
| Display | 1920×1080 or better; works at 125% / 150% scaling |
| External apps | MAA and/or MaaEnd, plus an Android emulator (e.g. MuMu) |
| Network | Needed for update checks, announcements and push; unattended runs can be offline |

> Only MAA with "exit emulator when done" enabled can be driven correctly — see the next section.

---

## 3. Install

### 3.1 Installer (recommended)

1. Open [Releases](https://github.com/mmccz/MaaAuto-Tool-works/releases/latest);
2. Download `MaaAuto_Setup_v<version>.exe` (~59 MB);
3. Run it and follow the wizard: language → install folder → optional shortcuts → install;
4. Leave "Run MaaAuto" checked to start it right away.

The default folder is `%LOCALAPPDATA%\Programs\MaaAuto`; any folder works (e.g. `D:\MaaAuto`).

| Asset | Purpose |
| --- | --- |
| `MaaAuto_Setup_v<version>.exe` | Full installer |
| `MaaAuto_Payload_v<version>.zip` | Full payload used by the updater (usually no manual download) |
| `MaaAuto_delta_v<old>_to_<new>.zip` | Incremental update, a few hundred KB, picked automatically |
| `MaaAuto_Online_v<version>.exe` | ~2 MB bootstrap: downloads the installer, verifies SHA256, starts the wizard |
| `SHA256SUMS.txt` | SHA256 for every asset |

### 3.2 From source (developers)

```powershell
git clone https://github.com/mmccz/MaaAuto-Tool-works.git
cd MaaAuto-Tool-works\MaaAutoProject
py -m pip install -r requirements.txt
py main.py
```

Python 3.11 or newer (development and CI use 3.15).

### 3.3 Verify the install

- A `MaaAuto` shortcut exists on the desktop / Start menu;
- "Settings → Apps" lists MaaAuto with a version (older entries may be stale; one launch fixes it);
- The tutorial appears on first launch.

---

## 4. First run: three hard requirements

The tutorial calls these out because they are **preconditions**, not suggestions:

1. **In MAA, enable "exit emulator when done"**.
   Otherwise the emulator is still running after the task, MaaAuto never sees the emulator exit, and both this run and the next one fail.
2. **MaaEnd's task list must end with "Close program" or "Close emulator"**.
   Order matters: it must be the last task, or MaaEnd closes itself before finishing. That task is also MaaAuto's signal that MaaEnd is done.
3. **Set both paths correctly**: `MAA.exe` and `MaaEnd.exe`.

Do steps 1–2 before the first "Run now" — that is what makes the first run succeed.

---

## 5. Tour of the UI

Three pages:

| Page | Contents |
| --- | --- |
| **Home** | Status, last/next run, run count, live log panel (clearable), "Run now / Stop", announcements, tutorial |
| **Settings** | Seven groups: paths, process & timeouts, matching & clicking, foreground handling, schedule & push, appearance, general; jump chips at the top |
| **About** | Version info, check for updates, open config/log folders, export logs, project links |

Tray menu: Show, Settings, Stop, Restart, Quit. Whether closing the window keeps the app in the tray depends on "Close to tray".

---

## 6. Settings reference

### 6.1 Paths

| Setting | Notes |
| --- | --- |
| MAA path | `MAA.exe` |
| MaaEnd path | `MaaEnd.exe` (optional; MAA-only setups can leave it empty) |
| ServerChan SendKey | WeChat push, from [serverchan](https://sct.ftqq.com/); empty = no push |
| Webhook URL | Custom HTTP endpoint; can be used together with SendKey |

### 6.2 Process & timeouts

| Setting | Default | Notes |
| --- | --- | --- |
| Emulator process | `MuMuPlayer.exe` | Used to tell whether the emulator is running |
| Game process | `Endfield.exe` | Used to tell whether the game is running |
| Window timeout | 60 s | How long to wait for a window after launch |
| Game start timeout | 120 s | From "start" click to in-game |
| Game exit timeout | 7200 s | Maximum wait for one session |
| Retries / interval | 3 / 30 s | Retry policy when matching fails |
| Min emulator runtime | 60 s | An emulator that dies immediately counts as failure; 0 = off |

### 6.3 Matching & clicking

| Setting | Default | Notes |
| --- | --- | --- |
| Search scope | Target window | Client area only; "screen" searches everything |
| Match threshold | 0.80 | Higher = stricter |
| Scale range / step | 0.60–2.00 / 0.05 | Covers DPI and window-size differences |
| Click mode | SendInput | Real mouse click; PostMessage sends background messages |
| Activate before click / restore cursor | On | Ensures the click lands, without stealing your mouse |
| Click verification | On | Compares pixels afterwards to confirm the click worked |
| Template folder | Empty = built-in | Point at your own templates |
| Capture template / Test match | — | Grab a region from screen; try a match with current templates |

> If "Link Start!" suddenly stops matching after a MAA update, run "Test match" and re-capture the template when the score is below the threshold (MAA has changed that button's rendering before).

### 6.4 Foreground handling

| Mode | Notes |
| --- | --- |
| Do nothing | Leaves other programs alone |
| Close all foreground apps | **High risk**: closes every visible foreground window |
| Close blacklist only | Closes only listed processes (comma separated, e.g. `WeChat.exe,QQ.exe`) |

Keep "Minimize main window during runs" on: MaaAuto's own window can cover MAA's buttons.

### 6.5 Schedule & push

| Setting | Notes |
| --- | --- |
| Enable schedule | Shows "Next run" on the home page |
| Time slots | Multiple times (e.g. 08:00, 20:30); one run per minute at most |
| Weekdays | Only these days trigger; none selected = every day |
| Start with Windows | Launches MaaAuto at sign-in (see §10) |

### 6.6 Appearance

Theme (system/light/dark), accent colour, background image (opacity/blur/fit mode), UI scale (1.0/1.25/1.5, follow the in-app prompt; a restart is usually required), animations, UI language (中文 / English).

### 6.7 General

System notifications, close to tray, close related processes on exit, auto check for updates, auto download, update channel (stable / beta), log retention in days (default 90; 0 = keep everything).

---

## 7. Schedules

1. Settings → Schedule & push → enable "Schedule";
2. Add time slots and pick times; tick weekdays if you do not want every day;
3. Check "Next run" on the home page;
4. At the due minute the run starts, then the result is pushed and the run counter increases.

The same minute never runs twice: each `date + hour:minute` triggers once, and a manual run in that minute suppresses the scheduled one.

**Missed slots are caught up**: the app checks every 10 seconds, so if today's slot has passed and nothing ran yet, it runs once shortly after startup.

---

## 8. Runs, logs and notifications

### 8.1 What a run does

Launch the target app → wait for its window → match and click "Link Start!" and friends → wait for the game process to exit → apply foreground handling → push the result → write logs.

### 8.2 Where the logs are

```
<install dir>\logs\<year>\<month>\<day>\run_<N>_<HHMMSS>\task.log
```

A failed run also leaves a screenshot of the moment (`find_fail_*.png`) next to the log.

"Clear" on the home page clears the on-screen pane only; "About → Export logs" packages the logs for sharing.

### 8.3 Notifications

With SendKey or a webhook configured, each run sends one message: start time, end time, status (success/failure) and a log excerpt. A failed push never affects the run itself.

---

## 9. Updates

- **Manual**: "Check for updates" on the About page;
- **Automatic**: Settings → General → auto check (optionally auto download);
- **Incremental**: new versions usually ship as a few-hundred-KB delta; the updater decides between delta and full payload;
- The running app is asked to exit; the updater replaces files and restarts it.

The `beta` channel includes pre-releases; use `stable` for everyday use.

---

## 10. Start with Windows

| Install type | Mechanism | How to check |
| --- | --- | --- |
| Installed build | Logon scheduled task `MaaAuto`, run with highest privileges (so no UAC prompt) | `schtasks /Query /TN MaaAuto /V /FO LIST` |
| Running from source | `MaaAuto` value under `HKCU\...\CurrentVersion\Run` | `reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v MaaAuto` |

The installed build uses a scheduled task because `MaaAuto.exe` requires administrator rights and a Run key cannot start an elevated program. A leftover Run key from older versions is migrated on upgrade.

If nothing appears after sign-in, open "About → Open log folder" and follow §13.

---

## 11. Moving, uninstalling, cleaning up

- **Move**: install again into the new folder; copy `config\` and `logs\` from the old one manually.
- **Uninstall**: Settings → Apps → MaaAuto → Uninstall. **Config and logs are kept** (user data is never deleted); delete the install folder to remove everything.
- **Lost shortcut / "Settings → Apps" entry**: run `repair_integration.py --dir <install dir>` from the installer repository.

---

## 12. FAQ

**Q1 It asks for administrator rights on start.**
Expected: it manipulates other windows and processes. Accept UAC.

**Q2 "Run now" does nothing.**
Check both paths, then that MAA has "exit emulator when done" enabled, then read the home log for a Chinese error line.

**Q3 Matching fails / "Link Start!" not found.**
Use "Test match" to see the score; re-capture the template when it is below the threshold; confirm MAA's UI language and resolution did not change.

**Q4 No push after a run.**
Check SendKey/webhook and your network; a failed push does not fail the run, and the log records why.

**Q5 The emulator stays open after a run.**
MAA's "exit emulator when done" is off, or MaaEnd's list does not end with "Close program / Close emulator".

**Q6 UI too small / cramped.**
Settings → Appearance → UI scale; restart afterwards.

**Q7 I closed the window — is it gone?**
Check "Close to tray". If on, it lives in the tray; right-click the tray icon to show it.

**Q8 Config still exists after uninstall.**
By design (user data is preserved). Delete the install folder to remove it.

**Q9 Can I run several instances?**
No. One MaaAuto instance drives one MAA or one MaaEnd.

**Q10 Do updates lose my settings?**
No. Config and logs live in `config\` and `logs\` inside the install folder and survive overwrite installs and delta updates.

---

## 13. Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| "Template missing" | Template file deleted/renamed | Restore the built-in template or re-capture |
| "Window not visible" | Target minimised or off-screen | Restore the window; avoid RDP sessions |
| "Emulator failed to start" | Emulator died instantly / no ADB | Start the emulator manually once |
| Stuck on "waiting for window" | Wrong process name | Re-pick it with "Pick process" |
| Clicks do nothing | Window covered / not foreground | Enable click verification, keep "Minimize during runs" on |
| No autostart after sign-in | Scheduled task blocked by policy | Use the installed build, or start manually |
| Dialogs hard to read in dark theme | Defect in 1.4.5 and older | Fixed on the development branch; ships with the next version |
| Update fails | Network drop / outdated installer | Retry; when told the installer is too old, download the full installer |

When in doubt, run "About → Export logs" and attach the archive to the issue.

---

## 14. Privacy, permissions and security

- Config and logs stay **on your machine**, in the install folder; nothing is uploaded;
- Network use is limited to: update checks (GitHub API), announcements, and the push endpoint you configure;
- `MaaAuto.exe` is elevated because it must enumerate/activate other processes' windows and send input;
- It does not read game memory, inject code, or modify game files;
- SendKey and webhook URLs are credentials: they sit in `config\config.json`, so check logs/config before sharing them.

---

## 15. Feedback and versions

- Issues and feature requests: [Issues](https://github.com/mmccz/MaaAuto-Tool-works/issues)
- Changelog: [CHANGELOG](../../CHANGELOG.md)｜Release notes: [Releases](https://github.com/mmccz/MaaAuto-Tool-works/releases)
- Versioning: big updates bump `X.Y` (1.4.x → 1.5.0), small ones bump `X.Y.Z` (1.4.5 → 1.4.6)
