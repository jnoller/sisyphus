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
$TOKENDIR = "C:\sisyphus\tokens"

# Create token directory if it doesn't exist
if (-not (Test-Path $TOKENDIR)) {
    New-Item -ItemType Directory -Force -Path $TOKENDIR | Out-Null
}

# Install CUDA
$scripts = @(
    @{Path="C:\prefect\install_cuda_driver.ps1"; Token="cuda_driver_installed.token"},
    @{Path="C:\prefect\install_cuda_12.3.0.ps1"; Token="cuda_12.3.0_installed.token"}
)

foreach ($script in $scripts) {
    if ($script -is [string]) {
        if (Test-Path $script) {
            Write-Host "Executing $script"
            & $script
        } else {
            Write-Warning "Script not found: $script"
        }
    } else {
        $scriptPath = $script.Path
        $tokenPath = Join-Path $TOKENDIR $script.Token
        if (Test-Path $scriptPath) {
            if (-not (Test-Path $tokenPath)) {
                Write-Host "Executing $scriptPath"
                & $scriptPath
                if ($LASTEXITCODE -eq 0) {
                    New-Item -ItemType File -Path $tokenPath -Force | Out-Null
                    Write-Host "Created token: $tokenPath"
                } else {
                    Write-Warning "Script execution failed: $scriptPath"
                }
            } else {
                Write-Host "Skipping $scriptPath (already executed)"
            }
        } else {
            Write-Warning "Script not found: $scriptPath"
        }
    }
}

# Initialize conda 
& "C:\miniconda3\shell\condabin\conda-hook.ps1"

# Function to confirm conda is initialized in the shell:
function Confirm-CondaInitialized {
    if (-not (Test-Path $env:CONDA_EXE)) {
        throw "Conda is not initialized. Please run 'conda init' and try again."
    }
}

# Function to run conda commands
function Invoke-CondaCommand {
    param([string]$Command)
    Write-Host "Running conda command: $Command"
    $result = & conda $Command.Split(" ") 2>&1
    if ($LASTEXITCODE -ne 0) { 
        Write-Host "Conda command output: $result"
        throw "Conda command failed: $Command" 
    }
    return $result
}

# Find a unique environment name
do {
    $envName = "sisyphus_" + (Get-Random -Minimum 1000 -Maximum 9999)
} until (-not (conda info --envs | Select-String -Pattern $envName))

# Create and activate the conda environment
Write-Host "Creating and activating $envName environment"
Invoke-CondaCommand "create -y -n $envName conda-build distro-tooling::anaconda-linter git anaconda-client conda-package-handling"
Invoke-CondaCommand "activate $envName"

# Verify activation
$env:CONDA_DEFAULT_ENV
if ($env:CONDA_DEFAULT_ENV -ne $envName) {
    throw "Failed to create and/or activate $envName environment"
}

Set-Location $BUILDROOT
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
