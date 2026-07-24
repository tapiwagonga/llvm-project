FROM docker.io/library/ubuntu:24.04

# MPFR is required by some of the mathlib tests.
RUN apt-get update && \
    apt-get install -y \
    git \
    libmpfr-dev \
    libgmp-dev \
    libmpc-dev \
    ninja-build \
    build-essential \
    gcc-9 \
    g++-9 \
    gcc-11 \
    g++-11 \
    qemu-user-static \
    libc6-dev-arm64-cross \
    libstdc++6-arm64-cross \
    gcc-aarch64-linux-gnu \
    g++-aarch64-linux-gnu \
    libc6-dev-riscv64-cross \
    libstdc++6-riscv64-cross \
    gcc-riscv64-linux-gnu \
    g++-riscv64-linux-gnu \
    libc6-dev-ppc64el-cross \
    libstdc++6-ppc64el-cross \
    gcc-powerpc64le-linux-gnu \
    g++-powerpc64le-linux-gnu \
    gcc-12-arm-linux-gnueabihf \
    g++-12-arm-linux-gnueabihf \
    sudo \
    sccache \
    ccache \
    wget \
    lsb-release \
    software-properties-common \
    gnupg \
    cmake \
    m4 \
    linux-libc-dev && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

RUN wget https://apt.llvm.org/llvm.sh && \
    chmod +x llvm.sh && \
    sudo ./llvm.sh 19 && \
    sudo ./llvm.sh 23 && \
    rm llvm.sh

# Install gmp and mpfr for cross compilation
RUN wget https://ftp.gnu.org/gnu/gmp/gmp-6.3.0.tar.xz && \
    tar -xf gmp-6.3.0.tar.xz && \
    cd gmp-6.3.0 && \
    ./configure --host=riscv64-linux-gnu --prefix=/usr/riscv64-linux-gnu && \
    make -j$(nproc) && \
    sudo make install && \
    cd .. && \
    rm -rf gmp-6.3.0 && \
    rm gmp-6.3.0.tar.xz

RUN wget https://ftp.gnu.org/gnu/mpfr/mpfr-4.2.2.tar.xz && \
    tar -xf mpfr-4.2.2.tar.xz && \
    cd mpfr-4.2.2 && \
    ./configure --host=riscv64-linux-gnu --prefix=/usr/riscv64-linux-gnu \
    --with-gmp=/usr/riscv64-linux-gnu && \
    make -j$(nproc) && \
    sudo make install && \
    cd .. && \
    rm -rf mpfr-4.2.2 && \
    rm mpfr-4.2.2.tar.xz

RUN wget https://ftp.gnu.org/gnu/mpc/mpc-1.4.1.tar.xz && \
    tar -xf mpc-1.4.1.tar.xz && \
    cd mpc-1.4.1 && \
    ./configure --host=riscv64-linux-gnu --prefix=/usr/riscv64-linux-gnu \
    --with-gmp=/usr/riscv64-linux-gnu \
    --with-mpfr=/usr/riscv64-linux-gnu && \
    make -j$(nproc) && \
    sudo make install && \
    cd .. && \
    rm -rf mpc-1.4.1 && \
    rm mpc-1.4.1.tar.xz



    
# Debian has a multilib setup, so we need to symlink the asm directory.
# For more information, see https://wiki.debian.org/Multiarch/LibraryPathOverview
RUN ln -sf /usr/include/$(uname -p)-linux-gnu/asm /usr/include/asm

# Create a new user to avoid test failures related to a lack of expected
# permissions issues in some tests. Set the user id to 1001 as that is the
# user id that Github Actions uses to perform the checkout action.
RUN useradd gha -u 1001 -m -s /bin/bash

# Also add the user to passwordless sudoers so that we can install software
# later on without having to rebuild the container.
RUN adduser gha sudo
RUN echo '%sudo ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers

USER gha
WORKDIR /home/gha
