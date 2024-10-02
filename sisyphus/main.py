import fabric
import requests
import tempfile
import os
import click
import threading
import shlex

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
    connection.run("docker stop sisyphus && docker rm sisyphus")

def build_linux(host, package, repo, branch, version, channel, label, local_save_path, conda_build_config_path):
    connection = connect_to_linux(host)
    
    # Cleanup existing sisyphus containers
    cleanup_sisyphus_containers(connection)

    connection.put(conda_build_config_path, "conda_build_config.yaml")
    
    # Start the Docker container in detached mode with a placeholder process
    connection.run("docker run -d --name sisyphus -v `pwd`:/io --gpus all public.ecr.aws/y0o4y9o3/anaconda-pkg-build:main-cuda tail -f /dev/null")
    
    # Function to run commands in the Docker container
    def docker_exec(cmd):
        escaped_cmd = shlex.quote(cmd)
        return connection.run(f"docker exec sisyphus bash -c {escaped_cmd}")
    
    # Run all commands in a single bash session
    build_commands = [
        "conda init bash",
        "source ~/.bashrc",
        "conda create -y -n build conda-build distro-tooling::anaconda-linter git anaconda-client conda-package-handling",
        "conda activate build",
        f"git clone {repo}",
        f"cd {package}-feedstock && git checkout {branch} && git pull",
        f"conda build --error-overlinking -c ai-staging --croot=/io/sisbuild-{package}/ .",
        f"cd /io/sisbuild-{package}/linux-64/ && cph t '*.tar.bz2' .conda"
    ]
    
    docker_exec(" && ".join(build_commands))
    
    # Copy all *.tar.bz2 *.conda to the local machine into $LOCAL_SAVE_PATH/$PACKAGE_NAME/$VERSION/linux-64
    linux_save_path = os.path.join(local_save_path, package, version, "linux-64")
    os.makedirs(linux_save_path, exist_ok=True)
    connection.get(f"./sisbuild-{package}/linux-64/*.tar.bz2", linux_save_path)
    connection.get(f"./sisbuild-{package}/linux-64/*.conda", linux_save_path)
    
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
