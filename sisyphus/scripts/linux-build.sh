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
echo "Building $PACKAGE -- logging output to $BUILDROOT/build-$PACKAGE/build.log"
# Run conda build and only log the output
mkdir -p $BUILDROOT/build-$PACKAGE
if ! conda build --error-overlinking -c ai-staging --croot=$BUILDROOT/build-"$PACKAGE"/ $BUILDROOT/"$PACKAGE"-feedstock/ > $BUILDROOT/build-"$PACKAGE"/conda-build.log 2>&1; then
    echo "Build failed. Last 100 lines of the conda build log:"
    tail -n 100 $BUILDROOT/build-$PACKAGE/conda-build.log
    exit 1
fi

echo "Build completed, transmuting packages"
cd $BUILDROOT/build-"$PACKAGE"/linux-64/
cph t '*.tar.bz2' .conda
packages=$(ls *.tar.bz2 *.conda)
for package in $packages; do
    echo $package
done

# Create a tarball of the $BUILDROOT/build-"$PACKAGE"/linux-64/ directory to pull back
cd $BUILDROOT/build-"$PACKAGE"
tar czf $BUILDROOT/build-"$PACKAGE"/linux-64-build.tar.gz linux-64
echo "Build zip created at $BUILDROOT/build-"$PACKAGE"/linux-64-build.tar.gz"
echo ":::BUILD_COMPLETE:::"
exit 0