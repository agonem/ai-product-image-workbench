# 母婴商品图工作台

T01 开发骨架 + T03 契约数据库 + T05 任务运行 + T04 开发账号与上传 + T06 开发工作台 · 2026-09-26

当前已有 Vue 3 + TypeScript 前端、Java Spring Boot 业务服务、Python FastAPI 图像服务及独立 Worker。Java 管理任务/attempt/outbox、状态、幂等重试和私有文件存储；Worker 通过内部 HTTP 领取租约并持久化回执。T04 提供开发账号/上传，以及独立 prod-local 生产本地账号 API（`9a1f685` 已通过独立验收）。T06-PROD 补充生产登录、会话处理、本人改密和账号管理页面，待独立验收。完整生产部署与图像生成算法尚未完成，普通 Worker 会明确返回失败。合成图片运输验收使用显式 fixture 模式。

需求 PRD-G02/G03/G06/G08、PRD-S01/S02/S03；任务 T01/T03/T05/T04/T06；验收 ACC-T01/ACC-T03/ACC-T05/ACC-T04-DEV/ACC-T04-PROD/ACC-T06。商品保真、三个独立入口、仅生成不发布等边界继续有效。OpenRouter 真实接入和拼多多规则尚未核实。T02 真实商品/赠品及样本说明未到位，授权已确认。

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

打开 [本地工作台](http://127.0.0.1:5173)，显示明确的开发环境登录页。默认 Java 健康模式无登录/业务能力；实际使用须先按 [T04 指南](docs/13-T04开发账号与上传.md) 配置私有本地账号、数据库及 `dev-local`，再启动 business/frontend（任务执行另启 worker）。Ctrl+C 停止服务。配置覆盖、原生命令及 Windows JDK 说明见 [T01 开发指南](docs/07-开发环境与版本选择.md)。

T06 提供三独立入口、原图上传/查看、任务提交、状态/重试、项目历史；真实生成尚未接入，普通上传仍受 alpha 审核阻塞。完整页面验收使用隔离数据库和随机开发账号：

```text
npm --prefix frontend exec -- playwright install chromium
python scripts/check_db.py --t06-only
```

先运行 `python scripts/check.py` 构建 Java。上述命令会启动 dev-local Java、Vite、普通 Worker，并运行真实 Chromium 页面检查；不会向已有数据库写测试数据。配置、合成夹具与限制见 [T06 交付说明](docs/15-T06-工作台交付.md)。

## 目录

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
- [01 产品设计与开发方案](docs/01-产品设计与开发方案.md)：需求与架构。
- [02 接口与数据契约](docs/02-接口与数据契约.md)：健康接口、T03 规范及后续业务接口。
- [03 验收标准与测试样本](docs/03-验收标准与测试样本.md)：业务验收、ACC-T01/ACC-T03。
- [04 待决策事项](docs/04-待决策事项.md)：已确认用户决定、未决细节及真实验收阻塞。
- [05 实施任务清单](docs/05-实施任务清单.md)：依赖与交付状态。
- [06 交互线框与设计规范](docs/06-交互线框与设计规范.md)：业务页面约束。
- [07 开发环境与版本选择](docs/07-开发环境与版本选择.md)：T01 环境与兼容性。
- [08 T01 交付记录](docs/08-T01交付记录.md)：T01 历史证据。
- [09 T03 契约与数据库开发](docs/09-T03契约与数据库开发.md)：新增版本、使用方式、数据库验证。
- [10 T03 交付记录](docs/10-T03交付记录.md)：文件、实际命令、结果与未完成项。
- [11 T05 运行与恢复](docs/11-T05运行与恢复.md)：runtime/Worker 启动、存储和恢复边界。
- [12 T05 交付记录](docs/12-T05交付记录.md)：文件、实际检查和未完成项。
- [13 T04 开发账号与上传](docs/13-T04开发账号与上传.md)：本地账号、项目 API、上传限制和 D-05 边界。
- [14 T04 可先行交付记录](docs/14-T04可先行交付记录.md)：A1–A8 验收证据、文件和阻塞项。
- [15 T06 工作台交付](docs/15-T06-工作台交付.md)：三入口、dev-local 页面复现、ACC 编号与能力边界。
- [16 用户决定同步](docs/16-T00-用户决定同步.md)：T00-D 文档交付、兼容策略与独立验收关口。
- [17 T04 生产本地账号](docs/17-T04-生产本地账号.md)：样本缺口、生产账号 API、配置及验证证据。
- [18 T06 生产认证接入](docs/18-T06-生产认证接入.md)：生产账号页面、历史契约对比、隔离浏览器与 smoke 验证。
- [Worker 请求 Schema](contracts/task.schema.json)：已固化的任务请求 v1。

新增任务引用需求和任务 ID，遵守“契约/验收 → 实现 → 检查 → 记录”。P0 未定时只推进不受影响的部分。
