#ifndef AppVersion
  #define AppVersion "1.0.9"
#endif

#define AppName "Accessible Reels"
#define AppExeName "Accessible Reels.exe"
#define AppId "{{C48F08B8-6A2D-4D42-B7ED-7DA20C7A79AE}"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=Accessible-Reels-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\dist\Accessible Reels\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; Flags: unchecked

[Registry]
; Lets Windows list the app under Default apps, so links opened from WhatsApp and
; other apps can reach it. It becomes the default only when the user chooses it.
Root: HKCU; Subkey: "Software\Classes\AccessibleReelsURL"; ValueType: string; ValueData: "{#AppName} URL"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\AccessibleReelsURL"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\AccessibleReelsURL\DefaultIcon"; ValueType: string; ValueData: "{app}\{#AppExeName},0"
Root: HKCU; Subkey: "Software\Classes\AccessibleReelsURL\shell\open\command"; ValueType: string; ValueData: """{app}\{#AppExeName}"" ""%1"""
Root: HKCU; Subkey: "Software\Clients\StartMenuInternet\{#AppName}"; ValueType: string; ValueData: "{#AppName}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Clients\StartMenuInternet\{#AppName}\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#AppName}"
Root: HKCU; Subkey: "Software\Clients\StartMenuInternet\{#AppName}\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "Abre videos do TikTok, Instagram e YouTube."
Root: HKCU; Subkey: "Software\Clients\StartMenuInternet\{#AppName}\Capabilities\URLAssociations"; ValueType: string; ValueName: "http"; ValueData: "AccessibleReelsURL"
Root: HKCU; Subkey: "Software\Clients\StartMenuInternet\{#AppName}\Capabilities\URLAssociations"; ValueType: string; ValueName: "https"; ValueData: "AccessibleReelsURL"
Root: HKCU; Subkey: "Software\Clients\StartMenuInternet\{#AppName}\shell\open\command"; ValueType: string; ValueData: """{app}\{#AppExeName}"""
Root: HKCU; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "{#AppName}"; ValueData: "Software\Clients\StartMenuInternet\{#AppName}\Capabilities"; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Iniciar o {#AppName}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\{#AppExeName}"; Flags: nowait skipifnotsilent

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  RuntimeDir: String;
begin
  if CurStep = ssPostInstall then
  begin
    RuntimeDir := ExpandConstant('{app}\runtime');
    if not Exec(ExpandConstant('{sys}\icacls.exe'),
      '"' + RuntimeDir + '" /grant *S-1-15-2-2:(OI)(CI)(RX) *S-1-15-2-1:(OI)(CI)(RX) /T /Q',
      '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      RaiseException('Não foi possível configurar as permissões do runtime.');
    if ResultCode <> 0 then
      RaiseException('Falha ao configurar as permissões do runtime: ' + IntToStr(ResultCode));
  end;
end;
