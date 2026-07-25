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
Source: "{#ServerPackageDir}\MissionLegalServerManager.exe"; DestDir: "{app}"; Flags: ignoreversion signonce
Source: "{#ServerPackageDir}\*"; DestDir: "{app}"; Excludes: "MissionLegalServer.exe,MissionLegalServerSetup.exe,MissionLegalService.exe,MissionLegalServerManager.exe"; Flags: ignoreversion recursesubdirs createallsubdirs
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
Type: files; Name: "{app}\MissionLegalServerManager.exe"

[Registry]
Root: HKLM; Subkey: "Software\MissionLegal\Server"; ValueType: string; ValueName: "InstallDir"; ValueData: "{app}"; Flags: uninsdeletekey
Root: HKLM; Subkey: "Software\MissionLegal\Server"; ValueType: string; ValueName: "Version"; ValueData: "{#AppVersion}"; Flags: uninsdeletekey
Root: HKLM; Subkey: "Software\MissionLegal\Server"; ValueType: string; ValueName: "ManagerOperatorAccount"; ValueData: "{code:GetManagerOperatorAccount}"; Flags: uninsdeletevalue
Root: HKLM; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Mission Legal Server Manager"; ValueData: """{app}\MissionLegalServerManager.exe"" --startup"; Flags: uninsdeletevalue

[Icons]
Name: "{autoprograms}\Mission Legal Server Manager"; Filename: "{app}\MissionLegalServerManager.exe"; WorkingDir: "{app}"; Comment: "Open the Mission Legal Server Manager"

[Run]
Filename: "{app}\MissionLegalServerManager.exe"; Parameters: "--startup"; WorkingDir: "{app}"; Flags: nowait runasoriginaluser skipifsilent

[Code]
const
  ServerAppId = '{8A39739D-CBD2-4C38-AE5D-9DE7E69B29D5}';
  ServiceName = 'MissionLegalServer';
  ReadinessMarkerContent = 'mission-legal-server-ready-v1';
  ReadinessMarkerIntroducedVersion = '0.1.1';

var
  PreflightStarted: Boolean;
  InstallCompleted: Boolean;
  InstallFailureDetected: Boolean;
  FreshFootprintCleanupCompleted: Boolean;
  ServiceStateFile: String;
  BinarySnapshotDir: String;
  DatabaseRollbackReceiptPath: String;
  BinarySnapshotCaptured: Boolean;
  BinaryRollbackRestored: Boolean;
  RollbackIntegrationRestored: Boolean;
  DatabaseBackupCaptured: Boolean;
  DatabaseRollbackRestored: Boolean;
  RollbackFailedClosed: Boolean;
  PriorInstallVersion: String;
  PriorManagerOperatorAccount: String;
  HasPriorRegisteredInstall: Boolean;
  HadPriorManagerOperatorAccount: Boolean;
  HasPriorRegistrationFootprint: Boolean;
  HasPriorServiceRegistration: Boolean;
  NeedsPriorBinarySnapshot: Boolean;
  ManagerOperatorSetupRequired: Boolean;
  ManagerShutdownAttempted: Boolean;
  ServerConfiguredBeforeInstall: Boolean;
  ReadinessMarkerExistedBeforeInstall: Boolean;
  PostCopyDatabaseMutationPossible: Boolean;
  WizardSetupRequired: Boolean;
  SetupModePage: TInputOptionWizardPage;
  StoragePage: TInputDirWizardPage;
  MigrationDatabasePage: TInputFileWizardPage;
  ManagerOperatorPage: TInputQueryWizardPage;

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

function DefaultManagerOperatorAccount: String;
var
  DomainName: String;
  UserName: String;
begin
  DomainName := Trim(GetEnv('USERDOMAIN'));
  UserName := Trim(GetEnv('USERNAME'));
  if (DomainName <> '') and (UserName <> '') then
    Result := DomainName + '\' + UserName
  else
    Result := UserName;
end;

function GetManagerOperatorAccount(Param: String): String;
begin
  { An explicit silent/automation override must win over the hidden upgrade
    page, whose value is initialized from the prior registration. }
  Result := Trim(ExpandConstant('{param:MANAGERACCOUNT|}'));
  if (Result = '') and Assigned(ManagerOperatorPage) then
    Result := Trim(ManagerOperatorPage.Values[0]);
  if Result = '' then
    Result := Trim(PriorManagerOperatorAccount);
  if Result = '' then
    Result := DefaultManagerOperatorAccount;
