import click
import logging
import os

from .build import Build
from .host import Host
from .util import create_gpu_instance, stop_instance


HELP_CONTEXT = dict(help_option_names=["-h", "--help"])


def setup_logging(log_level):
    """
    Setup logging for the whole application.
    """
    # All we want to see is the message level (DEBUG, INFO, etc...) and the actual message
    format = "%(levelname)s %(message)s"

    # Except when in DEBUG mode, then want to prefix that with a timestamp
    if log_level == "debug":
        format = "%(asctime)s " + format

    # Set the loggin level based on command-line option
    if log_level == "error":
        level = logging.ERROR
    elif log_level == "warning":
        level = logging.WARNING
    elif log_level == "info":
        level = logging.INFO
    elif log_level == "debug":
        level = logging.DEBUG
    logging.basicConfig(level=level, format=format)


@click.group(context_settings=HELP_CONTEXT)
def cli():
    pass


@cli.command(context_settings=HELP_CONTEXT)
@click.option("-H", "--host", required=True, help="IP or FQDN of the build host.")
@click.option("-l", "--log-level", type=click.Choice(["error", "warning", "info", "debug"], case_sensitive=False),
              default="info", show_default=True, help="Logging level.")
def prepare(host, log_level):
    """
    Prepare the host for building.
    """
    setup_logging(log_level)

    # Establish communication with the host
    h = Host(host)

    # Create work directories, setup conda, install CUDA if necessary, etc...
    h.prepare()

    # Wait for prepare to finish if necesary
    h.watch_prepare()


@cli.command(context_settings=HELP_CONTEXT)
@click.option("-H", "--host", required=True, help="IP or FQDN of the build host.")
@click.option("-P", "--package", required=True, help="Name of the package to build.")
@click.option("-B", "--branch", help="Branch to build from in the feedstock's repository.")
@click.option("--no-watch", is_flag=True, default=False, help="Don't watch the build process after it starts.")
@click.option("-l", "--log-level", type=click.Choice(["error", "warning", "info", "debug"], case_sensitive=False),
              default="info", show_default=True, help="Logging level.")
def build(package, branch, host, no_watch, log_level):
    """
    Build a package on the host.
    """
    setup_logging(log_level)

    # Establish communication with the host
    h = Host(host)

    # Prepare the host for building, it will automatically figure out if it has already run or not
    h.prepare()

    # Prepare and upload the data to the host
    b = Build(package, branch)
    b.upload_data(h)
    workdir = h.path(package)
    tarfile = h.path(b.tarfile)
    # Start from a blank slate, untar the data and cleanup
    h.rm(workdir)
    h.untar(tarfile, workdir)
    h.rm(tarfile)
    logging.info("Data ready on host")

    # Wait for prepare to finish if necesary
    h.watch_prepare()

    # Create a build directory, and build the package
    h.build(workdir)

    # Start watching the build process if not disabled
    if not no_watch:
        h.watch_build(workdir)


@cli.command(context_settings=HELP_CONTEXT)
@click.option("-H", "--host", required=True, help="IP or FQDN of the build host.")
@click.option("-P", "--package", help="Name of the package being built.")
@click.option("-l", "--log-level", type=click.Choice(["error", "warning", "info", "debug"], case_sensitive=False),
              default="info", show_default=True, help="Logging level.")
def watch(host, package, log_level):
    """
    Watch build in real-time if a package name is passed, otherwise watch the prepare process.
    Set exit code on error.
    """
    setup_logging(log_level)

    h = Host(host)
    if package:
        h.watch_build(h.path(package))
    else:
        h.watch_prepare()


@cli.command(context_settings=HELP_CONTEXT)
@click.option("-H", "--host", required=True, help="IP or FQDN of the build host.")
@click.option("-P", "--package", required=True, help="Name of the package being built.")
@click.option("-C", "--channel", required=True, help="Target channel on anaconda.org to upload the packages.")
@click.option("-t", "--token", required=True, help="Token for the target channel on anaconda.org.")
@click.option("-l", "--log-level", type=click.Choice(["error", "warning", "info", "debug"], case_sensitive=False),
              default="info", show_default=True, help="Logging level.")
def upload(host, package, channel, token, log_level):
    """
    Upload built packages on the remote host to anaconda.org.
    """
    setup_logging(log_level)

    h = Host(host)
    h.upload(package, channel, token)


@cli.command(context_settings=HELP_CONTEXT)
@click.option("-H", "--host", required=True, help="IP or FQDN of the build host.")
@click.option("-P", "--package", required=True, help="Name of the package being built.")
@click.option("--no-wait", is_flag=True, default=False, help="Don't wait for the build to finish before printing the log.")
@click.option("-l", "--log-level", type=click.Choice(["error", "warning", "info", "debug"], case_sensitive=False),
              default="info", show_default=True, help="Logging level.")
