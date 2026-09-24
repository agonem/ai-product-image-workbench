# 母婴商品图工作台

T01 开发骨架 + T03 契约与数据库基线 · 2026-09-24

当前已有可运行的 Vue 3 + TypeScript 前端、Java Spring Boot 业务服务、Python FastAPI 图像服务。页面可检查 Java 连接；三端共用任务 Schema 和测试样例，Java 管理 PostgreSQL 迁移及幂等约束。上传、生成、账号、任务 HTTP 写入和消息队列执行尚未实现。

需求 PRD-G03/G06、PRD-S01/S02/S03；任务 T01/T03；验收 ACC-T01/ACC-T03。商品保真、三个独立入口、仅生成不发布等边界继续有效；本仓库未确定拼多多平台规则或 AI 供应商。

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

该命令创建并停止一次性本机测试数据库；普通 check.py 不包含数据库测试。安装和环境变量见 [T03 开发指南](docs/09-T03契约与数据库开发.md)。

开发时在三个独立终端分别运行：

```text
python scripts/dev.py business
python scripts/dev.py image
python scripts/dev.py frontend
```

打开 [本地工作台](http://127.0.0.1:5173)，应显示“业务服务已连接”。Ctrl+C 停止服务。默认只监听本机，无密钥、无数据库也能启动。配置覆盖、原生命令、格式修复及 Windows JDK 说明见 [T01 开发指南](docs/07-开发环境与版本选择.md)。数据库仅在显式 database profile 启用。

## 目录

```text
frontend/          Vue 页面、Java 健康客户端、任务契约校验
business-service/  Java API、契约/指纹校验、Flyway SQL、数据库集成测试
image-service/     Python 内部 HTTP 服务、离线任务契约校验
contracts/         Draft 2020-12 Schema、三端共用正反例
scripts/           启动、聚合检查、HTTP 冒烟、隔离数据库验证
.github/workflows/ Windows / Ubuntu 代码检查、PostgreSQL 集成测试
```

前端只访问 Java；Python 不连接业务数据库。健康接口只说明进程可响应，不代表业务或依赖就绪。T03 的校验器尚未接入未实现的任务路由；不可将健康服务作为生产业务部署。

## 文档导航

- [AGENTS.md](AGENTS.md)：工作边界和完成标准。
- [01 产品设计与开发方案](docs/01-产品设计与开发方案.md)：需求与架构。
- [02 接口与数据契约](docs/02-接口与数据契约.md)：健康接口、T03 规范及后续业务接口。
- [03 验收标准与测试样本](docs/03-验收标准与测试样本.md)：业务验收、ACC-T01/ACC-T03。
- [04 待决策事项](docs/04-待决策事项.md)：P0 仍待业务确认。
- [05 实施任务清单](docs/05-实施任务清单.md)：依赖与交付状态。
- [06 交互线框与设计规范](docs/06-交互线框与设计规范.md)：业务页面约束。
- [07 开发环境与版本选择](docs/07-开发环境与版本选择.md)：T01 环境与兼容性。
- [08 T01 交付记录](docs/08-T01交付记录.md)：T01 历史证据。
- [09 T03 契约与数据库开发](docs/09-T03契约与数据库开发.md)：新增版本、使用方式、数据库验证。
- [10 T03 交付记录](docs/10-T03交付记录.md)：文件、实际命令、结果与未完成项。
- [Worker 请求 Schema](contracts/task.schema.json)：已固化的任务请求 v1。

新增任务引用需求和任务 ID，遵守“契约/验收 → 实现 → 检查 → 记录”。P0 未定时只推进不受影响的部分。
