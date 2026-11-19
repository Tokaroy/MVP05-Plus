<#
MVP05-Plus for the Xbox (Dev Mode): packs out\build\xbox-release\MVP05.exe into an app package you install with the
Xbox's Device Portal. Build-Xbox.cmd runs this after building the app.

  out\xbox\MVP05-Plus-Xbox.appx            the app (MVP05.exe, its manifest and tiles: no game files)
  out\xbox\MVP05-Plus-Xbox.cer             the certificate it's signed with (Device Portal may ask for it)
  out\xbox\Microsoft.VCLibs.x64.14.00.appx the C++ runtime it needs (Device Portal: add it as a dependency)

The certificate is made once (CN=MVP05-Plus, in your user's certificate store and as out\xbox\MVP05-Plus-Xbox.pfx)
and reused, so a newer build installs over the older one.
#>
param(
    [string]$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
)
$ErrorActionPreference = "Stop"

function Fail($why) { Write-Host "Stopped: $why" -ForegroundColor Red; exit 1 }

$exe = Join-Path $Repo "out\build\xbox-release\MVP05.exe"
if (-not (Test-Path $exe)) { Fail "no out\build\xbox-release\MVP05.exe: run Build-Xbox.cmd" }
$out = Join-Path $Repo "out\xbox"
$stage = Join-Path $out "package"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force -Path (Join-Path $stage "Assets") | Out-Null

# the tools from the Windows SDK: makeappx and signtool, the newest SDK's
$sdkBin = if ($env:WindowsSdkVerBinPath) { Join-Path $env:WindowsSdkVerBinPath "x64" } else { "" }
function SdkTool($name) {
    if ($sdkBin -and (Test-Path (Join-Path $sdkBin $name))) { return (Join-Path $sdkBin $name) }
    $found = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\$name" -ErrorAction SilentlyContinue |
             Sort-Object FullName -Descending | Select-Object -First 1
    if (-not $found) { Fail "$name isn't installed: it comes with the Windows SDK (Visual Studio Installer)" }
    return $found.FullName
}
$makeappx = SdkTool "makeappx.exe"
$signtool = SdkTool "signtool.exe"

# the package's version: 3.0 and the build's date and time (each part under 65536), so each build is newer
$now = Get-Date
$version = "3.0.{0}.{1}" -f [int]$now.ToString("MMdd"), [int]$now.ToString("HHmm")
$manifest = Get-Content (Join-Path $PSScriptRoot "AppxManifest.xml") -Raw
Set-Content -Path (Join-Path $stage "AppxManifest.xml") -Value $manifest.Replace("@VERSION@", $version) -Encoding UTF8
Copy-Item $exe $stage
Copy-Item (Join-Path $PSScriptRoot "Assets\*.png") (Join-Path $stage "Assets")

# the signing certificate: made once, then kept
$pfx = Join-Path $out "MVP05-Plus-Xbox.pfx"
$cer = Join-Path $out "MVP05-Plus-Xbox.cer"
$password = "mvp05plus"
if (-not (Test-Path $pfx)) {
    Write-Host "Making the signing certificate (once)"
    $cert = New-SelfSignedCertificate -Type Custom -Subject "CN=MVP05-Plus" -KeyUsage DigitalSignature `
        -FriendlyName "MVP05-Plus Xbox app" -CertStoreLocation "Cert:\CurrentUser\My" `
        -TextExtension @("2.5.29.37={text}1.3.6.1.5.5.7.3.3", "2.5.29.19={text}")
    $secure = ConvertTo-SecureString -String $password -Force -AsPlainText
    Export-PfxCertificate -Cert $cert -FilePath $pfx -Password $secure | Out-Null
    Export-Certificate -Cert $cert -FilePath $cer | Out-Null
}

$appx = Join-Path $out "MVP05-Plus-Xbox.appx"
if (Test-Path $appx) { Remove-Item $appx -Force }
& $makeappx pack /o /d $stage /p $appx
if ($LASTEXITCODE -ne 0) { Fail "makeappx couldn't pack the app" }
& $signtool sign /fd SHA256 /a /f $pfx /p $password $appx
if ($LASTEXITCODE -ne 0) { Fail "signtool couldn't sign the app" }

# the C++ runtime for apps, from Visual Studio's UWP tools
$vclibs = Get-ChildItem "${env:ProgramFiles(x86)}\Microsoft SDKs\Windows Kits\10\ExtensionSDKs\Microsoft.VCLibs\14.0\Appx\Retail\x64\Microsoft.VCLibs.x64.14.00.appx" -ErrorAction SilentlyContinue |
          Select-Object -First 1
if ($vclibs) { Copy-Item $vclibs.FullName $out -Force }
else { Write-Host "Microsoft.VCLibs.x64.14.00.appx wasn't found: it comes with Visual Studio's Universal Windows Platform tools" -ForegroundColor Yellow }

Write-Host ""
Write-Host "Done: $appx (version $version)" -ForegroundColor Green
Write-Host "Install it with the Xbox's Device Portal (Add): the .appx, with Microsoft.VCLibs.x64.14.00.appx as a"
Write-Host "dependency, and MVP05-Plus-Xbox.cer as the certificate if it asks. See docs\XBOX.md."
