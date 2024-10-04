param (
    [Parameter(Mandatory=$true)]
    [string]$Repo,

    [Parameter(Mandatory=$true)]
    [string]$Package,

    [Parameter(Mandatory=$true)]
    [string]$Branch
)

$ErrorActionPreference = "Stop"

$BUILDROOT = "C:\sisyphus"

# Install necessary packages and setup CUDA
choco install -y curl vim
& 'C:\miniconda3\shell\condabin\conda-hook.ps1'
& 'C:\prefect\install_cuda_driver.ps1'
& 'C:\prefect\install_cuda_12.3.0.ps1'

# Function to run conda commands
function Invoke-CondaCommand {
    param([string]$Command)
    & "C:\miniconda3\Scripts\conda.exe" $Command.Split(" ")
    if ($LASTEXITCODE -ne 0) { throw "Conda command failed: $Command" }
}

# Create and activate conda environment
Set-Location $BUILDROOT
Invoke-CondaCommand "init powershell"
& $profile
Invoke-CondaCommand "create -y -n build conda-build distro-tooling::anaconda-linter git anaconda-client conda-package-handling"
Invoke-CondaCommand "activate build"

# Clone repository and checkout branch
git clone $Repo
Set-Location "${Package}-feedstock"
git checkout $Branch
git pull
Set-Location $BUILDROOT

Write-Host "Building $Package -- logging output to $BUILDROOT\build-$Package\conda-build.log"

# Run conda build and log the output
New-Item -ItemType Directory -Force -Path "$BUILDROOT\build-$Package" | Out-Null
$buildCommand = "conda build --error-overlinking -c ai-staging --croot=$BUILDROOT\build-$Package\ $BUILDROOT\${Package}-feedstock\"
$buildLog = "$BUILDROOT\build-$Package\conda-build.log"

try {
    Invoke-Expression $buildCommand *>&1 | Out-File -FilePath $buildLog
}
catch {
    Write-Host "Build failed. Last 100 lines of the conda build log:"
    Get-Content $buildLog -Tail 100
    exit 1
}

Write-Host "Build completed"
Set-Location "$BUILDROOT\build-$Package\win-64\"
Invoke-Expression "cph t '*.tar.bz2' .conda"
$packages = Get-ChildItem -Filter *.tar.bz2,*.conda | Select-Object -ExpandProperty Name
foreach ($package in $packages) {
    Write-Host $package
}
exit 0