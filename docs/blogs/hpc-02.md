@[TOC](卷组、逻辑卷与NFS配置)
# 上期回顾
- [上一期文章](https://blog.csdn.net/m0_74221433/article/details/135175622)中我们探讨了从镜像源下载镜像、使用BalenaEtcher烧录、在Inspur集群安装Ubuntu Server 20.04、配置sysctl禁用IPv6、配置netplan静态IP与网关、配置SSH远程登录config及其端口转发与本地反向代理等问题，本期文章是在上一期文章环境的前提下进行配置的，请大家先粗略看一下上一期再看下文。
# 卷组与逻辑卷配置
## 物理卷、卷组与逻辑卷
- 物理卷简称PV（Physical Volume），是一个个**被选定**的物理储存单元，在Linux中以块设备的形式存在；一般名称形如```/dev/sda```、```/dev/sdb2```、```/dev/nvme0n1p4```等等。
- 卷组简称VG（Volume Group），是物理卷的集合，可看成是一个独立的**抽象**层面的设备。
- 逻辑卷简称LV（Logical Volume），是从卷组中划分出一块区域而成的一个独立的逻辑（或虚拟）磁盘，亦以块设备的形式存在。
- 架构图如下，此处为[图片来源](https://access.redhat.com/documentation/zh-cn/red_hat_enterprise_linux/7/html/logical_volume_manager_administration/lvm_definition)。
![PV/VG/LVM架构图](images/7098ed7eab5d4f5cb8e0b7f1a41180ad.png)
## 使用原因
1. 大容量磁盘：HPC集群业务中需要我们去挂载8TB大小的一个磁盘，然而我们却只有若干1TB与2TB大小的磁盘，如何去应对这种情况呢？当然是使用使用逻辑卷，将多个小容量的磁盘聚合为一个大的逻辑磁盘，这样就能满足需求。~~当然，再买一块8TB硬盘也不是不可以，~~ 这种方法是在硬件条件有限的情况下使用。
2. 方便拓展收缩：在前期规划磁盘时，我们并不能完全知道需要分配多少磁盘空间是合理的，如果直接使用物理卷，后期无法扩展和收缩，如果使用逻辑卷，可以根据后期的需求量，手动扩展或收缩。

## 创建物理卷
- 本次是使用```/dev/sda```、```/dev/sdc```、```/dev/sdd```、```/dev/sde```、```/dev/sdf```、```/dev/sdg```、```/dev/sdh```七块硬盘进行合并。
> 注意：创建新的分区表将抹除该磁盘上所有分区及其一切数据，数据无价，请务必谨慎操作！~~除非看管不稀罕数据恢复的巨款。~~

最后，使用```pvcreate```命令创建物理卷，使之可纳入卷组中。
```bash
sudo pvcreate /dev/sd[ac-h]
```
- 将后面的硬盘替换成看官自己的。
- 然后使用以下命令查看物理卷：
```bash
pvdisplay
pvs
pvscan
```
- 若有分区或磁盘不在此列，请对其重建分区表或修改ID（两者其一）后再次对其进行pvcreate。
### 重建分区表（使用parted）
- 使用```parted```工具在硬盘上创建msdos分区表，若是类似```/dev/sdb2```的卷，则参考```修改分区```一栏即可。
- 方法：
```bash
sudo parted /dev/sda
mklabel msdos
write
yes
```
### 修改分区ID（使用fdisk）
- 如果要使用逻辑卷管理，需要将分区id改为```8e```，才能创建物理卷。
- 方法：
```bash
sudo fdisk /dev/sdb2
t # 修改分区代码
2 # 选择2号分区
L # 列出可选择的修改代码
# 8e Linux LVM
8e # 选择8e
# Changed type of partition 'Linux' to 'Linux LVM'
w
# The partition table has been altered!
```
## 创建卷组
- 创建卷组使用```vgcreate```命令。
```bash
sudo vgcreate dvg /dev/sd[ac-g]
```
- 这里```dvg```是本人取的卷组名字。
- 拓展卷组使用```vgextend```命令
```bash
sudo vgextend dvg /dev/sdh
```
- 然后使用以下命令查看卷组：
```bash
vgdisplay
vgs
vgscan
```
## 创建逻辑卷
- 创建逻辑卷使用```lvcreate```命令：
```bash
sudo lvcreate -n dvl -l 100%free dvg
```
- 然后使用以下命令查看逻辑卷：
```bash
lvdisplay
lvs
lvscan
ls /dev/mapper/
# 可看到出现了一个符号链接 dvg-dvl
```
- 此处```dvg```是卷组名称，```dvl```是逻辑卷名称
## 格式化并挂载逻辑卷
- 格式化使用```mkfs```家族命令即可。本人将其格式化为BTRFS并挂载到/data/dataGPU01：
```bash
sudo mkfs.btrfs /dev/mapper/dvg-dvl
sudo mount /dev/mapper/dvg-dvl /data/dataGPU01
```
# NFS环境配置
## 第一步：安装NFS相关包
- 本环境采用Ubuntu 20.04 Server，故使用apt安装相关包。
```bash
sudo apt install nfs-common nfs-kernel-server -y
```
- 其中```nfs-common```是NFS客户端工具，用于挂载远端NFS分区；	```nfs-kernel-server```是NFS服务端工具。
- 这里我们需要将```gpu01```节点上的```/data/dataGPU01```以NFS的形式挂载到登陆节点以及```gpu02```、```gpu03```、```gpu04```节点上；将```gpu02```节点上的```/home```以NFS的形式挂载到登陆节点以及```gpu01```、```gpu03```、```gpu04```节点上。
## 第二步：配置NFS服务端
- 在```gpu01```节点上的```/etc/exports```加入以下内容：
```bash
/data/dataGPU01 *(rw,sync,no_root_squash)
```
- 在```gpu02```节点上的```/etc/exports```加入以下内容：
```bash
/home *(rw,sync,no_root_squash)
```
- 这里路径为分享出去的本地路径，*为表示内网中所有节点均有权，亦可指定部分IP；括号中的参数如下表：

参数     |	作用
------ | ----------
ro|	只读(read only)
rw	|读写(read write)
root_squash|	当NFS客户端以root管理员访问时，映射为NFS服务器的匿名用户(nobody)
no_root_squash|	当NFS客户端以root管理员访问时，映射为NFS服务器的root管理员
all_squash|	无论NFS客户端使用什么账户访问，均映射为NFS服务器的匿名用户
sync|	NFS先写入缓存(内存)，再同步到稳定存储(硬盘)，sync表示写入硬盘成功后，才告诉客户端写入成功，保证不丢失数据，效率偏低
async|	写入缓存后就通知客户端写入成功，不关心硬盘是否成功；这样效率更高，但可能会丢失数据
secure|	NFS客户端必须使用NFS保留端口（通常是1024以下的端口），默认选项
insecure|	允许NFS客户端不使用NFS保留端口（通常是1024以上的端口）
anonuid|	指定匿名用户的uid，默认指向nobody
anongid|	指定匿名用户的gid, 即组id,默认指向nobody组

两者分别启动NFS服务端：
```bash
sudo service nfs-kernel-server start
```

## NFS客户端配置
除服务端外，所有其他客户端使用```mount```挂载：
```bash
sudo mkdir -p /data/dataGPU01
sudo mount -t nfs gpu01:/data/dataGPU01 /data/dataGPU01
sudo mount -t nfs gpu02:/home /home
```
### 排错
- 如果没有成功怎么办？看这里：
- ```mount.nfs: access denied by server while mounting xxx:xxx```
说明```/etc/exports```指定目录未配置好或配置后未重启NFS服务端。
- ```mount.nfs: Resource temporarily unavailable```
集群应该很少出现此问题，不过出现此问题可能是相关目录文件系统有所故障等
- 其余自行搜索引擎或论坛搜索

# 结语
本期文章主要阐述了卷组、逻辑卷与NFS配置方法，大家有什么不明白的地方可评论区交流，有任何疏漏与意见可提出来。下期再见！;-)
