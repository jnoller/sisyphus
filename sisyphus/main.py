import fabric
import requests
import tempfile
import os
import click
import threading
import shlex
import uuid
import time

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
    print(f"To reconnect to the session, use: screen -r {session_name}")

    # Give the process a moment to start writing to the log file
    time.sleep(2)

    # Stream the log file in real-time
    try:
        # Use 'cat' first to display existing content, then 'tail -f' to follow
        connection.run(f"cat {log_file} && tail -f {log_file}", pty=True)
    except KeyboardInterrupt:
        print("\nOutput streaming interrupted. Build is still running in the background.")

    # Wait for the screen session to finish
    while True:
        result = connection.run(f"screen -list | grep {session_name}", warn=True)
        if result.failed:
            break
        time.sleep(10)

    # Check if the build was successful
    build_success = connection.run(f"docker exec sisyphus test -d {BUILDROOT}/sisbuild-{package}/linux-64", warn=True).ok

    if build_success:
        # First, copy files from the container to the host
        host_temp_dir = f"/tmp/sisyphus_build_{package}"
        connection.run(f"mkdir -p {host_temp_dir}")
        connection.run(f"docker cp sisyphus:{BUILDROOT}/sisbuild-{package}/linux-64 {host_temp_dir}")

        # Now copy from the host to the local machine
        linux_save_path = os.path.join(local_save_path, package, version, "linux-64")
        os.makedirs(linux_save_path, exist_ok=True)
        connection.get(f"{host_temp_dir}/linux-64/*.tar.bz2", linux_save_path)
        connection.get(f"{host_temp_dir}/linux-64/*.conda", linux_save_path)

        # Clean up the temporary directory on the host
        connection.run(f"rm -rf {host_temp_dir}")

        print(f"Build completed successfully. Packages saved to {linux_save_path}")
    else:
        print(f"Build failed. You can reconnect to the session with: screen -r {session_name}")
        print(f"Or view the full log with: cat {log_file}")

    # Clean up
    cleanup_sisyphus_containers(connection)

def build_windows(host, package, branch, version, channel, label, local_save_path, conda_build_config_path):
    connection = connect_to_windows(host)
    connection.run()

def get_feedstock(package):
  if package not in FEEDSTOCKS:
    raise click.BadParameter(f"Package {package} is not supported")
  return FEEDSTOCKS[package]

def validate_hosts(ctx, param, value):
    linux_host = ctx.params.get('linux_host')
    windows_host = ctx.params.get('windows_host')
    if not linux_host and not windows_host:
        raise click.BadParameter("At least one of --linux-host or --windows-host must be provided.")
    return value

@click.group()
def cli():
    pass

@cli.command()
@click.option('--package', required=True, help='The name of the package to build')
@click.option('--branch', help='The branch of the feedstock recipe to build')
@click.option('--version', required=True, help='The version of the package to build')
@click.option('--channel', required=True, help='The channel to upload the packages to')
@click.option('--tmp-channel', required=True, help='The channel to upload the unsigned Windows packages to')
@click.option('--label', required=True, help='The label to apply to the packages')
@click.option('--linux-host', help='The IP address of the Linux host')
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
