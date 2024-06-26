# PyTorch在RISC-V架构上的适配
# 前言
现如今RISC-V软件生态正在建设中，难免会出现大量常用软件包无法直接方便使用的情况。本文就教大家如何在RISC-V环境中安装PyTorch。
系统环境如图所示：
![系统环境](https://img-blog.csdnimg.cn/direct/0d8af7fa06064de7a3ddfc25abf356c6.png)CPU型号为SOPHON SG2042，RV64GC架构，支持V拓展，64核心，主频2.0GHz。
相关工具链版本如下：
![工具链版本](https://img-blog.csdnimg.cn/direct/2bf27850153048b99684c642edbc92bf.png#pic_center)
# 操作步骤
## 第一步：安装软件包
使用OpenEuler的dnf软件包管理器安装，命令如下：
```bash
sudo dnf install python3-{hypothesis,psutil,pyyaml,requests,sympy,filelock,networkx,jinja2,fsspec,packaging,numpy,venv}
```
## 第二步：创建虚拟环境
使用以下命令创建虚拟环境：
```bash
cd; python3 -m venv --system-site-packages venv
```
其中，```--system-site-packages```选项意为继承系统Python环境，从而使用全局环境的PyPI包。

使用 以下命令激活所创建的环境
```bash
source ~/venv/bin/activate
```
也可将其放入```~/.bashrc```中，使之登陆时自动激活
## 第三步：安装其他依赖项
**激活venv环境**后，使用pip安装其他依赖项：
```bash
pip install expecttest types-dataclasses lark optree
```
## 第四步：下载并更改PyTorch源码
我们推荐安装PyTorch 2.3.0版本。首先下载源码（这一过程可先在本地进行然后上传到服务器）：
```bash
wget https://github.com/pytorch/pytorch/releases/download/v2.3.0/pytorch-v2.3.0.tar.gz
```
解压它：
```bash
tar xvf pytorch-v2.3.0.tar.gz
cd pytorch-v2.3.0/
```
执行以下操作，更新```cpuinfo```：
```bash
cd third_party/
rm cpuinfo/ -rf
git clone https://github.com/sophgo/cpuinfo.git
cd ..
```
然后更改以下内容：
1. ```aten/src/ATen/CMakeLists.txt```
将语句：```if(NOT MSVC AND NOT EMSCRIPTEN AND NOT INTERN_BUILD_MOBILE)```
替换为：```if(FALSE)```。
2. ```caffe2/CMakeLists.txt```
将语句：```target_link_libraries(${test_name}_${CPU_CAPABILITY} c10 sleef gtest_main)```
替换为：```target_link_libraries(${test_name}_${CPU_CAPABILITY} c10 gtest_main)```
3. ```test/cpp/api/CMakeLists.txt```
在语句下：```add_executable(test_api ${TORCH_API_TEST_SOURCES})```
添加：```target_compile_options(test_api PUBLIC -Wno-nonnull)```
做好更改后保存，若是在本地进行更改请将更改后的源码上传至服务器。
## 第五步：撰写构建脚本并构建
撰写构建脚本：
```bash
#!/bin/bash
source ~/venv/bin/activate
export USE_CUDA=0 # RISC-V架构服务器无法使用CUDA
export USE_DISTRIBUTED=0 # 不支持分布式
export USE_MKLDNN=0 # 并非英特尔处理器，故不支持MKL
export MAX_JOBS=5 # 编译进程数，根据自己实际需求进行更改
python3 setup.py develop --cmake
```
将其保存为```build.sh```于服务器上的```pytorch-v2.3.0/```目录下。
执行此脚本：
```bash
bash build.sh
```
其将自动完成构建。构建时间很长，本人在此环境使用5进程的情况下构建时长达两三小时，可挂```tmux```或```screen```，此二者若使用需自行使用dnf包管理器进行安装。
## 第六步：安装后检验测试
若安装过程中不存在报错，那么安装过程算告一段落。以下为检验测试：
![检验](https://img-blog.csdnimg.cn/direct/081e154746d44a45bd7e263ecc494818.png)若按如图所示操作可得到相应输出，则PyTorch安装成功。
# 参考资料
- [基于RISC-V架构的AI框架（Pytorch）适配](https://blog.csdn.net/m0_49267873/article/details/135670989)
