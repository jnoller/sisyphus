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

Getting help:
```
sisyphus --help
  --package <package-name>             [required] The name of the package to build
  --branch <branch-name>               [required] The branch of the feedstock recipe to build
  --version <package-version>          [required] The version of the package to build
  --channel <anaconda.org-channel>     [required] The channel to upload the packages to
  --tmp-channel <anaconda.org-channel> [required] The channel to upload the unsigned Windows packages to
  --label <label>                      [required] The label to apply to the packages
  --linux-host <ip-address>            [required] The IP address of the Linux host
  --windows-host <ip-address>          [required] The IP address of the Windows host
  --local-save-path <path>             [required] The localpath to save the packages to
```

Running sisyphus:

```
sisyphus build --package llama.cpp \
  --branch main \
  --version 0.0.3853 \
  --channel ai-staging \
  --tmp-channel ai-staging-dev \
  --label dev \
  --linux-host="10.1.1.1" \
  --windows-host="10.1.1.2"
  --local-save-path="./llama-cpp-builds"
```

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