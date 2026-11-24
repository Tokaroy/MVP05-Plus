<#
MVP05-Plus for the Xbox (Dev Mode): installs out\xbox\MVP05-Plus-Xbox.appx on the Xbox over your network, through
Device Portal, and starts it; or, with -Logs, fetches xbox-start.txt and xbox-start-previous.txt from it.

  Install-Xbox.ps1 -Xbox 192.168.1.50        install and start (the address is in Dev Home, under Remote Access)
  Install-Xbox.ps1 -Logs                     the start logs, into out\xbox\logs

The address is remembered in out\xbox\xbox-address.txt. Device Portal's user name and password (Dev Home, Remote
Access settings) are asked for when it wants them, and not kept.
#>
param(
    [string]$Xbox = "",
    [switch]$Logs,
    [switch]$NoStart,
    [string]$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
)
$ErrorActionPreference = "Stop"
function Fail($why) { Write-Host "Stopped: $why" -ForegroundColor Red; exit 1 }

$out = Join-Path $Repo "out\xbox"
New-Item -ItemType Directory -Force -Path $out | Out-Null
$remember = Join-Path $out "xbox-address.txt"
if (-not $Xbox -and (Test-Path $remember)) { $Xbox = (Get-Content $remember -Raw).Trim() }
if (-not $Xbox) { $Xbox = (Read-Host "The Xbox's address (Dev Home, Remote Access: e.g. 192.168.1.50)").Trim() }
if (-not $Xbox) { Fail "no address" }
$Xbox = $Xbox -replace '^https?://', '' -replace '/.*$', ''
if ($Xbox -notmatch ':\d+$') { $Xbox += ":11443" }
Set-Content -Path $remember -Value $Xbox
$base = "https://$Xbox"

# Device Portal's certificate is the Xbox's own (self-signed): trusted for this script only
Add-Type -AssemblyName System.Net.Http
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
# (a C# callback: a PowerShell one can be called on a thread with no PowerShell to run it)
if (-not ("XboxPortalTrust" -as [type])) {
    Add-Type -TypeDefinition @"
public static class XboxPortalTrust {
    public static bool Any(object s, System.Security.Cryptography.X509Certificates.X509Certificate c,
        System.Security.Cryptography.X509Certificates.X509Chain ch, System.Net.Security.SslPolicyErrors e) { return true; }
}
"@
}
[System.Net.ServicePointManager]::ServerCertificateValidationCallback = [System.Net.Security.RemoteCertificateValidationCallback]([XboxPortalTrust].GetMethod("Any").CreateDelegate([System.Net.Security.RemoteCertificateValidationCallback]))
$cookies = New-Object System.Net.CookieContainer
$handler = New-Object System.Net.Http.HttpClientHandler
$handler.CookieContainer = $cookies
$http = New-Object System.Net.Http.HttpClient($handler)
$http.Timeout = [TimeSpan]::FromMinutes(10)

function Send($method, $path, $content = $null) {
    for ($try = 0; $try -lt 2; $try++) {
        $req = New-Object System.Net.Http.HttpRequestMessage([System.Net.Http.HttpMethod]::new($method), "$base$path")
        $csrf = $cookies.GetCookies([Uri]$base)["CSRF-Token"]
        if ($csrf) { $req.Headers.Add("X-CSRF-Token", $csrf.Value) }
        if ($content) { $req.Content = $content }
        try { $res = $http.SendAsync($req).GetAwaiter().GetResult() }
        catch { Fail "the Xbox at $Xbox didn't answer: is Dev Mode open and Device Portal on? ($($_.Exception.InnerException.Message))" }
        if ([int]$res.StatusCode -eq 401 -and $try -eq 0) {
            $cred = Get-Credential -Message "Device Portal's user name and password (Dev Home, Remote Access settings)"
            if (-not $cred) { Fail "no password" }
            $pair = "{0}:{1}" -f $cred.UserName, $cred.GetNetworkCredential().Password
            $http.DefaultRequestHeaders.Authorization = New-Object System.Net.Http.Headers.AuthenticationHeaderValue(
                "Basic", [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($pair)))
            continue
        }
        if ([int]$res.StatusCode -eq 403 -and $try -eq 0 -and $content -eq $null) { continue }  # (the CSRF cookie, now had)
        return $res
    }
    return $res
}
function Json($res) {
    $text = $res.Content.ReadAsStringAsync().GetAwaiter().GetResult()
    if (-not $res.IsSuccessStatusCode) { Fail "Device Portal said $([int]$res.StatusCode): $text" }
    if ($text) { return $text | ConvertFrom-Json } else { return $null }
}
function OurPackage() {
    $list = Json (Send "GET" "/api/app/packagemanager/packages")
    return $list.InstalledPackages | Where-Object { $_.PackageFullName -like "spyjam.MVP05Plus_*" } | Select-Object -First 1
}
function B64($s) { [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($s)) }

