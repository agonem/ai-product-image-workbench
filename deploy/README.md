# 内网部署说明（Ubuntu + Docker）

已在测试服务器 10.2.2.110（Ubuntu 20.04、OpenSSL 1.1.1、Docker Compose v2.35，经镜像加速拉取 Docker Hub 镜像）实际部署通过；Ubuntu 24.04 同样适用。

一台服务器，同事在浏览器里用 `https://服务器IP/` 访问。只开放 80（自动跳转）和 443 端口；数据库、Java 接口和 Worker 只在 Docker 内部网络里互通。

| 容器 | 作用 |
| --- | --- |
| `web` | nginx：提供页面，把 `/api/` 转给 Java（校验内部证书） |
| `business` | Java 业务服务（prod-local 生产模式，HTTPS） |
| `worker` | Python Worker：调用生成模型、导出尺寸、叠加中文文字（思源黑体 SC） |
| `db` | PostgreSQL 17 |

## 1. 部署前确认

- 服务器已装 Docker Engine 与 `docker compose` 插件；当前用户在 `docker` 组里（能不加 sudo 运行 `docker ps`）。
- **构建镜像时**服务器要能访问 Docker Hub、Maven Central、npm、PyPI、Debian 软件源。不能访问时见第 7 节“离线构建”。
- **运行时** Worker 要能访问 `https://openrouter.ai`（直连或公司代理）。需要代理时，在 `deploy/.env` 里填 `OPENROUTER_PROXY_URL=http://代理地址:端口`（只用于模型调用）。
- 80、443 端口没有被占用；被占用就换端口（见第 2 节末尾），访问地址随之带端口。

## 2. 首次安装

```bash
git clone <仓库地址> /opt/workbench        # 或把仓库拷贝到服务器
cd /opt/workbench/deploy
./init.sh 192.168.1.20 admin              # 换成服务器 IP 和首个管理员账号名
```

`init.sh` 会提示输入首个管理员密码（15–128 位），并生成：`secrets/`（数据库密码、Worker 令牌、密钥加密主密钥、内部证书、管理员引导文件）、`.env`、`workbench-ca.crt`。它拒绝覆盖已有安装。

```bash
docker compose up -d --build              # 首次构建约 5–15 分钟
./check.sh                                # 上线检查，不调用模型、不改数据
```

**80 或 443 端口已被占用时**（`init.sh` 检测到会直接提示）：初始化时指定其他端口，例如

```bash
HTTP_PORT=8080 ./init.sh 192.168.1.20 admin                   # 只换 80
HTTP_PORT=8080 HTTPS_PORT=8443 ./init.sh 192.168.1.20 admin   # 两个都换
```

已经初始化过的：编辑 `deploy/.env` 里的 `HTTP_PORT=` / `HTTPS_PORT=`，再执行 `docker compose up -d`。HTTPS 不是 443 时访问地址要带端口，如 `https://192.168.1.20:8443/`。查看端口被谁占用：`sudo ss -ltnp | grep ':80 '`。服务器开了防火墙（`sudo ufw status` 显示 active）时放行新端口：`sudo ufw allow 8080/tcp`。

## 3. 首次登录后（必须做）

1. 浏览器打开 `https://服务器IP/`，用管理员登录。
2. 删除引导文件：`rm secrets/bootstrap/admin.json`（账号已写入数据库，之后不再读取）。
3. 右上角“账号与安全 → 供应商配置”：模型 `openai/gpt-image-2`，provider_tag `openai`，填 OpenRouter API Key，勾选“保存后立即启用”。密钥加密保存，页面只显示掩码。
4. “账号与安全 → 账号管理”：给运营同事创建账号（普通用户）。
5. 上线冒烟：三个入口各生成 1 张（会产生真实费用，约每张 0.015 美元），点“对照原图”检查商品，再下载。

## 4. 让同事电脑不再提示“不安全”

证书由本机生成，浏览器默认不认识。把 `deploy/workbench-ca.crt` 发给同事：Windows 双击 → 安装证书 → 当前用户 → “将所有证书放入下列存储” → 受信任的根证书颁发机构。这张证书只对本服务器 IP 有效（名称约束），不能用来冒充其他网站。不安装也能用，只是每次要点“继续访问”。

## 5. 日常运维

| 操作 | 命令（在 `deploy/` 目录） |
| --- | --- |
| 查看状态 | `docker compose ps` |
| 看日志 | `docker compose logs -f business worker` |
| 重启 | `docker compose restart` |
| 更新版本 | `git pull && docker compose up -d --build && ./check.sh` |
| 停止 | `docker compose down`（数据保留） |

登录会话默认 15 分钟到期（`PROD_SESSION_SECONDS=900`），可在 `.env` 里调整（60–86400 秒）后 `docker compose up -d`。

数据位置：数据库在 Docker 卷 `product-image-workbench_db-data`，原图与生成结果在 `deploy/data/objects`，Worker 回执在 `deploy/data/journal`。`secrets/` 必须保留：丢失 `provider_master_key` 后已保存的 API Key 无法解密，需要重新录入。

## 6. 常见问题

| 现象 | 处理 |
| --- | --- |
| 生成失败 `PROVIDER_UNAVAILABLE` | 检查“供应商配置”是否已启用；运行 `./check.sh` 看能否访问 openrouter.ai |
| 生成失败并提示字体（`TEXT_FONT_UNAVAILABLE`） | `docker compose build worker && docker compose up -d worker` |
| 页面打不开 | `docker compose ps` 看 `web`、`business` 是否在运行；`docker compose logs business` |
| Worker 日志反复出现 `worker_retry` | Java 未就绪或证书不匹配；等 1 分钟再看，仍有就查 `docker compose logs business` |

## 7. 离线构建（服务器不能访问公网时）

在一台能联网、装有 Docker 的机器上，在同一份仓库的根目录执行：

```bash
for name in business worker web; do
  docker build -f deploy/$name/Dockerfile -t product-image-workbench/$name:local .
done
docker pull postgres:17
docker save product-image-workbench/business:local product-image-workbench/worker:local \
  product-image-workbench/web:local postgres:17 | gzip > workbench-images.tar.gz
```

把 `workbench-images.tar.gz` 和仓库拷到服务器，`docker load < workbench-images.tar.gz`，再按第 2 节执行 `./init.sh`，启动时用 `docker compose up -d`（不带 `--build`）。

## 8. 安全要点

- `secrets/`、`.env`、`data/` 不进 Git（已在 `.gitignore`），也不要打包发给别人；只有 `workbench-ca.crt` 可以分发。
- `secrets/ca.key` 能签发本服务器证书，只留在服务器上。
- 结果一律“待人工审核”；系统只生成和下载，不会自动上架。