def log(host, package, no_wait, log_level):
    """
    Print the build log to standard output (does not update in real-time).
    """
    setup_logging(log_level)

    h = Host(host)
    h.log(package, no_wait)


@cli.command(context_settings=HELP_CONTEXT)
@click.option("-H", "--host", required=True, help="IP or FQDN of the build host.")
@click.option("-P", "--package", required=True, help="Name of the package being built.")
@click.option("-d", "--destination", help="Destination directory.")
@click.option("-a", "--all", is_flag=True, help="Download the whole work directory for debugging.")
@click.option("-l", "--log-level", type=click.Choice(["error", "warning", "info", "debug"], case_sensitive=False),
              default="info", show_default=True, help="Logging level.")
def download(host, package, destination, all, log_level):
    """
    Download built packages from the remote host.
    """
    setup_logging(log_level)

    # The default desitination is the current working directory
    if not destination:
        destination = os.getcwd()

    h = Host(host)
    h.download(package, destination, all)


@cli.command(context_settings=HELP_CONTEXT)
@click.option("-H", "--host", required=True, help="IP or FQDN of the build host.")
@click.option("-P", "--package", required=True, help="Name of the package being built.")
@click.option("-l", "--log-level", type=click.Choice(["error", "warning", "info", "debug"], case_sensitive=False),
              default="info", show_default=True, help="Logging level.")
def transmute(host, package, log_level):
    """
    Transmute .tar.bz2 packages to .conda packages.
    """
    setup_logging(log_level)

    h = Host(host)
    h.transmute(package)


@cli.command(context_settings=HELP_CONTEXT)
@click.option("-H", "--host", required=True, help="IP or FQDN of the build host.")
@click.option("-P", "--package", required=True, help="Name of the package being built.")
@click.option("-l", "--log-level", type=click.Choice(["error", "warning", "info", "debug"], case_sensitive=False),
              default="info", show_default=True, help="Logging level.")
def status(host, package, log_level):
    """
    Print the build status.
    """
    setup_logging(log_level)

    h = Host(host)
    print(h.status(package))


@cli.command(context_settings=HELP_CONTEXT)
@click.option("-H", "--host", required=True, help="IP or FQDN of the build host.")
@click.option("-P", "--package", required=True, help="Name of the package being built.")
@click.option("-l", "--log-level", type=click.Choice(["error", "warning", "info", "debug"], case_sensitive=False),
              default="info", show_default=True, help="Logging level.")
def wait(host, package, log_level):
    """
    Wait for the build to finish and set exit code based on result.
    """
    setup_logging(log_level)

    h = Host(host)
    if not h.wait(package):
        raise SystemExit(1)


@cli.command(context_settings=HELP_CONTEXT)
@click.option("--linux", is_flag=True, help="Create a Linux GPU instance.")
@click.option("--windows", is_flag=True, help="Create a Windows GPU instance.")
@click.option("-t", "--instance-type", type=click.Choice(["g4dn.4xlarge", "p3.2xlarge"]),
              default="g4dn.4xlarge", show_default=True, help="EC2 GPU instance type.")
@click.option("--lifetime", default="24", show_default=True,
              help="Hours before instance termination.")
@click.option("--token", help="GitHub token (defaults to GITHUB_TOKEN environment variable).")
@click.option("-l", "--log-level", type=click.Choice(["error", "warning", "info", "debug"], case_sensitive=False),
              default="info", show_default=True, help="Logging level.")
def start_host(linux, windows, instance_type, lifetime, token, log_level):
    """
    Create a Linux or Windows GPU instance using rocket-platform.
    """
    setup_logging(log_level)

    if not linux and not windows:
        raise click.UsageError("Either --linux or --windows must be specified")
    if linux and windows:
        raise click.UsageError("Only one of --linux or --windows can be specified")

    create_gpu_instance(token, linux, instance_type, lifetime)


@cli.command(context_settings=HELP_CONTEXT)
@click.argument("id_or_ip")
@click.option("--token", help="GitHub token (defaults to GITHUB_TOKEN environment variable).")
@click.option("-l", "--log-level", type=click.Choice(["error", "warning", "info", "debug"], case_sensitive=False),
              default="info", show_default=True, help="Logging level.")
def stop_host(id_or_ip, token, log_level):
    """
    Stop a GPU instance by ID or IP using rocket-platform.
    """
    setup_logging(log_level)

    stop_instance(token, id_or_ip)


if __name__ == "__main__":
    cli()
