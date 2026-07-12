; =====================================================
;  AI Voice Studio - PUBLIC INSTALLER v1.0
;  by domore100
;  Fully self-contained - no Python needed by user
; =====================================================

#define AppName      "AI Voice Studio"
#define AppShortName "Local TTS"
#define AppVersion   "1.0"
#define AppPublisher "domore100"
#define AppExeName   "AI_Voice_Studio.exe"
#define AppURL       "https://github.com/somore100/ai-voice-studio"

[Setup]
AppId={{D4E2A1B3-7F6C-4A8D-9E0B-2C5F8A3D1E7F}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
DefaultDirName={autopf}\AI Voice Studio
DefaultGroupName={#AppName}
AllowNoIcons=yes
OutputDir=setup_output
OutputBaseFilename=AI_Voice_Studio_Setup_v1.0
SetupIconFile=logo.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
WizardResizable=no
LicenseFile=LICENSE.txt
MinVersion=10.0
PrivilegesRequired=admin
UninstallDisplayIcon={app}\logo.ico
UninstallDisplayName={#AppName} {#AppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create desktop shortcut (named ""Local TTS"")"; GroupDescription: "Shortcuts:"
Name: "startmenu"; Description: "Add to Start Menu"; GroupDescription: "Shortcuts:"
Name: "install_models"; Description: "Download basic AI models now (Whisper STT ~150MB + VCTK voices ~100MB) - requires internet"; GroupDescription: "AI Models:"
Name: "install_xtts"; Description: "Also download multilingual voices XTTS-v2 (~2GB) - optional, for Slovenian/Russian etc"; GroupDescription: "AI Models:"

[Dirs]
Name: "{app}"
Name: "{app}\python"
Name: "{app}\models\vctk"
Name: "{app}\models\xtts_v2"
Name: "{app}\models\whisper"
Name: "{app}\models\vosk"

[Files]
; Main application
Source: "dist\AI_Voice_Studio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "logo.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "download_models.py"; DestDir: "{app}"; Flags: ignoreversion
; Bundled Python 3.10 for model downloading
Source: "python_bundled\*"; DestDir: "{app}\python"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\logo.ico"; Tasks: startmenu
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#AppShortName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\logo.ico"; Tasks: desktopicon

[Run]
; Use bundled Python to install packages and download models
Filename: "{app}\python\python.exe"; Parameters: "-m pip install TTS openai-whisper vosk pygame SpeechRecognition PyAudio numpy librosa"; StatusMsg: "Installing packages..."; Flags: runhidden waituntilterminated
Filename: "{app}\python\python.exe"; Parameters: "-m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu"; StatusMsg: "Installing PyTorch (large download)..."; Flags: runhidden waituntilterminated
Filename: "{app}\python\python.exe"; Parameters: """{app}\download_models.py"" --whisper"; StatusMsg: "Downloading Whisper model (~150MB)..."; Flags: runhidden waituntilterminated
Filename: "{app}\python\python.exe"; Parameters: """{app}\download_models.py"" --vctk"; StatusMsg: "Downloading English voices (~100MB)..."; Flags: runhidden waituntilterminated
Filename: "{app}\python\python.exe"; Parameters: """{app}\download_models.py"" --xtts"; StatusMsg: "Downloading multilingual voices (~2GB)..."; Flags: runhidden waituntilterminated
; Download basic models if selected
Filename: "{app}\python\python.exe"; Parameters: """{app}\download_models.py"" --whisper --vctk"; StatusMsg: "Downloading basic AI models (Whisper + VCTK, ~250MB)..."; WorkingDir: "{app}"; Flags: runhidden waituntilterminated; Tasks: install_models
; Download XTTS if selected  
Filename: "{app}\python\python.exe"; Parameters: """{app}\download_models.py"" --xtts"; StatusMsg: "Downloading multilingual voices (~2GB, this takes a while)..."; WorkingDir: "{app}"; Flags: runhidden waituntilterminated; Tasks: install_xtts

Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName} now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Messages]
WelcomeLabel1=Welcome to AI Voice Studio
WelcomeLabel2=Version {#AppVersion} by {#AppPublisher}%n%nFully offline text-to-speech and speech-to-text.%n%n  Supports Slovenian, English, Russian and more%n  No Python installation required%n  English voices (VCTK) + multilingual XTTS-v2%n  Offline speech recognition via Whisper%n%nNote: Setup downloads ~2.5GB of AI models.%nPlease have internet and 5GB free disk space.%n%nClick Next to continue.
FinishedLabel=AI Voice Studio has been installed!%n%nDesktop shortcut "Local TTS" has been created.%n%nClick Finish to close.

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if not DirExists(ExpandConstant('{src}\dist\AI_Voice_Studio')) then
    Result := 'Application not built. Run BuildManager.exe first.';
end;
