# sisyphus

<img src="sisyphus.png" alt="Sisyphus" width="40%" height="40%"/>

Sisyphus automates the manual parts of building GPU (CUDA) enabled packages.

Sisyphus uses the Fabric python package to run commands on the rocket-platform dev instances and is designed to be run on a Unix-like system (Linux, MacOS).

Sisyphus currently automates the following packages:

- llama.cpp: CPU, CUDA, and hardware optimized versions

On the following platforms:

- Linux
- Windows

In order to run Sisyphus, you need to have access to the rocket-platform dev instances [outlined here][1] and you **must be on the Anaconda VPN**.

Sisyphus automates the build and uploading processes outlined here:
- [Building GPU packages][2]
- [Updating the Llama.cpp Conda Package][3]


## Setup & Usage

Sisyphus uses [`conda-project`](https://github.com/conda-incubator/conda-project). You will need to have `conda` and `conda-project` installed.

```
conda install -c conda-forge conda-project
```

You will need to have two API keys from `anaconda.org`, one for the **tmp** channel and one for the **target** channel:

```
export TMP_CHANNEL_API_KEY=<your-key>
export TARGET_CHANNEL_API_KEY=<your-key>
```

Or you can set the environment variables in `.env`:

```
TMP_CHANNEL_API_KEY=<your-key>
TARGET_CHANNEL_API_KEY=<your-key>
```

These variables must be set before running `conda project activate` in the sisyphus directory.

```
cd sisyphus
conda project activate
```

### Getting help
```
> sisyphus --help
Usage: sisyphus [OPTIONS] COMMAND [ARGS]...

Options:
  -h, --help  Show this message and exit.

Commands:
  build    Build a package on the host.
  prepare  Prepare the host for building.
  upload   Upload build packages to anaconda.org.
  watch    Watch build in real-time if a package name is passed,...
```

### Preparing the host

The remote host first needs to be prepared to run the builds.
This means creating a work directory, setting up Conda, and creating a Conda environment.
On Windows, it also means installing CUDA software and drivers, which takes more time.
This only needs to be done once.

```
> sisyphus prepare --help
Usage: sisyphus prepare [OPTIONS]

  Prepare the host for building.

Options:
  -H, --host TEXT                 IP or FQDN of the build host  [required]
  -l, --log-level [error|warning|info|debug]
                                  Logging level  [default: info]
  -h, --help                      Show this message and exit.
```

To prepare the host, run:

```
> sisyphus prepare -H <host>
```

`<host>` is the IP address or FQDN of your remote host.

Make sure your SSH key is correctly configured.
Sisyphus will automatically detect if the remote host is Linux or Windows.
It will immediately disconnect but the preparation will continue on the host.
This is to avoid the job being interrupted by a network issue, due to a VPN hiccup for example.

Logs for the Conda and, on Windows, both CUDA jobs are saved on the remote host in the work directory.
On Linux this is at `/tmp/sisyphus`, and on Windows it's at `C:\sisyphus`.
When `ssh`ing to the host for checking these logs, remember you should login with the `ec2-user` name on Linux and `dev-admin` on Windows.


### Watching the preparation progress

```
> sisyphus watch --help
Usage: sisyphus watch [OPTIONS]

  Watch build in real-time if a package name is passed, otherwise watch the
  prepare process. Set exit code on error.

Options:
  -H, --host TEXT                 IP or FQDN of the build host  [required]
  -P, --package TEXT              Name of the package being built
  -l, --log-level [error|warning|info|debug]
                                  Logging level  [default: info]
  -h, --help                      Show this message and exit.
```

To watch the above preparation process, do:

```
> sisyphus watch -H <host>
```

On the default logging level (info), the output will inform in real-time of the status.
In case of failure, an error exit code will be returned for use in automation, or even a Shell script or one-liner.


### Building the package

```
> sisyphus build --help
Usage: sisyphus build [OPTIONS]

  Build a package on the host.

Options:
  -H, --host TEXT                 IP or FQDN of the build host  [required]
  -P, --package TEXT              Name of the package to build  [required]
  -B, --branch TEXT               Branch to build from in the feedstock's
                                  repository
  -l, --log-level [error|warning|info|debug]
                                  Logging level  [default: info]
  -h, --help                      Show this message and exit.
```

Start the build with:

```
> sisyphus build -H <host> -P <package>
```

`<package>` is the package name as written in the URL for the feedstock.
For example, if the URL is `https://github.com/AnacondaRecipes/llama.cpp-feedstock`, then `<package>` is `llama.cpp`.

Sisyphus will prepare all the data locally, upload it to the host, start the build, then disconnect.


### Watching the build process

It's the same as above for the preparation, except this time we pass the package name.

```
> sisyphus watch -H <host> -P <package>
```

On the default logging level sisyphus will show the build output in real-time.
Here too, an exit code will be returned at the end for use in automation.


### Uploading packages to anaconda.org

```
> sisyphus upload --help
Usage: python -m sisyphus.main upload [OPTIONS]

  Upload build packages to anaconda.org.

Options:
  -H, --host TEXT                 IP or FQDN of the build host.  [required]
  -P, --package TEXT              Name of the package being built.  [required]
  -C, --channel TEXT              Target channel on anaconda.org to upload the
                                  packages.  [required]
  -T, --token TEXT                Token for the target channel on
                                  anaconda.org.  [required]
  -l, --log-level [error|warning|info|debug]
                                  Logging level.  [default: info]
  -h, --help                      Show this message and exit.
```

Upload packages with:

```
sisyphus upload -H <host> -P <package> -C <channel> -T <token>
```

> [!IMPORTANT]
> Windows packages need to be signed first.
> Upload the packages to a temporary channel, then run the code signing action at
> https://github.com/anaconda-distribution/rocket-platform/actions/workflows/codesign-windows.yml


---
Below this still needs to be updated
---

This command does the following:
- logs in to the dev instances via ssh (`--linux-host` and `--windows-host`)
- sets up the hosts for package building
- checks out the feedstock recipe for the package (`llama.cpp`) at the specified branch (`main`)
- builds the package (e.g. `conda build --error-overlinking -c ai-staging --croot=./llamabuild/ ./llama.cpp-feedstock/`)
- transmutes the package to conda format (`cph t "*.tar.bz2" .conda`)
- downloads the package to the local machine (`--local-save-path`)
  - Linux packages are saved in the `$LOCAL_SAVE_PATH/$PACKAGE_NAME/$VERSION/linux-64` subdirectory
  - Windows packages are saved in the `$LOCAL_SAVE_PATH/$PACKAGE_NAME/$VERSION/win-64-unsigned` subdirectory
- uploads the **unsigned** Windows packages to the temporary channel (`--tmp-channel`)
- uploads the Linux packages to the anaconda.org channel (`--channel`)

The windows packages must be signed using the rocket-platform [Codesign Windows Package Github Action][4]

Github Action Input:
- anaconda.org channel to search: `$TMP_CHANNEL/label/$LABEL`
- SPEC of the package(s) to search for: `$PACKAGE_NAME=$VERSION`

Once you have run the GHA to sign the Windows packages, download the signed packages zip file (`signed-packages.zip`) from the GHA page.

Run the following command to unpack and upload the signed Windows packages:

```
sisyphus upload-win-signed --package llama.cpp \
  --version 0.0.3853 \
  --channel ai-staging \
  --label dev \
  --signed-zip-path="~/Downloads/signed-packages.zip" \
  --local-save-path="./llama-cpp-builds"
```


## Error Handling

Sisyphus uses `screen` to run commands on the dev instances. If a screen session is already running, it will be automatically attached to. If not, a new screen session will be created. This means that if the connection is lost or terminated, the screen session will continue to run on the host.

If you need to connect to the screen session later, you can use the following command:

```
ssh -A <username>@<ip-address>
screen -r sisyphus
```

If a command fails during a sisyphus run, the error will be printed to the screen, and the screen session will remain running so you can investigate the issue.

For example, if the `sisyphus build` command fails during the `conda build` step you can log into the instance to debug the issue with the build:

```
ssh -A <username>@<ip-address>
screen -r sisyphus
```



[1]: https://github.com/anaconda-distribution/rocket-platform/tree/main/machine-images#dev-instances
[2]: https://github.com/anaconda-distribution/perseverance-skills/blob/main/sections/02_Package_building/01_How_tos/Building_GPU_packages.md
[3]: https://anaconda.atlassian.net/wiki/spaces/~7120206a3789e73a844699b3e4eb79b01a8c23/pages/3889627143/Updating+the+Llama.cpp+Conda+Package
[4]: https://github.com/anaconda-distribution/rocket-platform/actions/workflows/codesign-windows.yml
