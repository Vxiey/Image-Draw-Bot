#ifndef MyAppVersion
#define MyAppVersion "1.0.146-rc2"
#endif

[Setup]
#ifdef SignRelease
SignTool=imagedrawbot
SignedUninstaller=yes
#endif
AppId={{6A4AD303-4F16-4ED7-A9AF-5B912352D83E}
AppName=Image Draw Bot
AppVersion={#MyAppVersion}
VersionInfoVersion=1.0.146.0
AppPublisher=Image Draw Bot
DefaultDirName={localappdata}\Programs\Image Draw Bot
DefaultGroupName=Image Draw Bot
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\release
OutputBaseFilename=ImageDrawBot-{#MyAppVersion}-Windows-x64-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\assets\image-draw-bot-icon.ico
UninstallDisplayIcon={app}\ImageDrawBot.exe
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName=Image Draw Bot {#MyAppVersion}
SetupLogging=yes
RestartIfNeededByRun=no
CloseApplications=yes
RestartApplications=no

[Files]
Source: "..\dist\ImageDrawBot\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Image Draw Bot"; Filename: "{app}\ImageDrawBot.exe"; IconFilename: "{app}\_internal\assets\image-draw-bot-icon.ico"; AppUserModelID: "Vxiey.ImageDrawBot"
Name: "{autodesktop}\Image Draw Bot"; Filename: "{app}\ImageDrawBot.exe"; IconFilename: "{app}\_internal\assets\image-draw-bot-icon.ico"; AppUserModelID: "Vxiey.ImageDrawBot"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Run]
Filename: "{app}\ImageDrawBot.exe"; Description: "Launch Image Draw Bot"; Flags: nowait postinstall; Check: ShouldLaunchImageDrawBot

[Code]
function HasCommandLineParam(const Value: String): Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
  begin
    if CompareText(ParamStr(I), Value) = 0 then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

function ShouldLaunchImageDrawBot(): Boolean;
begin
  Result := (not WizardSilent) or HasCommandLineParam('/RELAUNCHIMAGEDRAWBOT');
end;
