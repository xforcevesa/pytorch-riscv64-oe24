# Adapting PyTorch for the RISC-V Architecture

## Introduction
The RISC-V software ecosystem is still under construction, and it is common to encounter difficulties when trying to use popular software packages. This article provides a guide on how to install PyTorch in a RISC-V environment.

The system environment is shown in the image below:
![System Environment](https://img-blog.csdnimg.cn/direct/0d8af7fa06064de7a3ddfc25abf356c6.png)

The CPU model is SOPHON SG2042, RV64GC architecture, with V extension, 64 cores, and a clock speed of 2.0GHz. The toolchain versions are as shown:
![Toolchain Versions](https://img-blog.csdnimg.cn/direct/2bf27850153048b99684c642edbc92bf.png#pic_center)

## Steps
### Step 1: Install Packages
Use OpenEuler's dnf package manager to install the necessary packages with the following command:
```bash
sudo dnf install python3-{hypothesis,psutil,pyyaml,requests,sympy,filelock,networkx,jinja2,fsspec,packaging,numpy,venv}
```

### Step 2: Create a Virtual Environment
Create a virtual environment with the following command:
```bash
cd; python3 -m venv --system-site-packages venv
```
The `--system-site-packages` option allows the virtual environment to inherit the system Python environment, thus using the global PyPI packages.

Activate the created environment with:
```bash
source ~/venv/bin/activate
```
Alternatively, add this command to `~/.bashrc` to activate the environment automatically upon login.

### Step 3: Install Other Dependencies
**Activate the venv environment** and install other dependencies with pip:
```bash
pip install expecttest types-dataclasses lark optree
```

### Step 4: Install PyTorch

#### Install from PyPI Wheel

Download the：

- GitHub Release：https://github.com/xforcevesa/pytorch-riscv64-oe24/releases/tag/2.3.0-alpha
- Gitee Release：https://gitee.com/xforcevesa/pytorch-riscv64-oe24/releases/2.3.0-alpha

After downloading the wheel file, install it with the following command：
```bash
source ~/venv/bin/activate
pip install torch-2.3.0a0+gitunknown-cp311-cp311-linux_riscv64.whl
```

The following is the steps to install PyTorch from source code.

If you have already installed PyTorch from PyPI, you can skip this step.


#### Install from Source

We recommend installing PyTorch version 2.3.0. First, download the source code (this process can be done locally and then uploaded to the server):
```bash
wget https://github.com/pytorch/pytorch/releases/download/v2.3.0/pytorch-v2.3.0.tar.gz
```
Extract it:
```bash
tar xvf pytorch-v2.3.0.tar.gz
cd pytorch-v2.3.0/
```
Update `cpuinfo` by executing the following:
```bash
cd third_party/
rm -rf cpuinfo/
git clone https://github.com/sophgo/cpuinfo.git
cd ..
```

Then, make the following changes:
1. In `aten/src/ATen/CMakeLists.txt`, replace the line:
    ```cmake
    if(NOT MSVC AND NOT EMSCRIPTEN AND NOT INTERN_BUILD_MOBILE)
    ```
    with:
    ```cmake
    if(FALSE)
    ```

2. In `caffe2/CMakeLists.txt`, replace the line:
    ```cmake
    target_link_libraries(${test_name}_${CPU_CAPABILITY} c10 sleef gtest_main)
    ```
    with:
    ```cmake
    target_link_libraries(${test_name}_${CPU_CAPABILITY} c10 gtest_main)
    ```

3. In `test/cpp/api/CMakeLists.txt`, add the following line after:
    ```cmake
    add_executable(test_api ${TORCH_API_TEST_SOURCES})
    ```
    ```cmake
    target_compile_options(test_api PUBLIC -Wno-nonnull)
    ```

Save the changes. If the modifications were done locally, upload the modified source code to the server.

Create a build script:
```bash
#!/bin/bash
source ~/venv/bin/activate
export USE_CUDA=0 # CUDA is not available on RISC-V architecture servers
export USE_DISTRIBUTED=0 # Distributed support is not available
export USE_MKLDNN=0 # MKL is not supported as it is not an Intel processor
export MAX_JOBS=5 # Number of compile processes, adjust as needed
python3 setup.py develop --cmake
```
Save it as `build.sh` in the `pytorch-v2.3.0/` directory on the server. Execute the script with:
```bash
bash build.sh
```
This will automatically complete the build process. The build time is quite long; in my case, using 5 processes, it took two to three hours. Consider using `tmux` or `screen` for a persistent session. If needed, install these tools using the dnf package manager.

### Step 5: Verify Installation
If no errors occurred during the installation, the process is complete. The following shows a verification test:
![Verification](https://img-blog.csdnimg.cn/direct/081e154746d44a45bd7e263ecc494818.png)

If you get the corresponding output as shown in the image, PyTorch has been successfully installed.

## References
- [AI Framework (Pytorch) Adaptation Based on RISC-V Architecture (Chinese)](https://blog.csdn.net/m0_49267873/article/details/135670989)