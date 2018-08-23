# Script to build the Trubble .msi pkg
Param (
    [bool]$default=$false,
    [string]$confFile=$null,
    [string]$version=$null
)
if (!((test-path "C:\Temp\trubble") -and (test-path "C:\Temp\salt"))) {
    write-error "The create_build_env.ps1 script has not been run. Please run the create_build_env.ps1 script and try again."
    break 
}

cd C:\temp
#Finds the current OS. If it isn't 2012r2 it breaks.
#This is a temporary fix until we can find out why it doesn't build on other OS's
$OS = (Get-WmiObject -class Win32_OperatingSystem -Property Version).Version
if ($os -notlike "6.3*" ) {
    write-error "Trubble for Windows can currently on be built on Windows Server 2012R2. Please run this script 2012R2."
}

$hooks = ".\pkg\"

# Find the NSIS Installer
if (Test-Path "C:\Program Files\NSIS\") {
    $nsis = 'C:\Program Files\NSIS'
} Else {
    $nsis = 'C:\Program Files (x86)\NSIS'
}
If (!(Test-Path "$nsis\NSIS.exe")) {
    choco install nsis 
    if (Test-Path "C:\Program Files\NSIS\") {
        $nsis = 'C:\Program Files\NSIS'
    } Else {
        $nsis = 'C:\Program Files (x86)\NSIS'
    }
}

# Add NSIS to the Path
$env:Path += ";$nsis"

# Check for existing trubble pyinstall dir and removing
if (Test-Path '.\trubble\dist') {
    Remove-Item '.\trubble\dist' -Recurse -Force
}
if (Test-Path '.\trubble\build') {
    Remove-Item '.\trubble\build' -Recurse -Force
}


# Create pyinstaller spec
pushd trubble
pyi-makespec --additional-hooks-dir=$hooks .\trubble.py

# Edit the spec file and add libeay32.dll, C:\Python27\libeay32.dll, and BINARY
$specFile = Get-Content .\trubble.spec
$modified = $specFile -match 'BINARY'
if (!($modified)) {
    $specFile = $specFile -replace "a.binaries","a.binaries + [('libeay32.dll', 'C:\Python27\libeay32.dll', 'BINARY')]"
    $specFile | Set-Content .\trubble.spec -Force
}

# Run pyinstaller
pyinstaller .\trubble.spec

# Checks to see if a conf file has been supplied. 
#If not, it prompts the user for a file path then Copies the trubble.conf to correct location
Start-Sleep -Seconds 5
if (!(Test-Path '.\dist\trubble\etc\trubble')) {
    New-Item '.\dist\trubble\etc\trubble' -ItemType Directory
}
if($default) {
    $confFile = 'C:\temp\trubble\pkg\windows\trubble.conf'
}
if($confFile) {
    while(!(test-path $confFile)) {
        write-host "The path you suppplied doesn't exists. Please enter a correct path."
        $confFile = read-host
    }
}
else {
    $confFile = read-host "Please specify the full file path to the .conf file you would like to use."
    while(!(test-path $confile)) {
        write-host "The path you suppplied doesn't exists. Please enter a correct path."
        $confFile = read-host
    }
}
Copy-Item $confFile -Destination '.\dist\trubble\etc\trubble\'

# Copy PortableGit to correct location
Move-Item '.\PortableGit' -Destination '.\dist\trubble\' -Force

# Copy nssm.exe to correct location
if (Test-Path '..\salt\pkg\windows\buildenv\nssm.exe') {
    Copy-Item '..\salt\pkg\windows\buildenv\nssm.exe' -Destination '.\dist\trubble\'
}
else {
    $choco_nssm = choco list --localonly | Where-Object {$_ -like "nssm*"} 
    if (!($choco_nssm)) {
        choco install NSSM -y
    }
    else {
        choco upgrade NSSM
    }
    $nssmPath = "C:\ProgramData\chocolatey\lib\NSSM\tools\nssm.exe"
    Copy-Item $nssmPath -Destination '.\dist\trubble'
}

# Check for intalled osquery
if (!(Test-Path 'C:\ProgramData\osquery\osqueryi.exe')) {
	choco install osquery
}
Copy-Item C:\ProgramData\osquery\osqueryi.exe .\dist\trubble\

# Add needed variables
$currDIR = $PWD.Path
$instDIR = $currDIR + "\pkg\windows"

# Get Prereqs vcredist
If (Test-Path "C:\Program Files (x86)") {
    Invoke-WebRequest -Uri 'http://repo.saltstack.com/windows/dependencies/64/vcredist_x64_2008_mfc.exe' -OutFile "$instDIR\vcredist.exe"
} Else {
    Invoke-WebRequest -Uri 'http://repo.saltstack.com/windows/dependencies/32/vcredist_x86_2008_mfc.exe' -OutFile "$instDIR\vcredist.exe"
}

# Build Installer
if ($default) {
    $version = git tag --sort version:refname | select -last 1
}
if ($version -eq $null) {
		$version = read-host "What would you like to name this build?"
}

makensis.exe /DTrubbleVersion=$version "$instDIR\trubble-Setup.nsi"

Move-Item .\pkg\windows\Trubble*.exe C:\temp\


Write-Host "`n`n***************************"
Write-Host "*********Finished**********"
Write-Host "***************************"
Write-Host "`nThe Trubble installer is located in C:\temp`n`n" -ForegroundColor Yellow
