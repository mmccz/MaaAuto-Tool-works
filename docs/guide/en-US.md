# MaaAuto User Guide (English)

> Applies to **v1.4.6** (2026-11-01)｜[简体中文](zh-CN.md)｜[Back to README](../../README.en.md)
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

MaaAuto is a Windows **scheduling shell**: at the time you set it launches [MAA](https://github.com/MaaAssistantArknights/MaaAssistantArknights) or [MaaEnd](https://github.com/MaaEnd/MaaEnd), lets them finish the daily routine, and pushes the result to WeChat or a webhook.

**Since 2.0 it no longer screenshots-and-clicks**: MAA is driven by **config injection** — "Startup → Run directly" is switched on in the scheme MAA already uses, then MAA is started and connects to the emulator on its own; MaaEnd is driven from the **command line** (`--autostart --instance <name> --quit-after-run`). The result is judged from MAA's `debug/gui.log` and MaaEnd's stdout, distinguishing all done / partially failed / emulator unreachable / no tasks selected / timeout / stopped.

Upstream redesigns, theme changes and window resizes can no longer break a run; the 1.x vision/click path is kept as a compatibility mode you can switch back to.

It contains **no game logic**: it does not patch the game, read memory, or replay input sequences. It does three things — **start on schedule, drive the upstreams, judge and report**.

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
| Disk | Installer ~62 MB, ~275 MB installed (bundled PySide6), plus log space (retention is configurable) |
| Display | 1920×1080 or better; works at 125% / 150% scaling |
| External apps | MAA and/or MaaEnd, plus an Android emulator (e.g. MuMu) |
| Network | Needed for update checks, announcements and push; unattended runs can be offline |

> Only MAA with "exit emulator when done" enabled can be driven correctly — see the next section.

---

## 3. Install

### 3.1 Installer (recommended)

1. Open [Releases](https://github.com/mmccz/MaaAuto-Tool-works/releases/latest);
2. Download `MaaAuto_Setup_v<version>.exe` (~62 MB);
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
   Otherwise the emulator keeps holding memory and ADB after the tasks. 2.0 judges the end from MAA's log instead, but the switch is still required — MAA finishes cleanly and the next round does not have to fight over the same emulator.
2. **MaaEnd's task list must end with "Close program" or "Close emulator"**.
   Order matters: it must be the last task, or MaaEnd closes itself before finishing. It is also the "round is over" signal: 2.0 additionally watches stdout task markers, but without it a run can still wait until timeout.
3. **Set both paths correctly**: `MAA.exe` and `MaaEnd.exe`.

Do steps 1–2 before the first "Run now" — that is what makes the first run succeed.

---

## 5. Tour of the UI

Three pages:

| Page | Contents |
| --- | --- |
| **Home** | Status, last/next run, run count, live log panel (clearable), "Run now / Stop", announcements, tutorial |
| **Settings** | Eight groups: paths, run control, process & timeouts, matching & clicking (compatibility mode), foreground handling, schedule & push, appearance, general; jump chips at the top |
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

### 6.2 Run control (new in 2.0)

| Setting | Default | Notes |
| --- | --- | --- |
| Control mode | Config injection | "Inject" writes MAA's config before launch (recommended); "Click" is the 1.x vision/click path (compatibility mode) |
| MaaEnd instance | Empty = last used | Passed as `--autostart --instance <name>`; pick the right one when MaaEnd holds several instances |
| Stage retries | 3 / 30 s | Classified backoff (30 / 60 / 120 s); repeated identical failures trip a circuit breaker |
| Update timing | Between two runs | A new version never interrupts the current run; after a failure auto-retry pauses for 24 hours |
| Keep upstreams after a run | Off | Off = each stage closes its own process (MAA / MaaEnd / Hypergryph launcher); on = keep them for debugging |
| Game launcher process | `Games.exe` | Tree-killed with `taskkill /F /T` when the MaaEnd stage ends (children included); keep `Games.exe` only — `Launcher.exe` is the bootstrap; empty = leave it alone |

> The matching/clicking group only appears when control mode is "Click" (values are kept and restored when you switch back).

### 6.3 Process & timeouts

| Setting | Default | Notes |
| --- | --- | --- |
| Emulator process | `MuMuPlayer.exe` | Used to tell whether the emulator is running |
| Game process | `Endfield.exe` | Used to tell whether the game is running |
| Window timeout | 60 s | How long to wait for a window after launch |
| Game start timeout | 120 s | From "start" click to in-game |
| Game exit timeout | 7200 s | Maximum wait for one session |
| Retries / interval | 3 / 30 s | Retry policy when matching fails |
| Min emulator runtime | 60 s | An emulator that dies immediately counts as failure; 0 = off |

### 6.4 Matching & clicking (compatibility mode)

> This group only appears when control mode is "Click". The default config-injection mode does not look at the screen at all, so upstream redesigns cannot break it; if injection ever misbehaves you can switch back to clicking from the Self-check window.

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

### 6.5 Foreground handling

| Mode | Notes |
| --- | --- |
| Do nothing | Leaves other programs alone |
| Close all foreground apps | **High risk**: closes every visible foreground window |
| Close blacklist only | Closes only listed processes (comma separated, e.g. `WeChat.exe,QQ.exe`) |

Keep "Minimize main window during runs" on: MaaAuto's own window can cover MAA's buttons.

### 6.6 Schedule & push

| Setting | Notes |
| --- | --- |
| Enable schedule | Shows "Next run" on the home page |
| Time slots | Multiple times (e.g. 08:00, 20:30); one run per minute at most |
| Weekdays | Only these days trigger; none selected = every day |
| Start with Windows | Launches MaaAuto at sign-in (see §10) |

### 6.7 Appearance

Theme (system/light/dark), accent colour, background image (opacity/blur/fit mode), UI scale (1.0/1.25/1.5, follow the in-app prompt; a restart is usually required), animations, UI language (中文 / English).

### 6.8 General

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

**2.0 (default, `control: "inject"`)**:

```
check config -> back up MAA's config -> write "start the queue directly" -> launch MAA
  -> judge MAA's debug\gui.log -> restore MAA's config
  -> launch MaaEnd with --autostart --instance <name> --quit-after-run -> judge stdout
  -> wrap up (close or keep, per keep_upstream) -> push the result -> write logs
```

An outcome that cannot be judged is never reported as success: a log without a
terminator becomes `LOG_UNKNOWN` and goes through the retry policy.

**Compatibility mode (`control: "click"`, the 1.x behaviour)**: launch the target app →
wait for its window → match and click "Link Start!" and friends → wait for the game
process to exit → apply foreground handling → push the result → write logs.

Tray menu → "Setup check" runs a read-only pass over the current configuration
(paths, empty task queue, MaaEnd's last task, upstream timers). One glance before a
run saves a lot of debugging.

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

**Q3 Matching fails / "Link Start!" not found.** (click mode only)
Use "Test match" to see the score; re-capture the template when it is below the threshold; confirm MAA's UI language and resolution did not change. The default config-injection mode does not look at the screen, so an upstream redesign cannot break it this way.

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
| Clicks do nothing (click mode only) | Window covered / not foreground | Enable click verification, keep "Minimize during runs" on |
| MAA starts but never begins the tasks | No tasks selected / blocked by an update prompt / no readiness marker within 90 s | Read `<MAA dir>\debug\gui.log`; make sure the scheme has tasks; switch to click mode from Self-check if needed |
| "MAA is already running" | 2.0 drives MAA by writing its config and will not take over a running instance | Quit MAA (including the tray icon) and run again |
| Result is "cannot tell" (`LOG_UNKNOWN`) | Upstream changed its closing wording | Judgement rules are updated remotely; restart MaaAuto to fetch them, and export logs if it still fails |
| No autostart after sign-in | Scheduled task blocked by policy | Use the installed build, or start manually |
| Dialogs hard to read in dark theme | Defect in 1.4.5 and older | Fixed in 1.4.6 |
| Update fails | Network drop / outdated installer | Retry; when told the installer is too old, download the full installer |

When in doubt, run "About → Export logs" and attach the archive to the issue.

---

## 14. Privacy, permissions and security

- Config and logs stay **on your machine**, in the install folder; nothing is uploaded;
- Network use is limited to: update checks (GitHub API), announcements, and the push endpoint you configure;
- `MaaAuto.exe` is elevated because it must enumerate/activate other processes' windows and send input;
- It does not read game memory or modify game files; 2.0 **temporarily rewrites MAA's own config** (`config\gui.new.json`) to trigger "run directly" and restores it byte for byte afterwards; a kill or power loss is compensated on the next start;
- SendKey and webhook URLs are credentials: they sit in `config\config.json`, so check logs/config before sharing them.

---

## 15. Feedback and versions

- Issues and feature requests: [Issues](https://github.com/mmccz/MaaAuto-Tool-works/issues)
- Changelog: [CHANGELOG](../../CHANGELOG.md)｜Release notes: [Releases](https://github.com/mmccz/MaaAuto-Tool-works/releases)
- Versioning: big updates bump `X.Y` (1.4.x → 1.5.0), small ones bump `X.Y.Z` (1.4.5 → 1.4.6)
