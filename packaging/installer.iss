; Setup wizard for PDF Reader (Inno Setup 6.4 or later).
;
; Build it with packaging\build.ps1, which first builds the app with PyInstaller and
; writes build\defines.iss (app name, version, and the voice model's pinned addresses
; and SHA-256 hashes, taken from the app's own code).
;
; Safety by design:
;   - Installs for the current user only: no administrator rights, nothing outside the
;     user's profile, no services, no background tasks, no telemetry.
;   - The voice model is downloaded over HTTPS and checked against its SHA-256 hash;
;     a file that doesn't match is rejected.
;   - "Open with" entries are added only if chosen, and never replace the user's
;     default apps.
;   - Uninstalling removes everything the setup added (and, if the user agrees, the
;     downloaded voices and settings).

#include "..\build\defines.iss"
#define AppExe AppName + ".exe"
#define VoicesTotalMB (ModelSize + VoicesSize + 500000) / 1000000

[Setup]
AppId={{6F1D2B7A-3C4E-4E8B-9A51-7D2C8B0F4E63}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=PDF Reader contributors
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
AppCopyright=Licensed under the GNU AGPL v3.0 or later
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} Setup
VersionInfoProductName={#AppName}
; Per-user installation into %LOCALAPPDATA%\Programs: never asks for admin rights.
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
UsePreviousAppDir=yes
; 64-bit Windows 10 (version 1809) or Windows 11: what the voice model, OCR, and media
; controls need.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
WizardStyle=modern
DisableWelcomePage=no
WizardImageFile=assets\wizard.bmp,assets\wizard@2x.bmp
WizardSmallImageFile=assets\wizard-small.bmp,assets\wizard-small@2x.bmp
SetupIconFile=..\src\pdf_reader\ui\assets\app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
; The license grants rights rather than asking for agreement, so it is shown as a
; summary (and installed with the app) instead of an "I accept" page.
InfoBeforeFile=before-install.txt
OutputDir=..\dist
OutputBaseFilename=PDF-Reader-Setup-{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
; Close a running copy of the app before updating or removing it.
CloseApplications=yes
RestartApplications=no
ChangesAssociations=yes
#ifdef SignTool
; Optional code signing: build.ps1 -SignTool "signtool sign /a /fd sha256 /tr ... $f"
SignTool=custom {#SignTool}
SignedUninstaller=yes
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
WelcomeLabel1=Welcome to {#AppName}
WelcomeLabel2=This will install {#AppName} {#AppVersion}: listen to PDFs, e-books, Word documents, web pages, and any text with natural AI voices.%n%nEverything runs on your own computer. Your documents never leave your PC, and no account is needed.%n%nIt's best to close other apps before continuing.
FinishedHeadingLabel={#AppName} is ready
FinishedLabel={#AppName} has been installed. Open it from the Start menu, or drop a document onto its window to start listening.

[CustomMessages]
VoicesTask=Download the natural voices now (about {#VoicesTotalMB} MB, recommended)
OpenWithTask=Add {#AppName} to "Open with" for PDF, EPUB, and Word files
LowMemory=This computer has %1 GB of memory. {#AppName} works best with at least 4 GB; reading may be slow.%n%nInstall anyway?
LowDisk=There is only %1 MB of free space on drive %2, and the voices need about {#VoicesTotalMB} MB.%n%nThe voices won't be downloaded now; {#AppName} will offer to download them later.
DownloadFailed=The voices couldn't be downloaded (%1).%n%n{#AppName} will be installed anyway and will download them the first time it starts.
RemoveData=Also remove the downloaded voices, your settings, and your reading history (positions and bookmarks)?

[Tasks]
Name: "voices"; Description: "{cm:VoicesTask}"; GroupDescription: "Voices:"; Check: not VoicesInstalled
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "openwith"; Description: "{cm:OpenWithTask}"; GroupDescription: "Files:"

[InstallDelete]
; Remove the previous version's program files, so nothing outdated is left behind.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\build\dist\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "..\src\pdf_reader\ui\fonts\OFL.txt"; DestDir: "{app}"; DestName: "OpenDyslexic-OFL.txt"; Flags: ignoreversion

[Icons]
; The AppUserModelID matches the one the app sets, so Windows shows the app's name and
; icon on the taskbar and in the media controls.
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "{#AppName}"; Comment: "Listen to documents with natural AI voices"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "{#AppName}"; Tasks: desktopicon

[Registry]
; "Open with" support (per user; never changes which app opens a file by default).
Root: HKA; Subkey: "Software\Classes\PDFReader.Document"; ValueType: string; ValueData: "Document"; Flags: uninsdeletekey; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\PDFReader.Document\DefaultIcon"; ValueType: string; ValueData: """{app}\{#AppExe}"",0"; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\PDFReader.Document\shell\open\command"; ValueType: string; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#AppName}"; Flags: uninsdeletekey; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\shell\open\command"; ValueType: string; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".pdf"; ValueData: ""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".epub"; ValueData: ""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".docx"; ValueData: ""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "PDFReader.Document"; ValueData: ""; Flags: uninsdeletevalue; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\.epub\OpenWithProgids"; ValueType: string; ValueName: "PDFReader.Document"; ValueData: ""; Flags: uninsdeletevalue; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\.docx\OpenWithProgids"; ValueType: string; ValueName: "PDFReader.Document"; ValueData: ""; Flags: uninsdeletevalue; Tasks: openwith

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
type
  TMemoryStatusEx = record
    dwLength: DWORD;
    dwMemoryLoad: DWORD;
    ullTotalPhys: Int64;
    ullAvailPhys: Int64;
    ullTotalPageFile: Int64;
    ullAvailPageFile: Int64;
    ullTotalVirtual: Int64;
    ullAvailVirtual: Int64;
    ullAvailExtendedVirtual: Int64;
  end;

function GlobalMemoryStatusEx(var Status: TMemoryStatusEx): BOOL;
  external 'GlobalMemoryStatusEx@kernel32.dll stdcall';

var
  DownloadPage: TDownloadWizardPage;
  VoicesDownloaded: Boolean;

function ModelsDir: String;
begin
  { Where the app looks for the voices: %LOCALAPPDATA%\<AppName>\models }
  Result := ExpandConstant('{localappdata}\{#AppName}\models');
end;

function HasFile(const Name: String; ExpectedSize: Int64): Boolean;
var
  Size: Int64;
begin
  Result := FileSize64(ModelsDir + '\' + Name, Size) and (Size = ExpectedSize);
end;

function VoicesInstalled: Boolean;
begin
  Result := HasFile('{#ModelName}', {#ModelSize}) and HasFile('{#VoicesName}', {#VoicesSize});
end;

function InitializeSetup: Boolean;
var
  Status: TMemoryStatusEx;
  Gigabytes: Integer;
begin
  { System check: enough memory to run the voice model comfortably. }
  Result := True;
  Status.dwLength := 64;
  if GlobalMemoryStatusEx(Status) then
  begin
    Gigabytes := Round(Status.ullTotalPhys / 1073741824.0);
    if Status.ullTotalPhys < 3758096384 then  { 3.5 GB: 4 GB machines report a little less. }
      Result := SuppressibleMsgBox(FmtMessage(CustomMessage('LowMemory'), [IntToStr(Gigabytes)]),
        mbConfirmation, MB_YESNO, IDYES) = IDYES;
  end;
end;

function OnDownloadProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
begin
  Result := True;
end;

procedure InitializeWizard;
begin
  DownloadPage := CreateDownloadPage('Downloading the voices',
    'The natural voices are being downloaded and checked. This happens only once.',
    @OnDownloadProgress);
  DownloadPage.ShowBaseNameInsteadOfUrl := True;
end;

function EnoughSpaceForVoices: Boolean;
var
  Free, Total: Int64;
  Drive, Message: String;
begin
  Drive := ExtractFileDrive(ModelsDir);
  Result := True;
  if GetSpaceOnDisk64(Drive, Free, Total) then
    if Free < {#ModelSize} + {#VoicesSize} + 200 * 1048576 then
    begin
      Message := FmtMessage(CustomMessage('LowDisk'), [IntToStr(Free div 1048576), Drive]);
      SuppressibleMsgBox(Message, mbInformation, MB_OK, IDOK);
      Result := False;
    end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID <> wpReady) or not WizardIsTaskSelected('voices') or VoicesInstalled then
    Exit;
  if not EnoughSpaceForVoices then
    Exit;
  DownloadPage.Clear;
  { Each file is checked against its SHA-256 hash; a mismatch is an error. }
  if not HasFile('{#ModelName}', {#ModelSize}) then
    DownloadPage.Add('{#ModelUrl}', '{#ModelName}', '{#ModelSha256}');
  if not HasFile('{#VoicesName}', {#VoicesSize}) then
    DownloadPage.Add('{#VoicesUrl}', '{#VoicesName}', '{#VoicesSha256}');
  DownloadPage.Show;
  try
    try
      DownloadPage.Download;
      VoicesDownloaded := True;
    except
      if not DownloadPage.AbortedByUser then
        SuppressibleMsgBox(FmtMessage(CustomMessage('DownloadFailed'), [GetExceptionMessage]),
          mbInformation, MB_OK, IDOK);
    end;
  finally
    DownloadPage.Hide;
  end;
end;

procedure MoveVoiceFile(const Name: String);
var
  Source, Target: String;
begin
  Source := ExpandConstant('{tmp}\' + Name);
  Target := ModelsDir + '\' + Name;
  if not FileExists(Source) then
    Exit;
  DeleteFile(Target);
  if not RenameFile(Source, Target) then
    FileCopy(Source, Target, False);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and VoicesDownloaded then
  begin
    ForceDirectories(ModelsDir);
    MoveVoiceFile('{#ModelName}');
    MoveVoiceFile('{#VoicesName}');
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent then
    if MsgBox(CustomMessage('RemoveData'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
    begin
      DelTree(ExpandConstant('{localappdata}\{#AppName}'), True, True, True);
      DelTree(ExpandConstant('{userappdata}\{#AppName}'), True, True, True);
    end;
end;
