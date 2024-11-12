import fabric
import requests
import tempfile
import os
import click
import threading
import shlex
import uuid
import time
import tarfile

CONDA_BUILD_CONFIG_YAML = "https://raw.githubusercontent.com/AnacondaRecipes/aggregate/master/conda_build_config.yaml"
LINUX_INST_USER = "ec2-user"
WINDOWS_INST_USER = "dev-admin"

FEEDSTOCKS = {
   "llama.cpp": { "repo": "https://github.com/AnacondaRecipes/llama.cpp-feedstock", "branch": "main" },
}

def get_tmpdir():
    # Return the path of the temporary directory as a string
    return tempfile.mkdtemp()

def get_conda_build_config(tmpdir):
    # Download the conda-build-config.yaml file to the tmpdir
    conda_build_config_path = os.path.join(tmpdir, "conda_build_config.yaml")
    response = requests.get(CONDA_BUILD_CONFIG_YAML)
    response.raise_for_status()
    with open(conda_build_config_path, "wb") as f:
        f.write(response.content)
    return conda_build_config_path

def fix_windows_vs2019(conda_build_config_path):
  # VS2019 is out of date, so we need to fix the config to use VS2022
  with open(conda_build_config_path, "r") as f:
    conda_build_config = f.read()
  conda_build_config = conda_build_config.replace("vs2019", "vs2022")
  with open(conda_build_config_path, "w") as f:
    f.write(conda_build_config)

def connect_to_linux(host):
  # Create and test the connection to the linux instance, should throw if the connection or command fails
  connection = fabric.Connection(user=LINUX_INST_USER, host=host)
  connection.run("ls -l", hide=True)
  return connection

def connect_to_windows(host):
  # Create and test the connection to the windows instance, should throw if the connection or command fails
  connection = fabric.Connection(user=WINDOWS_INST_USER, host=host)
  connection.run("dir", hide=True)
  return connection

def cleanup_sisyphus_containers(connection):
    try:
        # Stop the container if it's running
        connection.run("docker stop sisyphus", warn=True)
    except Exception as e:
        print(f"Warning: Failed to stop sisyphus container: {e}")

    try:
        # Remove the container if it exists
        connection.run("docker rm sisyphus", warn=True)
    except Exception as e:
        print(f"Warning: Failed to remove sisyphus container: {e}")

    # Check if the container still exists
    result = connection.run("docker ps -a --filter name=sisyphus --format '{{.Names}}'", hide=True, warn=True)
    if 'sisyphus' in result.stdout:
        print("Warning: sisyphus container could not be fully cleaned up.")
    else:
        print("sisyphus container successfully cleaned up.")

def build_linux(host, package, repo, branch, version, channel, label, local_save_path, conda_build_config_path):
    connection = connect_to_linux(host)

    # Cleanup existing sisyphus containers
    cleanup_sisyphus_containers(connection)

    BUILDROOT = '/sisyphus'
    current_dir = os.path.dirname(os.path.abspath(__file__))
    linux_build_script = os.path.join(current_dir, 'scripts', 'linux-build.sh')
    connection.put(conda_build_config_path, f"conda_build_config.yaml")
    connection.put(linux_build_script, f"linux-build.sh")
    connection.run(f"chmod +x linux-build.sh")

    # Generate a unique session name and log file name
    session_name = f"sisyphus_{package}_{uuid.uuid4().hex[:8]}"
    # Screen is running on the host, not the container so use the host's path for the log:
    log_file = f"/tmp/build_{session_name}.log"

    # Start the Docker container in detached mode with a placeholder process
    connection.run("docker run -d --name sisyphus -v `pwd`:/io --gpus all public.ecr.aws/y0o4y9o3/anaconda-pkg-build:main-cuda tail -f /dev/null")

    # Make the BUILDROOT directory in the Docker container
    connection.run(f"docker exec sisyphus mkdir -p {BUILDROOT}")
    connection.run(f"docker exec sisyphus mkdir -p {BUILDROOT}/logs")

    # Copy conda_build_config.yaml and linux-build.sh into the Docker container
    connection.run(f"docker cp conda_build_config.yaml sisyphus:/{BUILDROOT}/conda_build_config.yaml")
    connection.run(f"docker cp linux-build.sh sisyphus:/{BUILDROOT}/linux-build.sh")

    # Start a new screen session, run the build command, and tee output to a log file
    screen_command = f"screen -dmS {session_name} bash -c 'docker exec sisyphus {BUILDROOT}/linux-build.sh {repo} {package} {branch} 2>&1 | tee {log_file}; exec bash'"
    connection.run(screen_command)

    print(f"Build started in screen session '{session_name}'")
    print(f"Log file: {log_file}")

    # Stream the log file in real-time until build completion
    build_completed = False

    try:
        while True:
            result = connection.run(f"tail -n 1 {log_file}", hide=True)
            #print(result.stdout, end='', flush=True)

            if ":::BUILD_COMPLETE:::" in result.stdout:
                build_completed = True
                break

            time.sleep(5)
    except KeyboardInterrupt:
        print("\nOutput streaming interrupted. Build is still running in the background.")

    # Terminate the screen session
    connection.run(f"screen -S {session_name} -X quit", warn=True)

    if build_completed:
        print("Build completed: copying tarball from host")

        linux_save_path = os.path.join(local_save_path, package, version)
        os.makedirs(linux_save_path, exist_ok=True)
        build_tarball = "linux-64-build.tar.gz"
        docker_path = f"{BUILDROOT}/build-{package}/linux-64-build.tar.gz"
        host_temp_dir = f"/tmp/sisyphus_build_{package}"
        host_path = os.path.join(host_temp_dir, build_tarball)
        local_path = os.path.join(linux_save_path, build_tarball)

        connection.run(f"mkdir -p {host_temp_dir}")
        connection.run(f"docker cp sisyphus:{docker_path} {host_path}")

        # Now copy from the host to the local machine
        connection.get(f"{host_temp_dir}/linux-64-build.tar.gz", local_path)

        # Clean up the temporary directory on the host
        connection.run(f"rm -rf {host_temp_dir}")

        # Untar the packages locally (the tarball should include the linux-64 directory)
        os.makedirs(linux_save_path, exist_ok=True)
        with tarfile.open(local_path, "r:gz") as tar:
            tar.extractall(path=linux_save_path)

        print(f"Build completed successfully. Packages saved to {linux_save_path}/linux-64")
    else:
        print(f"Build was interrupted. You can view the full log with: cat {log_file}")

    # Clean up
    cleanup_sisyphus_containers(connection)
    connection.close()

