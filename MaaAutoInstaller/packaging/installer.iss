; ============================================================================
; MaaAuto full installer (Inno Setup 6.5+)
;
; Invoked by build_release.py, which passes in through /D:
;   MyAppVersion / MyInstallerVersion / MyUpdateApi
;   MyPayloadPrefix / MyMinInstaller / MyPayloadDir / MyOutputDir
;   MyIcon / MySetupBase
;
; Language files: ChineseSimplified.isl from the official Inno Setup issrc repo
; ============================================================================

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#ifndef MyInstallerVersion
  #define MyInstallerVersion "0.0.0"
#endif
#ifndef MyUpdateApi
  #define MyUpdateApi "https://api.github.com/repos/mmccz/MaaAuto-Tool-works/releases/latest"
#endif
#ifndef MyPayloadPrefix
  #define MyPayloadPrefix "MaaAuto_payload_v"
#endif
#ifndef MyMinInstaller
  #define MyMinInstaller "0.0.0"
#endif
#ifndef MyPayloadDir
  #define MyPayloadDir "..\_build\payload"
#endif
#ifndef MyOutputDir
  #define MyOutputDir "..\dist"
#endif
#ifndef MyIcon
  #define MyIcon "..\resources\icon.ico"
#endif
#ifndef MySetupBase
  #define MySetupBase "MaaAuto_Setup_v" + MyAppVersion + "-Windows-x64"
#endif
; Inno VersionInfoVersion accepts digits only, so prerelease b1/rc1 must be stripped
#ifndef MyVersionQuad
  #define MyVersionQuad "0.0.0.0"
#endif

