@echo off
powershell -ExecutionPolicy ByPass -File {BUILDROOT}\\windows-build.ps1 > {log_file} 2>&1
echo Build completed >> {log_file}