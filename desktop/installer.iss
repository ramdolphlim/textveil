; 文隐 TextVeil · Inno Setup 安装包脚本（装了 Inno Setup 6 后 build_win.bat 会自动生成安装程序）
[Setup]
AppId={{A798CC85-1AC3-4A8E-B14C-1EB11A14D35F}
AppName=文隐 TextVeil
AppVersion=1.0.0
AppPublisher=TextVeil
AppPublisherURL=https://github.com/ramdolphlim/textveil
DefaultDirName={autopf}\TextVeil
DefaultGroupName=文隐 TextVeil
OutputDir=dist
OutputBaseFilename=TextVeil-1.0.0-win-x64-setup
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\TextVeil.exe
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "chs"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "dist\TextVeil\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\文隐 TextVeil"; Filename: "{app}\TextVeil.exe"
Name: "{userdesktop}\文隐 TextVeil"; Filename: "{app}\TextVeil.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"

[Run]
Filename: "{app}\TextVeil.exe"; Description: "运行文隐"; Flags: nowait postinstall skipifsilent