[Setup]
AppId={{6F3A2C1E-8B4D-4E7A-9C15-3D02A7B9E4C1}
AppName=MaaAuto
AppVersion={#MyAppVersion}
AppVerName=MaaAuto {#MyAppVersion}
AppPublisher=mmccz
AppPublisherURL=https://github.com/mmccz/MaaAuto-Tool-works
AppSupportURL=https://github.com/mmccz/MaaAuto-Tool-works/issues
AppUpdatesURL=https://github.com/mmccz/MaaAuto-Tool-works/releases
VersionInfoVersion={#MyVersionQuad}
VersionInfoDescription=MaaAuto Setup
DefaultDirName={autopf}\MaaAuto
DefaultGroupName=MaaAuto
DisableProgramGroupPage=yes
DisableWelcomePage=no
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#MyOutputDir}
OutputBaseFilename={#MySetupBase}
SetupIconFile={#MyIcon}
UninstallDisplayIcon={app}\MaaAuto.exe
UninstallDisplayName=MaaAuto
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
AllowNoIcons=yes

[Languages]
Name: "cn"; MessagesFile: "languages\ChineseSimplified.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
cn.CreateStartMenuIcon=创建开始菜单快捷方式
en.CreateStartMenuIcon=Create a Start Menu shortcut

[Tasks]
; The Start Menu shortcut is optional (1.0.6): some users only use a desktop
; icon / taskbar and do not want a Start Menu entry; checked by default so
; existing users see no behaviour change after upgrading.
Name: "startmenuicon"; Description: "{cm:CreateStartMenuIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#MyPayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\MaaAuto"; Filename: "{app}\MaaAuto.exe"; Tasks: startmenuicon
Name: "{group}\{cm:UninstallProgram,MaaAuto}"; Filename: "{uninstallexe}"; Tasks: startmenuicon
Name: "{autodesktop}\MaaAuto"; Filename: "{app}\MaaAuto.exe"; Tasks: desktopicon

; Best-effort cleanup of the Start Menu group on uninstall.
;
; Measured (verified on 1.0.5): the uninstaller deletes the "Uninstall MaaAuto"
; shortcut but often leaves "MaaAuto.lnk" and the whole group directory behind
; (the Inno uninstall log does not clear them, especially when upgrading first
; and uninstalling later, or while the shell holds a handle on that directory).
; On this machine the system took minutes to reclaim it, which the user sees as
; "uninstall left junk". Just delete the entire {group} directory with
; filesandordirs -- that directory belongs to this program only.
[UninstallDelete]
Type: filesandordirs; Name: "{group}"

[Run]
; shellexec is required: the main app manifest demands administrator, and
; starting it directly with CreateProcess fails with "error 740, the requested
; operation requires elevation". ShellExecute goes through UAC.
Filename: "{app}\MaaAuto.exe"; Description: "{cm:LaunchProgram,MaaAuto}"; Flags: nowait postinstall skipifsilent shellexec

[Code]
procedure WriteManifest();
var
  Dir, DirEsc, UninstEsc, Json, ManifestPath, InstalledAt: String;
begin
  Dir := ExpandConstant('{app}');
  DirEsc := Dir;
  StringChangeEx(DirEsc, '\', '\\', True);
  { The Inno uninstaller is always named unins000.exe (renaming is not supported), so write the real path }
  UninstEsc := ExpandConstant('{uninstallexe}');
  StringChangeEx(UninstEsc, '\', '\\', True);
  InstalledAt := GetDateTimeString('yyyy-mm-dd hh:nn:ss', #0, #0);

  Json :=
    '{' + #13#10 +
    '  "version": "{#MyAppVersion}",' + #13#10 +
    '  "installer_version": "{#MyInstallerVersion}",' + #13#10 +
    '  "manifest_version": 3,' + #13#10 +
    '  "install_dir": "' + DirEsc + '",' + #13#10 +
    '  "app_exe": "' + DirEsc + '\\MaaAuto.exe",' + #13#10 +
    '  "uninstall_exe": "' + UninstEsc + '",' + #13#10 +
    '  "upgrade_exe": "' + DirEsc + '\\upgrade.exe",' + #13#10 +
    '  "requirements_hash": "",' + #13#10 +
    '  "mirror": "",' + #13#10 +
    '  "installed_at": "' + InstalledAt + '",' + #13#10 +
    '  "updated_at": "' + InstalledAt + '",' + #13#10 +
    '  "release_channel": "stable",' + #13#10 +
    '  "last_checked_at": "",' + #13#10 +
    '  "last_upgrade_from": "",' + #13#10 +
    '  "source_hash": "",' + #13#10 +
    '  "extra": {' + #13#10 +
    '    "github_url": "https://github.com/mmccz/MaaAuto-Tool-works",' + #13#10 +
    '    "update_api": "{#MyUpdateApi}",' + #13#10 +
    '    "release_channel": "stable",' + #13#10 +
    '    "launch_args": [],' + #13#10 +
    '    "payload_asset_prefix": "{#MyPayloadPrefix}",' + #13#10 +
    '    "min_installer_version": "{#MyMinInstaller}"' + #13#10 +
    '  }' + #13#10 +
    '}';

  ManifestPath := ExpandConstant('{app}\.maaauto.json');
  if not SaveStringToFile(ManifestPath, Json, False) then
    MsgBox('写入 .maaauto.json 失败，自动升级可能不可用。' + #13#10 + ManifestPath,
           mbError, MB_OK);
end;

{ 2.x elevated through the RUNASADMIN compatibility flag; 3.0 embeds the
  manifest in the exe instead. Clear registry leftovers from old versions here
  to avoid repeated prompts. }
procedure CleanLegacyRegistry();
var
  ExePath: String;
begin
  RegDeleteValue(HKCU,
    'Software\Microsoft\Windows\CurrentVersion\Run', 'MaaAuto');
  ExePath := ExpandConstant('{app}\MaaAuto.exe');
  RegDeleteValue(HKCU,
    'Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers', ExePath);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    WriteManifest();
    CleanLegacyRegistry();
  end;
end;

{ Whether MaaAuto.exe is still running.
  The uninstaller has ParamStr but no process API, so use the tasklist + find
  exit code. }
function IsAppRunning(): Boolean;
var
  ResultCode: Integer;
begin
  Result := False;
  if Exec(ExpandConstant('{cmd}'),
       '/c tasklist /FI "IMAGENAME eq MaaAuto.exe" /NH | find /I "MaaAuto.exe" >nul',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    Result := (ResultCode = 0);
end;

{ Ask the running main app to exit gracefully.

Why use the .upgrading handshake instead of a plain taskkill:
this installer is per-user by default and the uninstaller does **not** elevate,
while the main exe manifest requires administrator. A low-integrity process
cannot kill a high-integrity one (taskkill returns "access denied") and the
files cannot be removed cleanly -- exactly the "uninstall still leaves lots of
stuff" users reported. The main app polls config\.upgrading every second;
writing this file makes it save config and exit by itself, with no UAC and no
half-written state. }
function AskAppToExit(TimeoutMs: Integer): Boolean;
var
  FlagPath: String;
  Waited: Integer;
begin
  FlagPath := ExpandConstant('{app}\config\.upgrading');
  ForceDirectories(ExpandConstant('{app}\config'));
  SaveStringToFile(FlagPath, 'uninstall', False);

  Waited := 0;
  while (Waited < TimeoutMs) and IsAppRunning() do
  begin
    Sleep(300);
    Waited := Waited + 300;
  end;

  Result := not IsAppRunning();
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir, FlagPath: String;
  Purge: Boolean;
  ResultCode: Integer;
  I: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    CleanLegacyRegistry();

    { Stop the main app first: it may be running and holding DLLs in _internal,
      otherwise Inno cannot delete the files and the user sees "uninstall was
      incomplete". Order: handshake so the app exits by itself -> taskkill if it
      is still there (works at the same integrity level) -> fallback message. }
    if IsAppRunning() then
    begin
      if not AskAppToExit(12000) then
      begin
        Exec(ExpandConstant('{cmd}'),
             '/c taskkill /F /IM MaaAuto.exe /T >nul 2>&1', '',
             SW_HIDE, ewWaitUntilTerminated, ResultCode);
        Sleep(1000);
      end;
    end;

    { /PURGEDATA forces deleting user data too; otherwise ask, default is keep.
      The uninstaller has no CmdLineParamExists, so iterate over ParamStr. }
    Purge := False;
    for I := 1 to ParamCount do
      if CompareText(ParamStr(I), '/PURGEDATA') = 0 then
        Purge := True;

    if not Purge then
      Purge := SuppressibleMsgBox(
        '是否同时删除配置与日志？' + #13#10 +
        '选择“否”将保留 config 与 logs 目录，重新安装后可继续使用。',
        mbConfirmation, MB_YESNO, IDNO) = IDYES;

    if Purge then
    begin
      DataDir := ExpandConstant('{app}\config');
      DelTree(DataDir, True, True, True);
      DataDir := ExpandConstant('{app}\logs');
      DelTree(DataDir, True, True, True);
    end
    else
    begin
      { Clear the handshake file when keeping user data, otherwise the main app exits as soon as it starts after a reinstall }
      DeleteFile(ExpandConstant('{app}\config\.upgrading'));
    end;

    DeleteFile(ExpandConstant('{app}\.maaauto.json'));
    { .old exe and temp dirs left behind by upgrades }
    DeleteFile(ExpandConstant('{app}\upgrade.exe.old'));

    { Tell the user explicitly when the process really would not exit, instead of leaving a half-removed directory }
    if IsAppRunning() then
      MsgBox('MaaAuto 仍在运行，可能无法结束它（权限不足）。' + #13#10 +
             '请手动退出程序后重新卸载，否则部分文件会残留。',
             mbError, MB_OK);
  end;
end;
