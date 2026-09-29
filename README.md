# 母婴商品图工作台

**当前进度只看 [docs/08 当前状态与剩余任务](docs/08-当前状态与剩余任务.md)。** 2026-09-28 用户决定收缩范围（ADR-20260928）：删除网页付费试生成、供应商检查中继和场景 v2，从 [01 产品设计](docs/01-产品设计与开发方案.md) 的核心要求继续。

已有：Vue 3 + TypeScript 前端、Java Spring Boot 业务服务（任务/outbox/幂等重试/私有存储/生产本地账号与项目隔离）、Python 独立 Worker。场景图 v3 可真实生成背景并在本地合成原图商品层（新图待人工审核）。赠品图、卖点图、网页内抠图确认、删除功能尚未完成，按 docs/08 第 5 节顺序推进。商品保真、三个独立入口、仅生成不发布等边界继续有效；拼多多平台规则未核实。

## 快速运行

准备 Node 24.15.0（npm 11.x）、JDK 21、Python 3.13、uv 0.12.5。Maven 由 Wrapper 提供。从仓库根目录执行：

```text
npm --prefix frontend ci
uv sync --frozen --project image-service
python scripts/check.py
python scripts/smoke.py
```

数据库验证另需 PostgreSQL 17 原生工具，设置 PG_BIN 后运行：

```text
python scripts/check_db.py
```

该命令创建并停止一次性本机测试数据库，并启动 Java/独立 Worker 验证 T05 崩溃恢复和 T04 开发账号/原图上传；普通 check.py 不包含数据库测试。环境变量见 [T03 开发指南](docs/09-T03契约与数据库开发.md)；任务运行、凭据和恢复方式见 [T05 运行指南](docs/11-T05运行与恢复.md)。

开发时在三个独立终端分别运行：

```text
python scripts/dev.py business
python scripts/dev.py image
python scripts/dev.py frontend
```

网页内“生成抠图候选”需要图像服务（`dev.py image`）在运行：Java 与图像服务配置相同的 `IMAGE_SERVICE_TOKEN`，Java 另配 `IMAGE_SERVICE_URL`（见 `.env.example`、[02 §15](docs/02-接口与数据契约.md)）；未配置时页面明确提示抠图服务不可用。

打开 [本地工作台](http://127.0.0.1:5173)，显示明确的开发环境登录页。默认 Java 健康模式无登录/业务能力；实际使用须先按 [T04 指南](docs/13-T04开发账号与上传.md) 配置私有本地账号、数据库及 `dev-local`，再启动 business/frontend（任务执行另启 worker）。Ctrl+C 停止服务。配置覆盖、原生命令及 Windows JDK 说明见 [T01 开发指南](docs/07-开发环境与版本选择.md)。

T06 提供三独立入口、原图上传/查看、任务提交、状态/重试、项目历史；真实生成尚未接入，普通上传仍受 alpha 审核阻塞。完整页面验收使用隔离数据库和随机开发账号：

```text
npm --prefix frontend exec -- playwright install chromium
python scripts/check_db.py --t06-only
```

先运行 `python scripts/check.py` 构建 Java。上述命令会启动 dev-local Java、Vite、普通 Worker，并运行真实 Chromium 页面检查；不会向已有数据库写测试数据。配置、合成夹具与限制见 [T06 交付说明](docs/history/15-T06-工作台交付.md)。

## 目录

场景图（v3）：Java 端 `SCENE_ENABLED` 等部署配置、Worker 私有 OpenRouter 配置与真实调用证据见 [history/27](docs/history/27-场景导出与管理设置实施.md) 和 [history/26](docs/history/26-T09场景链路与能力阻塞.md)；模拟供应商链路 `python scripts/check_db.py --t09-only` 不计真实生成。

T02-SYN 提供离线合成素材分割/alpha/变换与合成实验，可在 `image-service/` 运行 `uv run --frozen python -m image_service.poc_demo --output ../.artifacts/t02-my-review`。目录必须尚不存在。对照与参数标记为合成测试、待人工确认，不接 Worker，不代表真实商品生成。依赖与结果见 [T02 合成预研](docs/history/20-T02-合成素材预研.md)。

生产认证页面构建默认使用 `production-local`，开发服务器默认 `development-only`；仅显式 `VITE_AUTH_MODE` 可覆盖，不自动回退。生产部署须以 HTTPS 提供静态页面，同源 `/api` 代理到受信 Java HTTPS，保持证书校验。页面令牌仅内存保存，刷新重新登录。隔离验证、独立 JAR/端口命令及能力边界见 [T06 生产认证接入](docs/18-T06-生产认证接入.md)，统一 smoke 支持 `BUSINESS_TEST_JAR` 和 `SMOKE_BUSINESS_PORT/SMOKE_IMAGE_PORT/SMOKE_FRONTEND_PORT`。

```text
frontend/          Vue 三入口工作台、Java API 客户端、契约与页面测试
business-service/  Java API、契约/指纹校验、Flyway SQL、数据库集成测试
image-service/     Python 内部 HTTP 服务、离线任务契约校验
contracts/         Draft 2020-12 Schema、三端共用正反例
scripts/           启动、聚合检查、HTTP 冒烟、隔离数据库验证
.github/workflows/ Windows / Ubuntu 代码检查、PostgreSQL 集成测试
```

前端只访问 Java；Python 不连接业务数据库。健康接口只说明进程可响应，不代表业务或依赖就绪。旧 runtime/dev-local 仍有本机开发限制；prod-local 账号 API 使用独立的数据库认证和 TLS，不能直接把开发配置用于生产。生产初始化、配置模板与验证见 [T04 生产账号说明](docs/17-T04-生产本地账号.md)。

## 文档导航

- [AGENTS.md](AGENTS.md)：工作边界和完成标准。
- [00 验收索引](docs/00-任务交接.md)：待独立验收条目。
- [01 产品设计与开发方案](docs/01-产品设计与开发方案.md)：需求与架构（核心要求基线）。
- [02 接口与数据契约](docs/02-接口与数据契约.md)、[03 验收标准](docs/03-验收标准与测试样本.md)、[04 待决策事项](docs/04-待决策事项.md)、[05 实施任务清单](docs/05-实施任务清单.md)、[06 交互线框](docs/06-交互线框与设计规范.md)。
- [08 当前状态与剩余任务](docs/08-当前状态与剩余任务.md)：**唯一状态入口**。
- 运行指南：[07 开发环境](docs/07-开发环境与版本选择.md)、[09 数据库](docs/09-T03契约与数据库开发.md)、[11 任务运行与恢复](docs/11-T05运行与恢复.md)、[13 开发账号与上传](docs/13-T04开发账号与上传.md)、[17 生产本地账号](docs/17-T04-生产本地账号.md)、[18 生产页面](docs/18-T06-生产认证接入.md)。
- [history/](docs/history/)：2026-09-28 前的逐次交付记录，仅作证据追溯。
- [Worker 请求 Schema](contracts/task.schema.json)：已固化的任务请求 v1。

新增任务引用需求和任务 ID，遵守“契约/验收 → 实现 → 检查 → 记录”。P0 未定时只推进不受影响的部分。
