# Builds the Windows installer: dist\FatimaVoiceStudio-Setup-<version>.exe (+ .sha256).
#
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#
# Needs: Python 3.13 with pip and Pillow on PATH (to fetch packages and draw the icon), and Inno Setup 6
# (ISCC.exe). The installer ships this repo's source files as they are, plus the official embeddable Python
# and the exact packages in packaging\requirements-lock.txt. The engine and models are not bundled;
# the app downloads them on its Setup and Models pages.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$PyVersion = "3.13.16"
$PySha256 = "97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297"

$Root = Split-Path -Parent $PSScriptRoot
$Build = Join-Path $Root "build"
$Stage = Join-Path $Build "app"
$Dist = Join-Path $Root "dist"
$Cache = Join-Path $Build "cache"

$Version = (Select-String -Path "$Root\studio\__init__.py" -Pattern '__version__ = "(.+)"').Matches[0].Groups[1].Value
Write-Host "Fatima Voice Studio $Version"

if (Test-Path $Stage) { Remove-Item $Stage -Recurse -Force }
New-Item -ItemType Directory -Force $Stage, $Dist, $Cache | Out-Null

# 0. The quick updater sets the version shown in Windows' Installed apps, under the installer's AppId: they must match.
$issId = (Select-String -Path "$Root\packaging\installer.iss" -Pattern '^AppId=\{\{([0-9A-F-]+)\}').Matches[0].Groups[1].Value
$updId = (Select-String -Path "$Root\studio\updater.py" -Pattern '^APP_ID = "\{([0-9A-F-]+)\}_is1"').Matches[0].Groups[1].Value
if (-not $issId -or $issId -ne $updId) { throw "AppId mismatch: installer.iss has '$issId', studio/updater.py has '$updId'" }

# 1. The app's own files, exactly as in the repo.
robocopy "$Root\studio" "$Stage\studio" /E /XD __pycache__ /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "copying studio failed" }
foreach ($f in "studio_mcp.py", "LICENSE", "THIRD_PARTY_NOTICES.md", "README.md") { Copy-Item "$Root\$f" $Stage }
Set-Content "$Stage\installed" "Marks an installed copy: data lives in %LOCALAPPDATA%\Fatima Voice Studio." -Encoding ascii

# Runtime fingerprint: everything a quick update (app files only) can't change. Installed copies keep it in
# runtime.txt; update.json carries the new one, and a quick update is offered only when they match.
$fpText = $PyVersion + (@("packaging\requirements-lock.txt", "packaging\launcher\Launcher.cs",
                          "packaging\installer.iss", "packaging\build.ps1") |
                        ForEach-Object { (Get-Content -Raw "$Root\$_") -replace "`r`n", "`n" }) -join "`n"
$fpBytes = [System.Text.Encoding]::UTF8.GetBytes($fpText)
$Runtime = -join ([System.Security.Cryptography.SHA256]::Create().ComputeHash($fpBytes) | ForEach-Object { $_.ToString("x2") })
Set-Content "$Stage\runtime.txt" $Runtime -Encoding ascii

# 2. Official embeddable Python, checked against its SHA-256.
$zip = Join-Path $Cache "python-$PyVersion-embed-amd64.zip"
if (-not (Test-Path $zip)) {
    Invoke-WebRequest "https://www.python.org/ftp/python/$PyVersion/python-$PyVersion-embed-amd64.zip" -OutFile $zip
}
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
if ($hash -ne $PySha256) { throw "Python download hash mismatch: $hash" }
Expand-Archive $zip "$Stage\python" -Force
# Let it see site-packages and the app folder (the ._pth file replaces the usual sys.path rules).
$pth = Get-ChildItem "$Stage\python\python*._pth" | Select-Object -First 1
$tag = $pth.BaseName
Set-Content $pth.FullName "$tag.zip`r`n.`r`nLib\site-packages`r`n..`r`nimport site" -Encoding ascii

# 3. Pinned packages, as wheels for this Python and platform only.
$site = "$Stage\python\Lib\site-packages"
python -m pip install --disable-pip-version-check --no-warn-script-location --quiet `
    --target $site --no-deps --only-binary=:all: --platform win_amd64 --python-version 3.13 --implementation cp `
    -r "$Root\packaging\requirements-lock.txt"
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

# 4. Trim what never runs: caches, tests, pywin32's IDE and demos, console-script launchers.
Get-ChildItem $site -Recurse -Directory -Include __pycache__, tests, test, Demos, demos |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
foreach ($d in "pythonwin", "bin", "win32\Demos", "win32\test", "win32com\demos", "win32comext\axdebug", "isapi") {
    if (Test-Path "$site\$d") { Remove-Item "$site\$d" -Recurse -Force }
}
Get-ChildItem $site -Recurse -Include *.chm, *.pyi | Remove-Item -Force

