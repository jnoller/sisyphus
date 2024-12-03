import fabric
import logging
import paramiko
import os
import time


LINUX_TYPE = "linux"
WINDOWS_TYPE = "windows"
LINUX_USER = "ec2-user"
WINDOWS_USER = "dev-admin"
LINUX_TOPDIR = "/tmp/sisyphus"
WINDOWS_TOPDIR = "\\sisyphus"
CONDA_PACKAGES = "conda-build distro-tooling::anaconda-linter git anaconda-client conda-package-handling"
BUILD_OPTIONS = "--error-overlinking -c ai-staging"
ACTIVATE = "conda activate sisyphus &&"


class Host:
    def __init__(self, host):
        """
        Detect the remote host type and initialize the instance.
        """
        self.host = host

        if self.__test_connection(LINUX_USER, "uname -a", LINUX_TYPE):
            self.type = LINUX_TYPE
            self.user = LINUX_USER
            self.separator = "/"
            self.topdir = LINUX_TOPDIR
            self.touch = f"touch"
            self.run("conda init")
        elif self.__test_connection(WINDOWS_USER, "ver", WINDOWS_TYPE):
            self.type = WINDOWS_TYPE
            self.user = WINDOWS_USER
            self.separator = "\\"
            self.topdir = WINDOWS_TOPDIR
            self.touch = f"copy nul"
            self.run("C:\\miniconda3\\Scripts\\conda.exe init")
        else:
            logging.error("Couldn't connect to host '%s' or figure out what type it is", self.host)
            raise SystemExit(1)
        self.mkdir(self.topdir)


    def __test_connection(self, user, cmd, type):
        """
        Verify we can connect and run a test command in order to try and identify the host type.
        """
        logging.debug("Attempting to connect to '%s' assuming it's %s")
        self.connection = fabric.Connection(user=user, connect_timeout=10, host=self.host)
        try:
            r = self.connection.run(cmd, hide=True)
        except:
            logging.debug("Couldn't connect to host '%s' or it isn't '%s'", self.host, type.capitalize())
            self.connection.close()
            return False
        else:
            logging.debug(r.stdout.lstrip().rstrip())
            logging.info("'%s' is a %s host", self.host, type.capitalize())
            return True


    def run(self, cmd, quiet=False):
        """
        Wrapper to run a command on the remote host, log automatically, and report errors if any.
        """
        try:
            r = self.connection.run(cmd, hide=True)
        except Exception as e:
            if not quiet:
                logging.error("%s", e)
                raise SystemExit(1)
        else:
            logging.debug("Running '%s'", cmd)
            stdout = r.stdout.lstrip().rstrip()
            for line in stdout.splitlines():
                logging.debug(line)
            return stdout


    def run_async(self, cmd):
        """
        Launch a background command on the remote host, no error reporting since we're not waiting for exit.
        """
        logging.debug("Running asynchronously '%s'", cmd)
        self.connection.run(cmd, asynchronous=True)


    def exists(self, path):
        """
        Check if remote file or directory exists
        """
        if self.type == LINUX_TYPE:
            # Using single-quotes for the variable to avoid expansion
            r = self.run(f"if [[ -e '{path}' ]]; then echo Yes; fi")
        elif self.type == WINDOWS_TYPE:
            # Windows wants double-quotes for the variable
            r = self.run(f'if exist "{path}" echo Yes')
        if r == "Yes":
            logging.debug("'%s' exists", path)
            return True
        else:
            logging.debug("'%s' doesn't exist", path)
            return False


    def isdir(self, path):
        """
        Check if a remote path is a directory.
        """
        if self.type == LINUX_TYPE:
            r = self.run(f"if [[ -d '{path}' ]]; then echo Yes; fi")
        elif self.type == WINDOWS_TYPE:
            r = self.run(f'if exist "{path}\\*" echo Yes')
        if r == "Yes":
            logging.debug("'%s' is a directory", path)
            return True
        else:
            logging.debug("'%s' isn't a directory", path)
            return False


    def mkdir(self, path):
        """
        Create a remote directory.
        """
        if self.exists(path):
            if self.isdir(path):
                logging.debug("Directory '%s' already exists")
                return
            else:
                logging.error("'%s' already exists and is a file, can't create directory")
                raise SystemExit(1)
        logging.debug("Creating %s", path)
        if self.type == LINUX_TYPE:
            self.run(f"mkdir -p {path}")
        elif self.type == WINDOWS_TYPE:
            self.run(f'mkdir "{path}"')


    def ls(self, path):
        """
        Outputs a simple list of the contents of a remote directory.
        """
        if self.type == LINUX_TYPE:
            self.run(f"ls -1 {path}")
        elif self.type == WINDOWS_TYPE:
            self.run(f'dir /b "{path}"')


    def rm(self, path):
        """
        Delete a remote file or directory.
        """
        if self.exists(path):
            if self.type == LINUX_TYPE:
                self.run(f"rm -rf {path}")
            elif self.type == WINDOWS_TYPE:
                if self.isdir(path):
                    self.run(f'rd /s /q "{path}"')
                else:
                    self.run(f'del "{path}"')


    def untar(self, filepath, dest):
        """
        Untar a remote file into a remote directory.
        """
        # Create the destination directory in case it doesn't exist
        self.mkdir(dest)
        self.run(f"tar -x -f {filepath} -C {dest}")


    def prepare(self):
        """
        Prepare the remote host for building.
        """
        # Create the top-level work directory
        self.mkdir(self.topdir)

        # Does the sisyphus environment exist?
        found = False
        r = self.run("conda env list")
        for line in r.splitlines():
            if line.startswith("sisyphus "):
                found = True
                break
        if found:
            logging.info("Environment 'sisyphus' already exists")
        else:
            # It doesn't, so let's create it
            conda_cmd = f"conda create -y -n sisyphus {CONDA_PACKAGES}"
            redirect = f"{self.topdir}{self.separator}conda.log 2>&1"
            touch = f"{self.touch} {self.topdir}{self.separator}conda."
            self.run_async(f"{conda_cmd} > {redirect} && {touch}ready || {touch}failed")
            logging.info("Environment 'sisyphus' is being created")

        # Windows hosts need to have CUDA installed by the user
        if self.type == WINDOWS_TYPE:
            # Using multiple powershell calls from cmd because the && operator doesn't exist in the old version we're using
            start = "powershell -ExecutionPolicy ByPass -File \\prefect\\install_"
            middle = f".ps1 > {self.topdir}\\"
            end = ".log 2>&1"
            cuda_driver = f"{start}cuda_driver{middle}cuda_driver{end}"
            cuda_12_3_0 = f"{start}cuda_12.3.0{middle}cuda_12.3.0{end}"
            touch = f"{self.touch} {self.topdir}{self.separator}cuda."
            self.run_async(f"{cuda_driver} && {cuda_12_3_0} && {touch}ready || {touch}failed")
            logging.info("CUDA is being installed")


    def put(self, source, dest):
        """
        Upload a local file to a remote directory.
        """
        # fabric won't handle backslashes and volume names in paths, so don't use the latter and replace the former
        if self.type == WINDOWS_TYPE:
            dest = dest.replace("\\", "/")
        logging.debug("Uploading '%s' to '%s'", source, dest)
        self.connection.put(source, dest)


    def build(self, path):
        """
        Build a feedstock with the conda config both in a remote directory.
        """
        builddir = f"{path}{self.separator}build"
        cbc = f"{path}{self.separator}conda_build_config.yaml"
        feedstock = f"{path}{self.separator}feedstock"
        logfile = f"{path}{self.separator}build.log"
        cmd = f"conda build {BUILD_OPTIONS} -e {cbc} --croot={builddir} {feedstock}"
        touch = f"{self.touch} {path}{self.separator}build."
        self.mkdir(builddir)
        self.run_async(f"{ACTIVATE} {cmd} > {logfile} 2>&1 && {touch}ready || {touch}failed")
        logging.info("Build is running")


    def watch(self, package):
        """
        Watch the build if a package name is passed, otherwise watch the prepare process.
        """
        # Set the wait time between updates to 10 seconds
        wait = 10

        if package:
            # A package name was passed so let's watch the build process
            logfile = f"{self.topdir}{self.separator}{package}{self.separator}build.log"
            if self.type == LINUX_TYPE:
                cat = "cat"
            elif self.type == WINDOWS_TYPE:
                cat = "type"
            last_lines = 0
            while True:
                # We can't use tail or the equvalent on Windows because they never return
                # So we'll download the whole log and just show the difference with each iteration
                # There may be a better way to do this, but is it worth the effort?
                r = self.run(f"{cat} {logfile}")
                lines = r.splitlines()
                for line in lines[last_lines:]:
                    logging.info(line)
                # Quit watching when the build.ready or build.failed files show up
                if self.exists(f"{self.topdir}{self.separator}{package}{self.separator}build.ready"):
                    logging.info("Build complete")
                    break
                if self.exists(f"{self.topdir}{self.separator}{package}{self.separator}build.failed"):
                    logging.error("Build Failed")
                    raise SystemExit(1)
                time.sleep(wait)
                last_lines = len(lines)

        else:
            # No package name passed so let's watch the prepare process
            error = False
            logging.info("Waiting for Conda setup to complete")
            while True:
                if self.exists(self.topdir + self.separator + "conda.ready"):
                    logging.info("Conda is ready")
                    break
                elif self.exists(self.topdir + self.separator + "conda.failed"):
                    logging.warning("Conda setup failed")
                    error = True
                    break
                time.sleep(wait)

            if self.type == WINDOWS_TYPE:
                logging.info("Waiting for CUDA installation to complete")
                while True:
                    if self.exists(self.topdir + "\\cuda.ready"):
                        logging.info("CUDA is ready")
                        break
                    elif self.exists(self.topdir + "\\cuda.failed"):
                        logging.warning("CUDA installation failed")
                        error = True
                        break
                    time.sleep(wait)

            if error:
                raise SystemExit(1)


    def upload(self, package, channel, token):
        """
        Upload build packages to anaconda.org.
        """
        pkgdir = f"{self.topdir}{self.separator}{package}{self.separator}build{self.separator}"
        if self.type == LINUX_TYPE:
            pkgdir = f"{pkgdir}linux-64"
        elif self.type == WINDOWS_TYPE:
            pkgdir = f"{pkgdir}win-64"
        logging.info("Uploading packages in: %s", pkgdir)
        logging.info("To channel: %s", channel)
        r = self.connection.run(f"{ACTIVATE} anaconda -t {token} upload -c {channel} --force {pkgdir}{self.separator}*.tar.bz2")
        logging.info("Done")
