# Docker 教学内测交付

当前版本：`3.7.6-beta.1`。源码：[gentactix-dsh-afsim](https://github.com/snow-wind-001/gentactix-dsh-afsim)。

Docker 文件请向 [snowwind001@gmail.com](mailto:snowwind001@gmail.com) 发送邮件申请。完整 AFSIM 教学镜像采用申请授权访问；公开源码不附带 AFSIM 本体。收到镜像仓库访问授权后，在 Docker Desktop 或 Docker CLI 中登录获准的 Docker Hub 账号。镜像地址为 `snowwind001/gentactix-dsh-afsim`，不能假定匿名下载可用。

## 教员首次使用

1. 安装并启动 Docker Engine + Compose v2；Windows 10/11 使用支持当前系统的 Docker Desktop、WSL2 和 Linux containers。此交付为 Linux amd64 镜像，Windows 通过容器运行，尚未完成 Windows 实机验收。
2. 下载发布包并解压，保留根目录 `docker-compose.yml` 和 `docker/` 的相对位置。
3. Windows 双击 `Start-GenTactix.cmd`；Ubuntu 执行或通过终端打开 `docker/start.sh`。脚本在镜像缺失时拉取授权镜像、启动容器并打开 `http://localhost:8080`。首次解包和创建 Wine prefix 较慢，后续复用。
可选执行 `docker/install-menu.sh` 将带图标的启动入口添加到 Ubuntu 应用菜单；解压目录随后不要移动。

4. 在界面“模型配置”填入自己的模型服务地址、模型 ID 和密钥并测试连接。容器里的 `127.0.0.1` 指容器自身；宿主模型服务使用 `host.docker.internal`，局域网 vLLM 使用实际 IP。不附带模型权重或用户 API key。默认中等思考强度、64K 输出预算和 256K 上下文，最终能力以服务支持为准。

默认 `-afsim` 标签包含当前应用需要的 AFSIM 2.9 命令行运行文件和 Wine，无需手工挂载 AFSIM。`-core` 是不含 AFSIM/Wine 的轻量版本，用 `docker compose -f docker-compose.yml -f docker-compose.core.yml up -d` 启动。两者复用代码基础层。AFSIM 的版权和授权条件独立于应用 MIT 许可，原文件内的声明均保留；不包含非运行必需的演示、培训文档和原始书籍扫描素材。

## 申请离线镜像包

若通过邮件申请取得完整离线镜像归档，先将其与启动包放在本机，再导入：

```bash
docker load -i gentactix-dsh-afsim-3.7.6-beta.1-afsim-linux-amd64.tar.gz
docker compose up -d --pull never
```

导入后也可双击 Windows 启动器或使用 `docker/start.sh`；它们复用本地已有镜像，不再下载同一标签。离线归档包括镜像所需基础层，无需登录 Docker Hub；仍需已运行的 Docker 和可访问的本地/局域网模型服务。不包含模型权重。联网影像底图不可用时可使用内置离线海岸线。AFSIM 离线归档按授权申请提供，不放进公开 GitHub Release。

## 启停、更新和数据

```bash
docker compose logs --tail=100
docker compose stop
docker compose start
docker compose pull
docker compose up -d
```

`gentactix-data` 命名卷保存对局、轨迹、加密模型配置、解密密钥、DSH workspace 和 Wine prefix。默认固定 Compose 项目名 `gentactix-dsh-afsim`，解压到新版本目录升级也复用同一数据卷；如自定义项目名则须保持一致。**不要使用 `docker compose down -v`**。配置与密钥要同时备份；Fernet 提供磁盘内容保护，不能防止具有宿主或 Docker 管理权限的人读取解密密钥。请勿把卷备份、对局、密钥上传到公开仓库。

镜像以 UID/GID `10001:10001` 运行；首次命名卷自动取得正确所有权，已有自定义绑定目录需由管理员赋予该 UID/GID 访问权限。不挂载 Docker socket，不需要 privileged。默认仅绑定本机 loopback，校验 Host/Origin，并以只读根文件系统运行；面向公网或多人认证不在此次交付范围。

## 从源码构建

SDK rc5 尚未在官方 PyPI 提供，因此从发布资产获取校验固定的 MIT SDK/runtime wheels，不降级 SDK，也不复制开发者虚拟环境。

```bash
python docker/fetch_sdk.py --directory .cache/docker-sdk
python docker/build_context.py --source . --out .cache/docker-context --sdk-wheels .cache/docker-sdk
# core 不要求 AFSIM。构建完整授权镜像时，在上一命令增加 --afsim-runtime /合法运行包目录
# 输出目录必须不存在，构建器不会遍历整个开发目录或拷贝个人配置。
docker build --target core -f .cache/docker-context/docker/Dockerfile -t gentactix:core .cache/docker-context
```

完整教学镜像由授权分发者将 AFSIM 运行集加入私有 build context 后选择 `--target afsim` 构建。二进制和源构建所需 SDK wheels 均不进入公开 Git；wheel SHA、上游 commit、许可和本地打包修补说明见 `sdk-wheels.json` 与 `licenses/dsh/`。

## 验收与适用边界

`/api/health` 是服务存活检查，不能代表模型连接、历史效能或 AFSIM 规则全部验收。交付报告分别记录网页/API、配置持久化、DSH 原生 MCP、真实 AFSIM 执行和镜像/数据卷体积。当前候选用于限定场景教学内测；全会战历史效能、长周期组合和所有场景不可据基础链路成功宣称完全通过。