def build_windows(host, package, repo, branch, version, channel, label, local_save_path, conda_build_config_path):
    connection = connect_to_windows(host)

    BUILDROOT = 'C:\\sisyphus'
    current_dir = os.path.dirname(os.path.abspath(__file__))
    windows_build_script = os.path.join(current_dir, 'scripts', 'windows-build.ps1')

    # Ensure the BUILDROOT directory exists
    connection.run(f"if not exist {BUILDROOT} mkdir {BUILDROOT}", hide=True)

    # Copy files to the Windows machine - put uses unix-style paths
    print(f"Copying conda_build_config.yaml to {BUILDROOT}")
    connection.put(conda_build_config_path, f"/sisyphus/conda_build_config.yaml")
    print(f"Copying windows-build.ps1 to {BUILDROOT}")
    connection.put(windows_build_script, f"/sisyphus/windows-build.ps1")

    # Generate a unique session name and log file name
    session_name = f"sisyphus_{package}_{uuid.uuid4().hex[:8]}"
    log_file = f"{BUILDROOT}\\build_{session_name}.log"

    # Install screen using cygwin
    connection.run(f"C:\\Users\\dev-admin\\setup-x86_64.exe --no-admin -q -P screen")
    # Ensure screen is available
    screen_path = "C:\\cygwin64\\bin\\screen.exe"
    connection.run(f"if not exist {screen_path} echo Screen not found at {screen_path} && exit 1", hide=True)

    # Start a new screen session, run the build command, and redirect output to a log file
    # screen_command = (
    #     f"C:\\cygwin64\\bin\\screen.exe -dmS {session_name} "
    #     f"powershell -ExecutionPolicy ByPass -Command \"& {{. C:\\sisyphus\\windows-build.ps1}} "
    #     f"2>&1 | Out-File -FilePath C:\\sisyphus\\build_{session_name}.log -Append\""
    # )
    # connection.run(screen_command)

    # Simple mode - just jump into powershell and call the build script
    script_args = f"-Repo {repo} -Package {package} -Branch {branch}"
    connection.run(f"powershell -ExecutionPolicy ByPass -Command \"& {{. C:\\sisyphus\\windows-build.ps1 {script_args}}}")
    # print(f"Build started in screen session '{session_name}'")
    # print(f"Log file: {log_file}")
    # print(f"To reconnect to the session, use: {screen_path} -r {session_name}")

    # # Give the process a moment to start writing to the log file
    # time.sleep(2)

    # # Stream the log file in real-time
    # try:
    #     while True:
    #         result = connection.run(f"if exist {log_file} (type {log_file}) else (echo Log file not created yet)", warn=True)
    #         print(result.stdout)
    #         if "Build completed" in result.stdout or "Build failed" in result.stdout:
    #             break
    #         time.sleep(10)
    # except KeyboardInterrupt:
    #     print("\nOutput streaming interrupted. Build is still running in the background.")

    # # Wait for the screen session to finish
    # while True:
    #     result = connection.run(f"{screen_path} -list | findstr {session_name}", warn=True)
    #     if result.failed:
    #         break
    #     time.sleep(10)

    # # Check if the build was successful
    # build_success = connection.run(f"if exist {BUILDROOT}\\sisbuild-{package}\\win-64 (echo Build successful) else (echo Build failed)", warn=True).stdout.strip()

    # if "Build successful" in build_success:
    #     # Copy the built packages to the local machine
    #     windows_save_path = os.path.join(local_save_path, package, version, "win-64")
    #     os.makedirs(windows_save_path, exist_ok=True)
    #     connection.get(f"{BUILDROOT}\\sisbuild-{package}\\win-64\\*.tar.bz2", windows_save_path)
    #     connection.get(f"{BUILDROOT}\\sisbuild-{package}\\win-64\\*.conda", windows_save_path)

    #     print(f"Build completed successfully. Packages saved to {windows_save_path}")
    # else:
    #     print(f"Build failed. You can reconnect to the session with: {screen_path} -r {session_name}")
    #     print(f"Or view the full log with: type {log_file}")

    # # Clean up
    # connection.run(f"if exist {BUILDROOT}\\sisbuild-{package} rmdir /s /q {BUILDROOT}\\sisbuild-{package}")