end;

function HasServerRegistrationFootprint: Boolean;
var
  RegistryPath: String;
begin
  RegistryPath := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\' +
    ServerAppId + '_is1';
  Result :=
    RegKeyExists(HKLM64, 'Software\MissionLegal\Server') or
    RegKeyExists(HKLM64, RegistryPath);
end;

function HasServerServiceRegistration: Boolean;
begin
  Result := RegKeyExists(
    HKLM64, 'SYSTEM\CurrentControlSet\Services\' + ServiceName);
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
  HadPriorManagerOperatorAccount := RegQueryStringValue(
    HKLM64,
    'Software\MissionLegal\Server',
    'ManagerOperatorAccount',
    PriorManagerOperatorAccount);
  ManagerOperatorSetupRequired :=
    (not HadPriorManagerOperatorAccount) or
    (Trim(PriorManagerOperatorAccount) = '');
  HasPriorRegistrationFootprint := HasServerRegistrationFootprint;
  HasPriorServiceRegistration := HasServerServiceRegistration;
  HasPriorRegisteredInstall :=
    HasPriorRegistrationFootprint and (PriorInstallVersion <> '');
  if WizardSilent and ManagerOperatorSetupRequired and
    (Trim(ExpandConstant('{param:MANAGERACCOUNT|}')) = '') then
    ErrorMessage := 'A silent server installation must identify the Windows ' +
      'account allowed to use Server Manager. Add ' +
      '/MANAGERACCOUNT="DOMAIN\User" and retry.'
  else if HasPriorServiceRegistration and (not HasPriorRegistrationFootprint) then
    ErrorMessage := 'A Mission Legal Server service exists without a registered ' +
      'installer-owned application. Setup will not replace this partial or ' +
      'manually registered installation.'
  else if HasPriorRegistrationFootprint and (PriorInstallVersion = '') then
    ErrorMessage := 'Mission Legal Server registration exists but its installed ' +
      'version is missing. Setup cannot create a verified rollback state.'
  else if not HasPriorRegisteredInstall then
    Exit
  else if not CompareReleaseVersions('{#AppVersion}', PriorInstallVersion, Comparison) then
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
  { Capture stdout and stderr in the Inno Setup log. This is especially
    important for hidden PowerShell and Python console helpers: a path,
    integrity, ACL, TLS, or service error must not collapse into only "exit 1". }
  Result := ExecAndLogOutput(
    FileName, Parameters, '', SW_HIDE, ewWaitUntilTerminated, ResultCode, nil);
  if not Result then
  begin
    Log(Description + ' could not be started.');
    Exit;
  end;
  Result := ResultCode = 0;
  if not Result then
    Log(Description + ' failed with exit code ' + IntToStr(ResultCode) + '.');
end;

function VerifyServerManagerConnection: Boolean;
var
  Parameters: String;
  ResultPath: String;
begin
  ResultPath := ExpandConstant('{tmp}\mission-legal-manager-smoke.json');
  if FileExists(ResultPath) then
    DeleteFile(ResultPath);
  Parameters := '--connection-smoke-test ' + QuoteArgument(ResultPath);
  Result := RunProcess(
    ExpandConstant('{app}\MissionLegalServerManager.exe'),
    Parameters,
    'Server Manager local-control verification');
  Result := Result and FileExists(ResultPath);
  if Result then
    Log('Server Manager local-control verification passed.')
  else
    Log('Server Manager local-control verification failed.');
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
  if CompareText(Action, 'ValidateManagerOperator') = 0 then
    Parameters := Parameters + ' -ManagerOperatorAccount ' +
      QuoteArgument(GetManagerOperatorAccount(''));
  if RecordState then
    Parameters := Parameters + ' -StateFile ' + QuoteArgument(ServiceStateFile);
  Result := RunProcess(PowerShellExe, Parameters, 'Service action ' + Action);
end;

function ShutdownInstalledServerManager(const ServiceScript: String): Boolean;
begin
  Result := RunServiceAction(ServiceScript, 'StopManager', False);
  if Result then
    Log('Verified that no Server Manager process remains at the exact installed path.');
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
    ' -SnapshotDir ' + QuoteArgument(BinarySnapshotDir) +
    ' -LogFile ' + QuoteArgument(
      ExpandConstant('{commonappdata}\MissionLegal\Logs\installer-rollback.log'));
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

function ReadinessMarkerPath: String;
begin
  Result := ExpandConstant(
    '{commonappdata}\MissionLegal\Configuration\installer-ready-v1.marker');
end;

function HasValidServerReadinessMarker: Boolean;
var
  Marker: AnsiString;
begin
  Result :=
    LoadStringFromFile(ReadinessMarkerPath, Marker) and
    (CompareText(Trim(String(Marker)), ReadinessMarkerContent) = 0);
end;

function HasCoreServerState: Boolean;
begin
  Result :=
    FileExists(ExpandConstant('{commonappdata}\MissionLegal\app.db')) and
    FileExists(
      ExpandConstant('{commonappdata}\MissionLegal\Configuration\server.json'));
end;

function IsServerConfigured: Boolean;
begin
  Result := HasCoreServerState and HasValidServerReadinessMarker;
end;

function IsVerifiedLegacyConfiguredServer: Boolean;
var
  Comparison: Integer;
begin
  Result := False;
  if FileExists(ReadinessMarkerPath) or
    (not HasPriorRegisteredInstall) or
    (not HasPriorServiceRegistration) or
    (not HasCoreServerState) then
    Exit;
  if not CompareReleaseVersions(
    PriorInstallVersion, ReadinessMarkerIntroducedVersion, Comparison) then
    Exit;
  Result := Comparison < 0;
end;

function DefaultOneDriveRoot: String;
begin
  Result := GetEnv('OneDriveCommercial');
  if Result = '' then
    Result := GetEnv('OneDrive');
end;

procedure InitializeWizard;
var
  OneDriveRoot: String;
begin
  ReadinessMarkerExistedBeforeInstall := FileExists(ReadinessMarkerPath);
  ServerConfiguredBeforeInstall :=
    IsServerConfigured or IsVerifiedLegacyConfiguredServer;
  if IsVerifiedLegacyConfiguredServer then
    Log('Adopting a registered pre-readiness-marker server without rerunning ' +
      'the initial storage wizard. The candidate must pass all current runtime ' +
      'gates before its readiness marker is committed.');
  WizardSetupRequired :=
    (not ServerConfiguredBeforeInstall) and (not WizardSilent);

  SetupModePage := CreateInputOptionPage(
    wpWelcome,
    'Choose the server setup',
    'Will this computer start a new server or migrate an existing database?',
    'Setup will configure the Windows service, private-network firewall rule, ' +
      'server storage, and database automatically. It never replaces a populated ' +
      'local database without explicit migration authority.',
    True,
    False);
  SetupModePage.Add(
    'Create a fresh server (keep any local server data already present)');
  SetupModePage.Add('Migrate a verified database snapshot');
  SetupModePage.SelectedValueIndex := 0;

  StoragePage := CreateInputDirPage(
    SetupModePage.ID,
    'Choose server storage',
    'Select the mission-document and mirrored database-backup folders.',
    'The mission-document folder must already exist. The backup folder may be ' +
      'created during setup. Both locations will grant the server service access.',
    False,
    '');
  StoragePage.Add('Mission documents folder:');
  StoragePage.Add('OneDrive database backup folder:');

  OneDriveRoot := DefaultOneDriveRoot;
  if OneDriveRoot <> '' then
  begin
    StoragePage.Values[0] :=
      AddBackslash(OneDriveRoot) + 'Mission Legal Documents';
    StoragePage.Values[1] :=
      AddBackslash(OneDriveRoot) + 'Mission Legal Database Backups';
  end
  else
  begin
    StoragePage.Values[0] :=
      ExpandConstant('{userdocs}\Mission Legal Documents');
    StoragePage.Values[1] :=
      ExpandConstant('{userdocs}\Mission Legal Database Backups');
  end;

  MigrationDatabasePage := CreateInputFilePage(
    StoragePage.ID,
    'Choose the database snapshot',
    'Select the verified SQLite snapshot to migrate.',
    'Setup integrity-checks the selected snapshot and preserves the source file. ' +
      'A populated authoritative database is never replaced by this guided setup.');
  MigrationDatabasePage.Add(
    'Database snapshot:',
    'SQLite database snapshots (*.db)|*.db|All files (*.*)|*.*',
    '.db');

  ManagerOperatorPage := CreateInputQueryPage(
    MigrationDatabasePage.ID,
    'Choose the Server Manager account',
    'Which Windows account should be allowed to manage this server?',
    'Enter the account that normally signs in to this computer and will use ' +
      'the tray icon. This grants only the Server Manager''s fixed local ' +
      'actions; it does not grant access to the protected database or keys.');
  ManagerOperatorPage.Add('Windows account (DOMAIN\User):', False);
  if Trim(ExpandConstant('{param:MANAGERACCOUNT|}')) <> '' then
    ManagerOperatorPage.Values[0] :=
      Trim(ExpandConstant('{param:MANAGERACCOUNT|}'))
  else if HadPriorManagerOperatorAccount then
    ManagerOperatorPage.Values[0] := Trim(PriorManagerOperatorAccount)
  else
    ManagerOperatorPage.Values[0] := DefaultManagerOperatorAccount;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if (PageID = SetupModePage.ID) or (PageID = StoragePage.ID) then
    Result := not WizardSetupRequired
  else if PageID = MigrationDatabasePage.ID then
    Result :=
      (not WizardSetupRequired) or
      (SetupModePage.SelectedValueIndex <> 1)
  else if PageID = ManagerOperatorPage.ID then
    Result := not ManagerOperatorSetupRequired;
end;

function NormalizeSelectedDirectory(const Value: String): String;
begin
  Result := Trim(Value);
  while (Length(Result) > 3) and
    ((Result[Length(Result)] = '\') or
      (Result[Length(Result)] = '/')) do
    Delete(Result, Length(Result), 1);
end;

function IsDriveRoot(const Value: String): Boolean;
begin
  Result :=
    (Length(Value) = 3) and
    (Value[2] = ':') and
    ((Value[3] = '\') or (Value[3] = '/'));
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if WizardSilent then
    Exit;

  if CurPageID = ManagerOperatorPage.ID then
  begin
    ManagerOperatorPage.Values[0] :=
      Trim(ManagerOperatorPage.Values[0]);
    if ManagerOperatorPage.Values[0] = '' then
    begin
      MsgBox('Enter the Windows account that will use Server Manager.',
        mbError, MB_OK);
      Result := False;
      Exit;
    end;
    if (Length(ManagerOperatorPage.Values[0]) > 256) or
      (Pos(#13, ManagerOperatorPage.Values[0]) > 0) or
      (Pos(#10, ManagerOperatorPage.Values[0]) > 0) or
      (Pos(#0, ManagerOperatorPage.Values[0]) > 0) then
    begin
      MsgBox('The Server Manager Windows account is not valid.',
        mbError, MB_OK);
      Result := False;
      Exit;
    end;
    Exit;
  end;

  if not WizardSetupRequired then
    Exit;

  if CurPageID = StoragePage.ID then
  begin
    StoragePage.Values[0] :=
      NormalizeSelectedDirectory(StoragePage.Values[0]);
    StoragePage.Values[1] :=
      NormalizeSelectedDirectory(StoragePage.Values[1]);
    if StoragePage.Values[0] = '' then
    begin
      MsgBox('Choose the folder containing the mission documents.',
        mbError, MB_OK);
      Result := False;
      Exit;
    end;
    if IsDriveRoot(StoragePage.Values[0]) then
    begin
      MsgBox('Choose a mission documents folder inside the drive, not the ' +
        'drive root itself.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
    if not DirExists(StoragePage.Values[0]) then
    begin
      MsgBox('The mission documents folder does not exist. Create or select it ' +
        'with Browse, then continue.' + #13#10#13#10 + StoragePage.Values[0],
        mbError, MB_OK);
      Result := False;
      Exit;
    end;
    if StoragePage.Values[1] = '' then
    begin
      MsgBox('Choose the OneDrive database backup folder.',
        mbError, MB_OK);
      Result := False;
      Exit;
    end;
    if IsDriveRoot(StoragePage.Values[1]) then
    begin
      MsgBox('Choose a database backup folder inside the drive, not the drive ' +
        'root itself.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
  end
  else if (CurPageID = MigrationDatabasePage.ID) and
    (SetupModePage.SelectedValueIndex = 1) then
  begin
    MigrationDatabasePage.Values[0] :=
      Trim(MigrationDatabasePage.Values[0]);
    if not FileExists(MigrationDatabasePage.Values[0]) then
    begin
      MsgBox('Choose an existing database snapshot to migrate.',
        mbError, MB_OK);
      Result := False;
      Exit;
    end;
    if CompareText(
      ExtractFileExt(MigrationDatabasePage.Values[0]), '.db') <> 0 then
    begin
      MsgBox('The migration snapshot must be a .db file.',
        mbError, MB_OK);
      Result := False;
      Exit;
    end;
  end;
end;

function RunInitialServerConfiguration: Boolean;
var
  Parameters: String;
  SetupExecutable: String;
begin
  SetupExecutable := ExpandConstant('{app}\MissionLegalServerSetup.exe');
  Parameters :=
    '--data-dir ' +
      QuoteArgument(ExpandConstant('{commonappdata}\MissionLegal')) +
    ' --mission-storage-root ' + QuoteArgument(StoragePage.Values[0]) +
    ' --onedrive-backup-dir ' + QuoteArgument(StoragePage.Values[1]) +
    ' --host ' + QuoteArgument('0.0.0.0') +
    ' --port 8765 --skip-main-client';
  if SetupModePage.SelectedValueIndex = 1 then
    Parameters := Parameters + ' --existing-database ' +
      QuoteArgument(MigrationDatabasePage.Values[0]);
  Result := RunProcess(
    SetupExecutable, Parameters, 'Initial server configuration');
end;

function InstalledPayloadIsRecognizable: Boolean;
begin
  Result :=
    FileExists(ExpandConstant('{app}\MissionLegalServer.exe')) and
    FileExists(ExpandConstant('{app}\MissionLegalServerSetup.exe')) and
    FileExists(ExpandConstant('{app}\MissionLegalService.exe'));
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
  if HadPriorManagerOperatorAccount then
    RegWriteStringValue(
      HKLM64,
      'Software\MissionLegal\Server',
      'ManagerOperatorAccount',
      PriorManagerOperatorAccount)
  else
    RegDeleteValue(
      HKLM64,
      'Software\MissionLegal\Server',
      'ManagerOperatorAccount');
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
  if BinaryRollbackRestored and RollbackIntegrationRestored then
  begin
    Result := True;
    Exit;
  end;
  if (not BinarySnapshotCaptured) and
    (not PostCopyDatabaseMutationPossible) then
  begin
    { Inno Setup will remove any partially copied first-install files. No
      service or authoritative database mutation has begun, so there is no
      installer-owned state for the custom rollback helper to restore. }
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
  if BinarySnapshotCaptured and (not RunRollbackAction('Restore')) then
  begin
    RollbackFailedClosed := True;
    Log('ERROR: The previous application binaries could not be restored. ' +
      'The verified snapshot remains at ' + BinarySnapshotDir + '.');
    Result := False;
    Exit;
  end;
  if not BinarySnapshotCaptured then
    Log('No prior application binaries existed; Inno Setup will remove the ' +
      'candidate first-install files.');
  BinaryRollbackRestored := True;
  RestorePriorVersionRegistry;
  { Re-run the registration action against the restored executable before any
    restart. This also recreates and verifies the managed Private-network
    firewall rule from the preserved server configuration, without applying
    the candidate version's health check to the prior binary. }
  if (not ServiceWasAbsent) and
    (not RunServiceAction(ServiceScript, 'InstallOrUpdate', False)) then
  begin
    RollbackFailedClosed := True;
    Log('The previous binaries were restored, but their service registration ' +
      'or managed firewall rule could not be restored and verified. Rollback ' +
      'failed closed and the prior service will remain stopped.');
    Result := False;
    Exit;
  end;
  if ServiceWasRunning and
    (not RunServiceAction(ServiceScript, 'StartOnly', False)) then
  begin
    RollbackFailedClosed := True;
    Log('The previous binaries were restored, but their service could not be ' +
      'restarted and held stable. Rollback failed closed.');
    Result := False;
    Exit;
  end;
  RollbackIntegrationRestored := True;
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

function PathIsStrictlyUnderRoot(
  const CandidatePath, RootPath: String): Boolean;
var
  Candidate: String;
  Root: String;
begin
  Candidate := AddBackslash(ExpandFileName(CandidatePath));
  Root := AddBackslash(ExpandFileName(RootPath));
  Result :=
    (Length(Candidate) > Length(Root)) and
    (CompareText(Copy(Candidate, 1, Length(Root)), Root) = 0);
end;

function IsSupportedServiceInstallPath: Boolean;
var
  InstallPath: String;
begin
  InstallPath := ExpandConstant('{app}');
  Result :=
    PathIsStrictlyUnderRoot(
      InstallPath,
      ExpandConstant('{autopf64}')) or
    PathIsStrictlyUnderRoot(
      InstallPath,
      ExpandConstant('{autopf32}'));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ServiceScript: String;
  RecordInitialServiceState: Boolean;
begin
  Result := '';
  if not IsSupportedServiceInstallPath then
  begin
    Result := 'Mission Legal Server must be installed beneath Windows Program ' +
      'Files or Program Files (x86). Setup rejected this application path ' +
      'before stopping the service or changing application files: ' +
      ExpandConstant('{app}');
    Exit;
  end;
  ServiceStateFile := ExpandConstant('{tmp}\mission-legal-service-state.txt');
  BinarySnapshotDir := ExpandConstant(
    '{commonappdata}\MissionLegal\Backups\InstallerBinaries\rollback-{#AppVersion}');
  if DatabaseRollbackReceiptPath = '' then
    DatabaseRollbackReceiptPath := ExpandConstant(
      '{commonappdata}\MissionLegal\Backups\Installer\installer-attempt-') +
      ExtractFileName(ExpandConstant('{tmp}')) + '.json';
  ServerConfiguredBeforeInstall :=
    IsServerConfigured or IsVerifiedLegacyConfiguredServer;
  NeedsPriorBinarySnapshot := HasPriorRegistrationFootprint;
  try
    ExtractTemporaryFile('server_installer_actions.ps1');
    ExtractTemporaryFile('server_installer_rollback.ps1');
    ExtractTemporaryFile('MissionLegalServerMaintenance.exe');
  except
    Result := 'Setup could not extract its server maintenance tools. ' +
      'No application files were changed. Details: ' + GetExceptionMessage;
    Exit;
  end;

  ServiceScript := ExpandConstant('{tmp}\server_installer_actions.ps1');
  if not RunServiceAction(
    ServiceScript, 'ValidateManagerOperator', False) then
  begin
    Result := 'The Server Manager operator must resolve to one Windows user ' +
      'account, not a group or another type of security principal. No service ' +
      'or application files were changed.';
    Exit;
  end;

  if (not ManagerShutdownAttempted) and
    (not ShutdownInstalledServerManager(ServiceScript)) then
  begin
    Result := 'Mission Legal Server Manager could not be closed for the ' +
      'upgrade. No application or server files were changed. Setup only stops ' +
      'a process whose executable path exactly matches this installation.';
    Exit;
  end;
  ManagerShutdownAttempted := True;

  if NeedsPriorBinarySnapshot then
  begin
    if not InstalledPayloadIsRecognizable then
    begin
      Result := 'The registered Mission Legal Server application files are ' +
        'incomplete. Setup cannot create a verified binary rollback copy. ' +
        'No service or application files were changed.';
      Exit;
    end;
  end
  else if not RunRollbackAction('PrepareFresh') then
  begin
    Result := 'Setup found an unregistered application tree or a rollback ' +
      'snapshot that is not safe to discard. No service or application files ' +
      'were changed. Review ProgramData\MissionLegal\Logs\installer-rollback.log.';
    Exit;
  end;

  { PrepareToInstall can run again after an interactive retry. Preserve the
    state captured before the first stop so cancelling a later failed retry
    still restarts a service that was originally running. }
  RecordInitialServiceState := not PreflightStarted;
  PreflightStarted := True;
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
  if NeedsPriorBinarySnapshot and (not RunRollbackAction('Capture')) then
  begin
    Result := 'Setup could not create and verify an independent rollback copy of ' +
      'the installed application binaries. No application files were changed. ' +
      'Review ProgramData\MissionLegal\Logs\installer-rollback.log.';
    Exit;
  end;
  BinarySnapshotCaptured := NeedsPriorBinarySnapshot;
end;

function RemoveFailedFreshInstallationFootprint: Boolean;
var
  AppPath: String;
  RegistryPath: String;
begin
  Result := False;
  if HasPriorRegistrationFootprint then
  begin
    Result := True;
    Exit;
  end;
  if HasServerServiceRegistration then
  begin
    Log('ERROR: Refusing to remove the failed fresh-install files while the ' +
      'candidate service registration still exists.');
    Exit;
  end;

  AppPath := RemoveBackslashUnlessRoot(ExpandConstant('{app}'));
  if (Length(AppPath) < 4) or
    (CompareText(
      AppPath,
      RemoveBackslashUnlessRoot(ExtractFileDrive(AppPath) + '\')) = 0) then
  begin
    Log('ERROR: Refusing unsafe fresh-install cleanup path: ' + AppPath);
    Exit;
  end;
  if DirExists(AppPath) and (not DelTree(AppPath, True, True, True)) then
  begin
    Log('ERROR: Could not remove the failed fresh-install application tree: ' +
      AppPath);
    Exit;
  end;

  RegistryPath := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\' +
    ServerAppId + '_is1';
  if RegKeyExists(HKLM64, 'Software\MissionLegal\Server') and
    (not RegDeleteKeyIncludingSubkeys(
      HKLM64, 'Software\MissionLegal\Server')) then
  begin
    Log('ERROR: Could not remove the failed fresh-install product registry key.');
    Exit;
  end;
  if RegKeyExists(HKLM64, RegistryPath) and
    (not RegDeleteKeyIncludingSubkeys(HKLM64, RegistryPath)) then
  begin
    Log('ERROR: Could not remove the failed fresh-install uninstall registration.');
    Exit;
  end;

  Result :=
    (not DirExists(AppPath)) and
    (not RegKeyExists(HKLM64, 'Software\MissionLegal\Server')) and
    (not RegKeyExists(HKLM64, RegistryPath)) and
    (not HasServerServiceRegistration);
  if Result then
    Log('Verified removal of the failed fresh-install files and registration.')
  else
    Log('ERROR: Failed fresh-install files or registration remain after cleanup.');
end;

procedure FailServerInstallation(const Message: String);
var
  RestoreSucceeded: Boolean;
  CleanupSucceeded: Boolean;
begin
  InstallFailureDetected := True;
  RestoreSucceeded := RestorePriorInstallation;
  CleanupSucceeded := False;
  if RestoreSucceeded then
    CleanupSucceeded := RemoveFailedFreshInstallationFootprint;
  FreshFootprintCleanupCompleted := CleanupSucceeded;
  if not RestoreSucceeded then
    RaiseException(
      Message + ' Rollback failed closed; no server will be started ' +
      'automatically. Review the Setup and installer rollback logs.');
  if not CleanupSucceeded then
    RaiseException(
      Message + ' The prior data state was restored, but Setup could not ' +
      'fully remove the failed fresh-install files or registration. Review ' +
      'the Setup log before retrying.');
  RaiseException(Message + ' The prior state was restored and the failed ' +
    'candidate footprint was removed when this was a fresh install.');
end;

procedure FinishServerInstallation;
var
  ServiceScript: String;
begin
  { ssPostInstall runs after Inno Setup has finalized its uninstall log, so
    every failure path below must restore the prior application/data state and
    explicitly remove a failed true-first-install footprint before raising. }
  ServiceScript := ExpandConstant('{app}\InstallerSupport\server_installer_actions.ps1');
  if WizardSetupRequired then
  begin
    WizardForm.StatusLabel.Caption :=
      'Configuring the authoritative database and server settings...';
    WizardForm.StatusLabel.Update;
    { The installed setup utility may create or migrate the authoritative
      database before it registers and health-checks the service. From this
      point, a failure must restore the receipted pre-install database state
      even though a true first install has no binary rollback snapshot. }
    PostCopyDatabaseMutationPossible := True;
    if not RunInitialServerConfiguration then
    begin
      FailServerInstallation(
        'Mission Legal Server configuration did not complete. The prior ' +
        'state will be restored when possible, and a failed true-first-install ' +
        'footprint will be removed. Server logs under ' +
        '%ProgramData%\MissionLegal\Logs require an administrator or IT account. ' +
        'The Setup log is in the Setup account''s %TEMP% folder with a name ' +
        'beginning with "Setup Log".');
    end;
    { The packaged setup utility normally registers and verifies the service
      itself. Keep the outer installer authoritative as well: a custom /DIR
      path intentionally makes the utility treat itself like a raw package,
      so finish registration here instead of accepting a false success. }
    if (not HasServerServiceRegistration) and
      (not RunServiceAction(ServiceScript, 'InstallOrUpdate', False)) then
    begin
      FailServerInstallation(
        'Server settings were written, but Windows service, storage access, ' +
        'or firewall integration did not complete. Setup will restore the prior ' +
        'state when possible and remove a failed true-first-install footprint.');
    end;
    WizardForm.StatusLabel.Caption :=
      'Starting the server and verifying its secure connection...';
    WizardForm.StatusLabel.Update;
    if not RunServiceAction(ServiceScript, 'StartAndVerify', False) then
    begin
      FailServerInstallation(
        'The newly configured server did not pass service and health ' +
        'verification. Setup will restore the prior state when possible and ' +
        'remove a failed true-first-install footprint.');
    end;
  end
  else if ServerConfiguredBeforeInstall then
  begin
    WizardForm.StatusLabel.Caption :=
      'Updating Windows service and firewall integration...';
    WizardForm.StatusLabel.Update;
    PostCopyDatabaseMutationPossible := True;
    if not RunServiceAction(ServiceScript, 'InstallOrUpdate', False) then
    begin
      FailServerInstallation(
        'Mission Legal Server Windows integration did not complete. ' +
        'Setup will restore the previous application state when possible. Review ' +
        'the final failing stage in the Setup log.');
    end;
    WizardForm.StatusLabel.Caption :=
      'Starting the server and verifying its secure connection...';
    WizardForm.StatusLabel.Update;
    if not RunServiceAction(ServiceScript, 'StartAndVerify', False) then
    begin
      FailServerInstallation(
        'The updated server did not pass service and health verification. ' +
        'Setup will restore the previous application state when possible.');
    end;
  end;
  if WizardSetupRequired or ServerConfiguredBeforeInstall then
  begin
    WizardForm.StatusLabel.Caption :=
      'Verifying Server Manager access for the selected Windows account...';
    WizardForm.StatusLabel.Update;
    if not VerifyServerManagerConnection then
    begin
      FailServerInstallation(
        'The server is healthy, but Server Manager could not connect through ' +
        'its protected local control channel. Setup will restore the prior ' +
        'state when possible.');
    end;
  end;
  if (not WizardSetupRequired) and (not ServerConfiguredBeforeInstall) then
    Log('Server configuration and authoritative database are not both present. ' +
      'Silent installation left service registration and startup deferred. ' +
      'Run MissionLegalServerSetup.exe with explicit storage paths to finish.');
  if not RunServiceAction(
    ServiceScript, 'RemoveLegacyManagerAutostart', False) then
    Log('WARNING: Setup could not finish best-effort cleanup of exact legacy ' +
      'per-user Server Manager startup entries. The installer-owned ' +
      'machine-wide startup registration remains authoritative.');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    FinishServerInstallation;
  if CurStep = ssDone then
  begin
    if InstallFailureDetected then
      Log('ERROR: Setup reached ssDone after a recorded server-install failure; ' +
        'the failure exit code and rollback state are being preserved.')
    else
    begin
      InstallCompleted := True;
      if BinarySnapshotCaptured and (not RunRollbackAction('Discard')) then
        Log('Setup succeeded, but its temporary binary rollback snapshot could not be removed.');
    end;
  end;
end;

function GetCustomSetupExitCode: Integer;
begin
  if InstallFailureDetected then
    Result := 20
  else
    Result := 0;
end;

procedure RemoveCandidateReadinessMarker;
var
  MarkerPath: String;
  TemporaryPath: String;
  RollbackPath: String;
begin
  if ReadinessMarkerExistedBeforeInstall then
    Exit;
  MarkerPath := ReadinessMarkerPath;
  TemporaryPath := MarkerPath + '.tmp';
  RollbackPath := MarkerPath + '.rollback';
  if FileExists(TemporaryPath) and (not DeleteFile(TemporaryPath)) then
    Log('WARNING: Could not remove candidate readiness-marker temporary file: ' +
      TemporaryPath);
  if FileExists(RollbackPath) and (not DeleteFile(RollbackPath)) then
    Log('WARNING: Could not remove candidate readiness-marker rollback file: ' +
      RollbackPath);
  if FileExists(MarkerPath) and (not DeleteFile(MarkerPath)) then
    Log('WARNING: Could not remove the candidate server readiness marker: ' +
      MarkerPath);
end;

procedure DeinitializeSetup;
var
  ScriptPath: String;
begin
  if PreflightStarted and (not InstallCompleted) then
  begin
    RestorePriorInstallation;
    if InstallFailureDetected and (not HasPriorRegistrationFootprint) and
      (not FreshFootprintCleanupCompleted) then
      FreshFootprintCleanupCompleted :=
        RemoveFailedFreshInstallationFootprint;
    RemoveCandidateReadinessMarker;
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
      if not ShutdownInstalledServerManager(ServiceScript) then
        RaiseException('Mission Legal Server Manager could not be closed. Setup ' +
          'refused to remove shared files while the exact installed executable ' +
          'was still running.');
      if not RunServiceAction(
        ServiceScript, 'RemoveLegacyManagerAutostart', False) then
        Log('WARNING: Uninstall could not finish best-effort cleanup of exact ' +
          'legacy per-user Server Manager startup entries.');
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
