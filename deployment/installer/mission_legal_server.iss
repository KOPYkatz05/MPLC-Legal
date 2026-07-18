#ifndef AppVersion
  #error AppVersion must be supplied by deployment/build_server_installer.ps1
#endif
#ifndef AppVersionNumeric
  #error AppVersionNumeric must be supplied by deployment/build_server_installer.ps1
#endif
#ifndef ServerPackageDir
  #error ServerPackageDir must point to the frozen MissionLegalServer directory
#endif
#ifndef MaintenanceExe
  #error MaintenanceExe must point to MissionLegalServerMaintenance.exe
#endif
#ifndef OutputDir
  #error OutputDir must be supplied by deployment/build_server_installer.ps1
#endif

[Setup]
AppId={{8A39739D-CBD2-4C38-AE5D-9DE7E69B29D5}
AppName=Mission Legal Server
AppVersion={#AppVersion}
AppVerName=Mission Legal Server {#AppVersion}
AppPublisher=Mission Legal
DefaultDirName={autopf}\Mission Legal\Server
DefaultGroupName=Mission Legal
DisableDirPage=yes
DisableProgramGroupPage=yes
DirExistsWarning=no
UsePreviousAppDir=yes
Uninstallable=yes
UninstallDisplayIcon={app}\MissionLegalServer.exe
UninstallDisplayName=Mission Legal Server
UninstallLogMode=append
UpdateUninstallLogAppName=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
CloseApplications=no
RestartApplications=no
RestartIfNeededByRun=no
AllowCancelDuringInstall=no
SetupLogging=yes
UninstallLogging=yes
Compression=lzma2/ultra64
SolidCompression=yes
OutputDir={#OutputDir}
OutputBaseFilename=MissionLegalServerSetup-{#AppVersion}
VersionInfoCompany=Mission Legal
VersionInfoDescription=Mission Legal Server installer
VersionInfoProductName=Mission Legal Server
VersionInfoProductVersion={#AppVersion}
VersionInfoVersion={#AppVersionNumeric}
#ifdef SignToolName
SignTool={#SignToolName}
SignedUninstaller=yes
SignToolRetryCount=3
#else
SignedUninstaller=no
#endif

[Files]
; Keep preflight tools first so solid compression does not delay extraction.
#ifdef SignToolName
Source: "{#MaintenanceExe}"; DestName: "MissionLegalServerMaintenance.exe"; Flags: dontcopy noencryption signonce
Source: "{#ServerPackageDir}\MissionLegalServer.exe"; DestDir: "{app}"; Flags: ignoreversion signonce
Source: "{#ServerPackageDir}\MissionLegalServerSetup.exe"; DestDir: "{app}"; Flags: ignoreversion signonce
Source: "{#ServerPackageDir}\MissionLegalService.exe"; DestDir: "{app}"; Flags: ignoreversion signonce
Source: "{#ServerPackageDir}\*"; DestDir: "{app}"; Excludes: "MissionLegalServer.exe,MissionLegalServerSetup.exe,MissionLegalService.exe"; Flags: ignoreversion recursesubdirs createallsubdirs
#else
Source: "{#MaintenanceExe}"; DestName: "MissionLegalServerMaintenance.exe"; Flags: dontcopy noencryption
Source: "{#ServerPackageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
#endif
Source: "server_installer_actions.ps1"; Flags: dontcopy noencryption
Source: "server_installer_rollback.ps1"; Flags: dontcopy noencryption
Source: "server_installer_actions.ps1"; DestDir: "{app}\InstallerSupport"; Flags: ignoreversion
Source: "server_installer_rollback.ps1"; DestDir: "{app}\InstallerSupport"; Flags: ignoreversion

[InstallDelete]
; Remove the old private runtime only after the service and backup gates pass.
; The uninstaller and every ProgramData/user-data path are intentionally absent.
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\InstallerSupport"
Type: files; Name: "{app}\MissionLegalServer.exe"
Type: files; Name: "{app}\MissionLegalServerSetup.exe"
Type: files; Name: "{app}\MissionLegalService.exe"

[Registry]
Root: HKLM; Subkey: "Software\MissionLegal\Server"; ValueType: string; ValueName: "InstallDir"; ValueData: "{app}"; Flags: uninsdeletekey
Root: HKLM; Subkey: "Software\MissionLegal\Server"; ValueType: string; ValueName: "Version"; ValueData: "{#AppVersion}"; Flags: uninsdeletekey

[Code]
const
  ServerAppId = '{8A39739D-CBD2-4C38-AE5D-9DE7E69B29D5}';
  ServiceName = 'MissionLegalServer';

var
  PreflightStarted: Boolean;
  InstallCompleted: Boolean;
  ServiceStateFile: String;
  BinarySnapshotDir: String;
  DatabaseRollbackReceiptPath: String;
  BinarySnapshotCaptured: Boolean;
  BinaryRollbackRestored: Boolean;
  DatabaseBackupCaptured: Boolean;
  DatabaseRollbackRestored: Boolean;
  RollbackFailedClosed: Boolean;
  PriorInstallVersion: String;
  HasPriorRegisteredInstall: Boolean;
  ServerConfiguredBeforeInstall: Boolean;

function ReadVersionNumber(const Value: String; var Index: Integer;
  var Number: Integer): Boolean;
var
  StartIndex: Integer;
  Token: String;
begin
  StartIndex := Index;
  while (Index <= Length(Value)) and (Value[Index] >= '0') and
    (Value[Index] <= '9') do
    Index := Index + 1;
  Token := Copy(Value, StartIndex, Index - StartIndex);
  Result := Token <> '';
  if Result then
  begin
    Number := StrToIntDef(Token, -1);
    Result := Number >= 0;
  end;
end;

function ParseReleaseVersion(const Value: String; var Major, Minor, Patch: Integer;
  var Qualifier: String): Boolean;
var
  CleanValue: String;
  Index: Integer;
  PlusPosition: Integer;
begin
  CleanValue := Trim(Value);
  PlusPosition := Pos('+', CleanValue);
  if PlusPosition > 0 then
    Delete(CleanValue, PlusPosition, Length(CleanValue));
  Index := 1;
  Result := ReadVersionNumber(CleanValue, Index, Major);
  if not Result or (Index > Length(CleanValue)) or (CleanValue[Index] <> '.') then
  begin
    Result := False;
    Exit;
  end;
  Index := Index + 1;
  Result := ReadVersionNumber(CleanValue, Index, Minor);
  if not Result or (Index > Length(CleanValue)) or (CleanValue[Index] <> '.') then
  begin
    Result := False;
    Exit;
  end;
  Index := Index + 1;
  Result := ReadVersionNumber(CleanValue, Index, Patch);
  if not Result then
    Exit;
  Qualifier := Lowercase(Copy(CleanValue, Index, Length(CleanValue)));
  while (Length(Qualifier) > 0) and
    ((Qualifier[1] = '.') or (Qualifier[1] = '-')) do
    Delete(Qualifier, 1, 1);
end;

function ParseQualifier(const Value: String; var Rank, Sequence: Integer): Boolean;
var
  Name: String;
  Index: Integer;
begin
  Name := Lowercase(Value);
  if Name = '' then
  begin
    Rank := 4;
    Sequence := 0;
    Result := True;
    Exit;
  end;
  if Pos('dev', Name) = 1 then
  begin
    Rank := 0;
    Delete(Name, 1, 3);
  end
  else if Pos('alpha', Name) = 1 then
  begin
    Rank := 1;
    Delete(Name, 1, 5);
  end
  else if Pos('a', Name) = 1 then
  begin
    Rank := 1;
    Delete(Name, 1, 1);
  end
  else if Pos('beta', Name) = 1 then
  begin
    Rank := 2;
    Delete(Name, 1, 4);
  end
  else if Pos('b', Name) = 1 then
  begin
    Rank := 2;
    Delete(Name, 1, 1);
  end
  else if Pos('rc', Name) = 1 then
  begin
    Rank := 3;
    Delete(Name, 1, 2);
  end
  else if Pos('post', Name) = 1 then
  begin
    Rank := 5;
    Delete(Name, 1, 4);
  end
  else
  begin
    Result := False;
    Exit;
  end;
  while (Length(Name) > 0) and ((Name[1] = '.') or (Name[1] = '-')) do
    Delete(Name, 1, 1);
  if Name = '' then
    Sequence := 0
  else
  begin
    Index := 1;
    Result := ReadVersionNumber(Name, Index, Sequence) and (Index > Length(Name));
    Exit;
  end;
  Result := True;
end;

function CompareReleaseVersions(const NewVersion, InstalledVersion: String;
  var Comparison: Integer): Boolean;
var
  NewMajor, NewMinor, NewPatch, NewRank, NewSequence: Integer;
  OldMajor, OldMinor, OldPatch, OldRank, OldSequence: Integer;
  NewQualifier, OldQualifier: String;
begin
  Result := ParseReleaseVersion(NewVersion, NewMajor, NewMinor, NewPatch,
    NewQualifier) and ParseReleaseVersion(InstalledVersion, OldMajor, OldMinor,
    OldPatch, OldQualifier);
  if not Result then
    Exit;
  Result := ParseQualifier(NewQualifier, NewRank, NewSequence) and
    ParseQualifier(OldQualifier, OldRank, OldSequence);
  if not Result then
    Exit;
  if NewMajor <> OldMajor then
    Comparison := NewMajor - OldMajor
  else if NewMinor <> OldMinor then
    Comparison := NewMinor - OldMinor
  else if NewPatch <> OldPatch then
    Comparison := NewPatch - OldPatch
  else if NewRank <> OldRank then
    Comparison := NewRank - OldRank
  else
    Comparison := NewSequence - OldSequence;
end;

function GetInstalledVersion: String;
var
  RegistryPath: String;
begin
  Result := '';
  if RegQueryStringValue(HKLM64, 'Software\MissionLegal\Server', 'Version', Result) then
    Exit;
  RegistryPath := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\' +
    ServerAppId + '_is1';
  RegQueryStringValue(HKLM64, RegistryPath, 'DisplayVersion', Result);
end;

function AllowDevelopmentReinstall: Boolean;
begin
  Result := False;
#ifdef DevelopmentBuild
  Result := CompareText(ExpandConstant('{param:ALLOWDEVREINSTALL|0}'), '1') = 0;
#endif
end;

function InitializeSetup: Boolean;
var
  Comparison: Integer;
  ErrorMessage: String;
begin
  Result := True;
  PriorInstallVersion := GetInstalledVersion;
  HasPriorRegisteredInstall := PriorInstallVersion <> '';
  if not HasPriorRegisteredInstall then
    Exit;
  if not CompareReleaseVersions('{#AppVersion}', PriorInstallVersion, Comparison) then
    ErrorMessage := 'Setup cannot safely compare the installed Mission Legal Server ' +
      'version (' + PriorInstallVersion + ') with this package ({#AppVersion}).'
  else if Comparison < 0 then
    ErrorMessage := 'Mission Legal Server {#AppVersion} cannot replace newer installed ' +
      'version ' + PriorInstallVersion + '. Downgrades are blocked.'
  else if (Comparison = 0) and (not AllowDevelopmentReinstall) then
    ErrorMessage := 'Mission Legal Server {#AppVersion} is already installed. ' +
      'Same-version reinstalls are blocked.'
  else
  begin
    if Comparison = 0 then
      Log('WARNING: unpublished development same-version reinstall was explicitly enabled.');
    Exit;
  end;
  Log(ErrorMessage + ' The service has not been stopped and no files were changed.');
  SuppressibleMsgBox(ErrorMessage, mbCriticalError, MB_OK, IDOK);
  Result := False;
end;

function QuoteArgument(const Value: String): String;
begin
  Result := '"' + Value + '"';
end;

function PowerShellExe: String;
begin
  Result := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
end;

function RunProcess(const FileName, Parameters, Description: String): Boolean;
var
  ResultCode: Integer;
begin
  Log(Description + ': ' + FileName + ' ' + Parameters);
  Result := Exec(FileName, Parameters, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  if not Result then
  begin
    Log(Description + ' could not be started.');
    Exit;
  end;
  Result := ResultCode = 0;
  if not Result then
    Log(Description + ' failed with exit code ' + IntToStr(ResultCode) + '.');
end;

function RunServiceAction(const ScriptPath, Action: String; RecordState: Boolean): Boolean;
var
  Parameters: String;
begin
  Parameters := '-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File ' +
    QuoteArgument(ScriptPath) + ' -Action ' + QuoteArgument(Action) +
    ' -InstallDir ' + QuoteArgument(ExpandConstant('{app}')) +
    ' -DataDir ' + QuoteArgument(ExpandConstant('{commonappdata}\MissionLegal')) +
    ' -AppVersion ' + QuoteArgument('{#AppVersion}');
  if RecordState then
    Parameters := Parameters + ' -StateFile ' + QuoteArgument(ServiceStateFile);
  Result := RunProcess(PowerShellExe, Parameters, 'Service action ' + Action);
end;

function RunRollbackAction(const Action: String): Boolean;
var
  Parameters: String;
  ScriptPath: String;
begin
  ScriptPath := ExpandConstant('{tmp}\server_installer_rollback.ps1');
  Parameters := '-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File ' +
    QuoteArgument(ScriptPath) + ' -Action ' + QuoteArgument(Action) +
    ' -InstallDir ' + QuoteArgument(ExpandConstant('{app}')) +
    ' -SnapshotDir ' + QuoteArgument(BinarySnapshotDir);
  Result := RunProcess(PowerShellExe, Parameters, 'Binary rollback action ' + Action);
end;

function PreviousVersion: String;
begin
  { Use the value captured before setup writes any candidate-version registry
    entries. The same exact version is bound into backup and restore receipts. }
  Result := PriorInstallVersion;
  if Result = '' then
    Result := 'unknown';
end;

function RunBackupGate: Boolean;
var
  Parameters: String;
  MaintenancePath: String;
begin
  { Always use the maintenance helper carried by the candidate installer. It
    has no application-startup or migration dependencies and emits one stable,
    versioned metadata contract for both legacy and current upgrades. }
  MaintenancePath := ExpandConstant('{tmp}\MissionLegalServerMaintenance.exe');
  Parameters := 'pre-upgrade-backup' +
    ' --database ' + QuoteArgument(ExpandConstant('{commonappdata}\MissionLegal\app.db')) +
    ' --backup-dir ' + QuoteArgument(ExpandConstant('{commonappdata}\MissionLegal\Backups\Installer')) +
    ' --receipt ' + QuoteArgument(DatabaseRollbackReceiptPath) +
    ' --from-version ' + QuoteArgument(PreviousVersion) +
    ' --to-version ' + QuoteArgument('{#AppVersion}') +
    ' --log-file ' + QuoteArgument(ExpandConstant('{commonappdata}\MissionLegal\Logs\installer-maintenance.log'));
  Result := RunProcess(MaintenancePath, Parameters, 'Verified database backup gate');
end;

function RunDatabaseRollback: Boolean;
var
  Parameters: String;
  MaintenancePath: String;
begin
  MaintenancePath := ExpandConstant('{tmp}\MissionLegalServerMaintenance.exe');
  Parameters := 'restore-pre-upgrade-backup' +
    ' --database ' + QuoteArgument(ExpandConstant('{commonappdata}\MissionLegal\app.db')) +
    ' --backup-dir ' + QuoteArgument(ExpandConstant('{commonappdata}\MissionLegal\Backups\Installer')) +
    ' --receipt ' + QuoteArgument(DatabaseRollbackReceiptPath) +
    ' --from-version ' + QuoteArgument(PreviousVersion) +
    ' --to-version ' + QuoteArgument('{#AppVersion}') +
    ' --log-file ' + QuoteArgument(ExpandConstant('{commonappdata}\MissionLegal\Logs\installer-maintenance.log'));
  Result := RunProcess(MaintenancePath, Parameters,
    'Verified authoritative database rollback');
end;

function ServiceWasRunning: Boolean;
var
  State: AnsiString;
begin
  Result := False;
  if LoadStringFromFile(ServiceStateFile, State) then
    Result := (CompareText(Trim(String(State)), 'running') = 0) or
      (CompareText(Trim(String(State)), 'startpending') = 0);
end;

function ServiceWasAbsent: Boolean;
var
  State: AnsiString;
begin
  Result := LoadStringFromFile(ServiceStateFile, State) and
    (CompareText(Trim(String(State)), 'absent') = 0);
end;

function IsServerConfigured: Boolean;
begin
  Result := FileExists(ExpandConstant('{commonappdata}\MissionLegal\app.db')) and
    FileExists(ExpandConstant('{commonappdata}\MissionLegal\Configuration\server.json'));
end;

procedure RestorePriorVersionRegistry;
var
  RegistryPath: String;
begin
  RegistryPath := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\' +
    ServerAppId + '_is1';
  if HasPriorRegisteredInstall then
  begin
    RegWriteStringValue(HKLM64, 'Software\MissionLegal\Server', 'Version',
      PriorInstallVersion);
    RegWriteStringValue(HKLM64, RegistryPath, 'DisplayVersion', PriorInstallVersion);
  end
  else
    RegDeleteValue(HKLM64, 'Software\MissionLegal\Server', 'Version');
end;

function RestorePriorInstallation: Boolean;
var
  ServiceScript: String;
begin
  if RollbackFailedClosed then
  begin
    Log('Rollback previously failed closed; setup will not retry recovery or ' +
      'start a server executable automatically.');
    Result := False;
    Exit;
  end;
  if BinaryRollbackRestored or (not BinarySnapshotCaptured) then
  begin
    Result := True;
    Exit;
  end;
  ServiceScript := ExpandConstant('{tmp}\server_installer_actions.ps1');
  if ServiceWasAbsent then
  begin
    if not RunServiceAction(ServiceScript, 'Remove', False) then
    begin
      RollbackFailedClosed := True;
      Log('ERROR: The candidate service could not be removed before rollback. ' +
        'Setup will not start any server executable.');
      Result := False;
      Exit;
    end;
  end
  else if not RunServiceAction(ServiceScript, 'Stop', False) then
  begin
    RollbackFailedClosed := True;
    Log('ERROR: The candidate service could not be stopped before rollback. ' +
      'Setup will not start any server executable.');
    Result := False;
    Exit;
  end;
  if not DatabaseRollbackRestored then
  begin
    if (not DatabaseBackupCaptured) or
      (DatabaseRollbackReceiptPath = '') or
      (not RunDatabaseRollback) then
    begin
      RollbackFailedClosed := True;
      Log('ERROR: The authoritative database could not be restored from the ' +
        'verified backup receipt. The prior service will remain stopped. ' +
        'Receipt: ' + DatabaseRollbackReceiptPath + '.');
      Result := False;
      Exit;
    end;
    DatabaseRollbackRestored := True;
    Log('Verified authoritative database rollback completed before binary and ' +
      'service recovery.');
  end;
  if not RunRollbackAction('Restore') then
  begin
    RollbackFailedClosed := True;
    Log('ERROR: The previous application binaries could not be restored. ' +
      'The verified snapshot remains at ' + BinarySnapshotDir + '.');
    Result := False;
    Exit;
  end;
  BinaryRollbackRestored := True;
  RestorePriorVersionRegistry;
  { Re-run the registration action against the restored executable before any
    restart. This also recreates and verifies the managed Private-network
    firewall rule from the preserved server configuration, without applying
    the candidate version's health check to the prior binary. }
  if (not ServiceWasAbsent) and
    (not RunServiceAction(ServiceScript, 'InstallOrUpdate', False)) then
  begin
    Log('The previous binaries were restored, but their service registration ' +
      'or managed firewall rule could not be restored and verified.');
    Result := False;
    Exit;
  end;
  if ServiceWasRunning and
    (not RunServiceAction(ServiceScript, 'StartOnly', False)) then
  begin
    Log('The previous binaries were restored, but their service could not be restarted.');
    Result := False;
    Exit;
  end;
  Result := True;
end;

function RemoveFirewallWithoutHelper: Boolean;
var
  Command: String;
  Parameters: String;
begin
  { Match only the stable internal name and exact legacy/current display name.
    Never use a wildcard or group-wide removal in the uninstall fallback. }
  Command := '$ErrorActionPreference = ''Stop''; ' +
    '$rules = @(); ' +
    '$rules += @(Get-NetFirewallRule -Name ''MissionLegalServerHTTPS'' ' +
      '-ErrorAction SilentlyContinue); ' +
    '$rules += @(Get-NetFirewallRule -DisplayName ''Mission Legal Server HTTPS'' ' +
      '-ErrorAction SilentlyContinue); ' +
    '$rules | Sort-Object -Property Name -Unique | ' +
      'Remove-NetFirewallRule -ErrorAction Stop; ' +
    '$remaining = @(); ' +
    '$remaining += @(Get-NetFirewallRule -Name ''MissionLegalServerHTTPS'' ' +
      '-ErrorAction SilentlyContinue); ' +
    '$remaining += @(Get-NetFirewallRule -DisplayName ''Mission Legal Server HTTPS'' ' +
      '-ErrorAction SilentlyContinue); ' +
    'if ($remaining.Count -ne 0) { throw ''Managed Mission Legal Server ' +
      'firewall rules remain after fallback removal.'' }';
  Parameters := '-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass ' +
    '-Command ' + QuoteArgument(Command);
  Result := RunProcess(PowerShellExe, Parameters,
    'Fallback managed firewall removal during uninstall');
end;

function RemoveServiceWithoutHelper: Boolean;
var
  ServiceRegistryPath: String;
  ScExe: String;
  ServiceRemoved: Boolean;
begin
  ServiceRegistryPath := 'SYSTEM\CurrentControlSet\Services\' + ServiceName;
  if not RegKeyExists(HKLM64, ServiceRegistryPath) then
  begin
    Log('The Mission Legal Server service is already absent.');
    ServiceRemoved := True;
  end;
  if RegKeyExists(HKLM64, ServiceRegistryPath) then
  begin
    ScExe := ExpandConstant('{sys}\sc.exe');
    { A stopped service makes sc.exe stop return a nonzero code. Ignore that
      result and require only the deletion request to succeed. }
    RunProcess(
      ScExe, 'stop ' + QuoteArgument(ServiceName),
      'Fallback service stop during uninstall');
    ServiceRemoved := RunProcess(
      ScExe, 'delete ' + QuoteArgument(ServiceName),
      'Fallback service removal during uninstall');
  end;
  if not ServiceRemoved then
  begin
    Result := False;
    Exit;
  end;
  Result := RemoveFirewallWithoutHelper;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ServiceScript: String;
  RecordInitialServiceState: Boolean;
begin
  Result := '';
  ServiceStateFile := ExpandConstant('{tmp}\mission-legal-service-state.txt');
  BinarySnapshotDir := ExpandConstant(
    '{commonappdata}\MissionLegal\Backups\InstallerBinaries\rollback-{#AppVersion}');
  if DatabaseRollbackReceiptPath = '' then
    DatabaseRollbackReceiptPath := ExpandConstant(
      '{commonappdata}\MissionLegal\Backups\Installer\installer-attempt-') +
      ExtractFileName(ExpandConstant('{tmp}')) + '.json';
  ServerConfiguredBeforeInstall := IsServerConfigured;
  try
    ExtractTemporaryFile('server_installer_actions.ps1');
    ExtractTemporaryFile('server_installer_rollback.ps1');
    ExtractTemporaryFile('MissionLegalServerMaintenance.exe');
  except
    Result := 'Setup could not extract its server maintenance tools. ' +
      'No application files were changed. Details: ' + GetExceptionMessage;
    Exit;
  end;

  { PrepareToInstall can run again after an interactive retry. Preserve the
    state captured before the first stop so cancelling a later failed retry
    still restarts a service that was originally running. }
  RecordInitialServiceState := not PreflightStarted;
  PreflightStarted := True;
  ServiceScript := ExpandConstant('{tmp}\server_installer_actions.ps1');
  if not RunServiceAction(
    ServiceScript, 'Stop', RecordInitialServiceState) then
  begin
    Result := 'Mission Legal Server could not be stopped safely. ' +
      'No application files were changed. Review the setup log and retry.';
    Exit;
  end;
  if (not DatabaseBackupCaptured) and (not RunBackupGate) then
  begin
    Result := 'The authoritative database did not pass the verified pre-upgrade ' +
      'backup gate. No application files were changed. Review the installer ' +
      'maintenance log under ProgramData\MissionLegal\Logs and retry.';
    Exit;
  end;
  DatabaseBackupCaptured := True;
  if not RunRollbackAction('Capture') then
  begin
    Result := 'Setup could not create and verify an independent rollback copy of ' +
      'the installed application binaries. No application files were changed.';
    Exit;
  end;
  BinarySnapshotCaptured := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ServiceScript: String;
begin
  if CurStep = ssPostInstall then
  begin
    ServiceScript := ExpandConstant('{app}\InstallerSupport\server_installer_actions.ps1');
    if ServerConfiguredBeforeInstall then
    begin
      if not RunServiceAction(ServiceScript, 'InstallOrUpdate', False) then
      begin
        RestorePriorInstallation;
        RaiseException('The Mission Legal Server service could not be installed or updated. ' +
          'The previous application binaries were restored when possible.');
      end;
      if not RunServiceAction(ServiceScript, 'StartAndVerify', False) then
      begin
        RestorePriorInstallation;
        RaiseException('The updated server did not pass service and health verification. ' +
          'The previous application binaries were restored when possible.');
      end;
    end;
    if not ServerConfiguredBeforeInstall then
      Log('Server configuration and authoritative database are not both present. ' +
        'Service registration and startup are deferred until server setup is complete.');
  end;
  if CurStep = ssDone then
  begin
    InstallCompleted := True;
    if BinarySnapshotCaptured and (not RunRollbackAction('Discard')) then
      Log('Setup succeeded, but its temporary binary rollback snapshot could not be removed.');
  end;
end;

procedure DeinitializeSetup;
var
  ScriptPath: String;
begin
  if PreflightStarted and (not InstallCompleted) then
  begin
    RestorePriorInstallation;
    ScriptPath := ExpandConstant('{tmp}\server_installer_actions.ps1');
    if not FileExists(ScriptPath) then
      ScriptPath := ExpandConstant('{app}\InstallerSupport\server_installer_actions.ps1');
    if FileExists(ScriptPath) and ServiceWasRunning and
      (not BinaryRollbackRestored) and (not RollbackFailedClosed) then
      RunServiceAction(ScriptPath, 'StartOnly', False);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ServiceScript: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    ServiceScript := ExpandConstant('{app}\InstallerSupport\server_installer_actions.ps1');
    if FileExists(ServiceScript) then
    begin
      if not RunServiceAction(ServiceScript, 'Remove', False) then
        RaiseException('Mission Legal Server could not be stopped and removed. ' +
          'ProgramData was not changed. Review the uninstall log before retrying.');
    end
    else
    begin
      if not RemoveServiceWithoutHelper then
        RaiseException('Mission Legal Server could not be removed from the Windows ' +
          'Service Control Manager. ProgramData was not changed.');
    end;
  end;
end;