Json (Send "GET" "/api/os/info") | Out-Null  # (signs in, and gets the CSRF cookie)

if ($Logs) {
    $pkg = OurPackage
    if (-not $pkg) { Fail "MVP05-Plus isn't installed on the Xbox" }
    $dir = Join-Path $out "logs"
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    foreach ($name in @("xbox-start.txt", "xbox-start-previous.txt")) {
        $res = $null
        foreach ($sub in @("\LocalState", "LocalState", "/LocalState")) {
            $q = "knownfolderid=LocalAppData&packagefullname=$([Uri]::EscapeDataString($pkg.PackageFullName))" +
                 "&path=$([Uri]::EscapeDataString($sub))&filename=$name"
            $res = Send "GET" "/api/filesystem/apps/file?$q"
            if ($res.IsSuccessStatusCode) { break }
        }
        if (-not $res.IsSuccessStatusCode) { Write-Host "  $name isn't there"; continue }
        [IO.File]::WriteAllBytes((Join-Path $dir $name), $res.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult())
        Write-Host "  $name" -ForegroundColor Green
    }
    Write-Host "In $dir"
    Invoke-Item $dir
    exit 0
}

$appx = Join-Path $out "MVP05-Plus-Xbox.appx"
if (-not (Test-Path $appx)) { Fail "no out\xbox\MVP05-Plus-Xbox.appx: run Build-Xbox.cmd" }
$files = @($appx)
$vclibs = Join-Path $out "Microsoft.VCLibs.x64.14.00.appx"
if (Test-Path $vclibs) { $files += $vclibs }

Write-Host "Sending MVP05-Plus to the Xbox at $Xbox"
$form = New-Object System.Net.Http.MultipartFormDataContent
foreach ($f in $files) {
    $part = New-Object System.Net.Http.ByteArrayContent(, [IO.File]::ReadAllBytes($f))
    $part.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse("application/octet-stream")
    $form.Add($part, (Split-Path $f -Leaf), (Split-Path $f -Leaf))
}
$res = Send "POST" "/api/app/packagemanager/package?package=$([Uri]::EscapeDataString((Split-Path $appx -Leaf)))" $form
Json $res | Out-Null

Write-Host "Installing" -NoNewline
for ($i = 0; $i -lt 300; $i++) {
    Start-Sleep -Milliseconds 1000
    $state = Send "GET" "/api/app/packagemanager/state"
    if ([int]$state.StatusCode -eq 204) { Write-Host "." -NoNewline; continue }  # (still installing)
    $s = Json $state
    Write-Host ""
    if ($s -and $s.Success -eq $false) {
        $why = "$($s.CodeText) $($s.Reason)".Trim()
        if ($why -match "VCLibs" -or $why -match "framework") { $why += " (try it without the runtime: remove $vclibs)" }
        Fail "the Xbox didn't install it: $why"
    }
    break
}
Write-Host "Installed" -ForegroundColor Green

if ($NoStart) { exit 0 }
$pkg = OurPackage
if (-not $pkg) { Fail "it installed, but isn't in the Xbox's list of apps" }
$res = Send "POST" "/api/taskmanager/app?appid=$(B64 $pkg.PackageRelativeId)&package=$(B64 $pkg.PackageFullName)"
if ($res.IsSuccessStatusCode) { Write-Host "Started on the Xbox" -ForegroundColor Green }
else { Write-Host "It didn't start ($([int]$res.StatusCode)): start it in Dev Home" -ForegroundColor Yellow }
Write-Host "Check once that its App type is Game (Dev Home: highlight it, Menu, View details)."