# 5. FatimaVoiceStudio.exe: our launcher (icon + version info), compiled with the C# compiler in Windows.
$icon = Join-Path $Build "app.ico"
python -c "import sys; sys.path.insert(0, r'$Root'); from studio.autostart import icon_image; icon_image().save(r'$icon', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])"
if ($LASTEXITCODE -ne 0) { throw "icon failed" }
$numeric = ($Version -replace '[^0-9.]', '') + ".0"
Set-Content "$Build\Version.cs" @"
using System.Reflection;
[assembly: AssemblyTitle("Fatima Voice Studio")]
[assembly: AssemblyProduct("Fatima Voice Studio")]
[assembly: AssemblyDescription("Fatima Voice Studio")]
[assembly: AssemblyCompany("Hassan")]
[assembly: AssemblyCopyright("Copyright (c) 2026 Hassan. MIT License.")]
[assembly: AssemblyVersion("$numeric")]
[assembly: AssemblyFileVersion("$numeric")]
[assembly: AssemblyInformationalVersion("$Version")]
"@ -Encoding utf8
$csc = "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
& $csc /nologo /target:winexe /platform:x64 /optimize+ "/win32icon:$icon" "/out:$Stage\FatimaVoiceStudio.exe" `
    "$Root\packaging\launcher\Launcher.cs" "$Build\Version.cs"
if ($LASTEXITCODE -ne 0) { throw "launcher build failed" }

# 5b. Microsoft Visual C++ runtime for the engines (llama.cpp and whisper.cpp need it; a fresh Windows doesn't have
#     it). Taken from Visual Studio's redistributable folder (GitHub's build machines), else from this PC's own
#     redistributable install; each file must carry Microsoft's signature. studio/runtime.py uses them app-locally.
$crt = @("msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "msvcp140_atomic_wait.dll", "msvcp140_codecvt_ids.dll",
         "vcruntime140.dll", "vcruntime140_1.dll", "concrt140.dll", "vcomp140.dll")
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$vs = if (Test-Path $vswhere) { & $vswhere -latest -products * -property installationPath } else { $null }
$redist = if ($vs) { Get-ChildItem "$vs\VC\Redist\MSVC\*\x64" -Directory -ErrorAction SilentlyContinue |
                     Where-Object { $_.Parent.Name -match '^\d+\.\d+' } |
                     Sort-Object { [version]$_.Parent.Name } -Descending | Select-Object -First 1 } else { $null }
New-Item -ItemType Directory -Force "$Stage\runtime" | Out-Null
foreach ($dll in $crt) {
    $src = if ($redist) { Get-ChildItem $redist.FullName -Recurse -Filter $dll | Select-Object -First 1 } else { $null }
    if (-not $src) { $src = Get-Item "$env:SystemRoot\System32\$dll" -ErrorAction SilentlyContinue }
    if (-not $src) { throw "Visual C++ runtime file $dll not found (install Visual Studio Build Tools or VC_redist)" }
    $sig = Get-AuthenticodeSignature $src.FullName
    if ($sig.Status -ne "Valid" -or $sig.SignerCertificate.Subject -notmatch "O=Microsoft Corporation") {
        throw "$dll isn't signed by Microsoft ($($sig.Status))"
    }
    Copy-Item $src.FullName "$Stage\runtime\$dll"
}
Write-Host ("Visual C++ runtime {0} from {1}" -f (Get-Item "$Stage\runtime\msvcp140.dll").VersionInfo.FileVersion,
            $(if ($redist) { $redist.FullName } else { "System32" }))

# 6. Smoke test: the bundled Python imports the whole app, and the launcher starts it.
& "$Stage\python\python.exe" -c "import studio.app, studio.tray, studio.mcp_server, numpy, soundfile, lameenc, num2words, sherpa_onnx, win32api; print('imports ok')"
if ($LASTEXITCODE -ne 0) { throw "the bundled runtime can't import the app" }
$check = Start-Process "$Stage\FatimaVoiceStudio.exe" -ArgumentList "--check" -Wait -PassThru
if ($check.ExitCode -ne 0) { throw "FatimaVoiceStudio.exe --check failed ($($check.ExitCode))" }
Write-Host "launcher ok"

$size = (Get-ChildItem $Stage -Recurse -File | Measure-Object Length -Sum).Sum
Write-Host ("Staged {0:N1} MB in {1}" -f ($size / 1MB), $Stage)

# 7. Installer.
$iscc = @("$env:ProgramFiles (x86)\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
          "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 (ISCC.exe) not found" }
& $iscc /Q "/DAppVersion=$Version" "/DSourceDir=$Stage" "/DOutputDir=$Dist" "/DIconFile=$icon" "$Root\packaging\installer.iss"
if ($LASTEXITCODE -ne 0) { throw "ISCC failed" }

$exe = Join-Path $Dist "FatimaVoiceStudio-Setup-$Version.exe"
$sha = (Get-FileHash $exe -Algorithm SHA256).Hash.ToLower()
Set-Content "$exe.sha256" "$sha  $(Split-Path -Leaf $exe)" -Encoding ascii
Write-Host ("Built {0} ({1:N1} MB)`nSHA-256 {2}" -f $exe, ((Get-Item $exe).Length / 1MB), $sha)

# 8. Quick-update package (the app's own files) and update.json, which the in-app updater reads.
$appZip = Join-Path $Dist "FatimaVoiceStudio-app-$Version.zip"
python -c @"
import hashlib, json, os, sys, zipfile
stage, app_zip, setup, version, runtime, out = sys.argv[1:7]
with zipfile.ZipFile(app_zip, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for top in ('studio', 'studio_mcp.py', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'README.md', 'FatimaVoiceStudio.exe'):
        path = os.path.join(stage, top)
        if os.path.isfile(path):
            z.write(path, top)
            continue
        for folder, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if d != '__pycache__']
            for f in files:
                full = os.path.join(folder, f)
                z.write(full, os.path.relpath(full, stage))
def info(p):
    return {'file': os.path.basename(p), 'size': os.path.getsize(p), 'sha256': hashlib.sha256(open(p, 'rb').read()).hexdigest()}
json.dump({'version': version, 'runtime': runtime, 'app': info(app_zip), 'full': info(setup)}, open(out, 'w'), indent=2)
"@ $Stage $appZip $exe $Version $Runtime (Join-Path $Dist "update.json")
if ($LASTEXITCODE -ne 0) { throw "update package failed" }
Write-Host ("Quick update {0} ({1:N1} MB), update.json written" -f (Split-Path -Leaf $appZip), ((Get-Item $appZip).Length / 1MB))
