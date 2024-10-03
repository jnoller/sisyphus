#!/bin/bash
set -e

# Check if all required arguments are provided
if [ "$#" -ne 3 ]; then
    echo "Usage: $0 <repo> <package> <branch>"
    exit 1
fi

# Assign command-line arguments to variables
REPO="$1"
PACKAGE="$2"
BRANCH="$3"

BUILDROOT=/sisyphus
cd $BUILDROOT
conda init bash
source ~/.bashrc
conda create -y -n build conda-build distro-tooling::anaconda-linter git anaconda-client conda-package-handling
conda activate build
git clone "$REPO"
cd "${PACKAGE}-feedstock" && git checkout "$BRANCH" && git pull
cd $BUILDROOT
conda build --error-overlinking -c ai-staging --croot=$BUILDROOT/build-"$PACKAGE"/ $BUILDROOT/"$PACKAGE"-feedstock/
cd $BUILDROOT/build-"$PACKAGE"/linux-64/ && cph t '*.tar.bz2' .conda