def get_feedstock(package):
  if package not in FEEDSTOCKS:
    raise click.BadParameter(f"Package {package} is not supported")
  return FEEDSTOCKS[package]

def validate_hosts(ctx, param, value):
    # Check if we're in the 'complete' phase of command parsing
    if ctx.params.get('windows_host') is None and ctx.params.get('linux_host') is None:
        # We're not in the complete phase, so don't validate yet
        return value

    linux_host = ctx.params.get('linux_host')
    windows_host = ctx.params.get('windows_host')
    if not linux_host and not windows_host:
        raise click.BadParameter("At least one of --linux-host or --windows-host must be provided.")
    return value

@click.group(context_settings=dict(help_option_names=['-h', '--help']))
def cli():
    pass

@cli.command()
@click.option('--package', required=True, help='The name of the package to build')
@click.option('--branch', help='The branch of the feedstock recipe to build')
@click.option('--version', required=True, help='The version of the package to build')
@click.option('--channel', required=True, help='The channel to upload the packages to')
@click.option('--tmp-channel', required=True, help='The channel to upload the unsigned Windows packages to')
@click.option('--label', required=True, help='The label to apply to the packages')
@click.option('--linux-host', help='The IP address of the Linux host', callback=validate_hosts)
@click.option('--windows-host', help='The IP address of the Windows host', callback=validate_hosts)
@click.option('--local-save-path', required=True, help='The local path to save the packages to')
def build(package, branch, version, channel, tmp_channel, label, linux_host, windows_host, local_save_path):

    feedstock = get_feedstock(package)
    repo = feedstock["repo"]
    branch = branch or feedstock["branch"]

    tmpdir = get_tmpdir()
    conda_build_config_path = get_conda_build_config(tmpdir)
    fix_windows_vs2019(conda_build_config_path)

    # Implement the build logic here
    click.echo(f"Building {package} version {version} on branch {branch}")
    click.echo(f"Using channel: {channel}, tmp channel: {tmp_channel}, label: {label}")
    click.echo(f"Linux host: {linux_host}, Windows host: {windows_host}")
    click.echo(f"Saving builds to: {local_save_path}")
    if linux_host:
        build_linux(linux_host, package, repo, branch, version, channel, label, local_save_path, conda_build_config_path)
    if windows_host:
        build_windows(windows_host, package, repo, branch, version, channel, label, local_save_path, conda_build_config_path)


@cli.command()
@click.option('--package', required=True, help='The name of the package')
@click.option('--version', required=True, help='The version of the package')
@click.option('--channel', required=True, help='The channel to upload the signed Windows packages to')
@click.option('--label', required=True, help='The label to apply to the packages')
@click.option('--signed-zip-path', required=True, help='Path to the signed packages zip file')
@click.option('--local-save-path', required=True, help='The local path where builds are saved')
def upload_win_signed(package, version, channel, label, signed_zip_path, local_save_path):
    # Implement the logic for uploading signed Windows packages
    click.echo(f"Uploading signed Windows packages for {package} version {version}")
    click.echo(f"Using channel: {channel}, label: {label}")
    click.echo(f"Signed zip file: {signed_zip_path}")
    click.echo(f"Local save path: {local_save_path}")

    # Add the implementation for unpacking and uploading signed Windows packages

if __name__ == '__main__':
    cli()
