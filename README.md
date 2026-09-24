# 母婴商品图工作台

T01 开发骨架 · 2026-09-24 · 公司内部图片生成工作台

当前已有可运行的 Vue 3 + TypeScript 前端、Java Spring Boot 业务服务、Python FastAPI 图像服务骨架。页面可以真实检查 Java 服务连接。上传、生成、账号、数据库、任务队列及三个业务入口尚未实现。

需求：PRD-G06；任务：T01；验收：ACC-T01。商品保真、三个独立入口、仅生成不发布等既定边界继续有效；本仓库不代表已确认任何拼多多平台规则或 AI 供应商。

## 快速运行

准备 Node 24.15.0（npm 11.x）、JDK 21、Python 3.13、uv 0.12.5。Maven 由项目 Wrapper 提供。以下从仓库根目录执行：

```text
npm --prefix frontend ci
uv sync --frozen --project image-service
python scripts/check.py
python scripts/smoke.py
```

然后在三个独立终端中分别运行：

```text
python scripts/dev.py business
python scripts/dev.py image
python scripts/dev.py frontend
```

打开 [本地工作台](http://127.0.0.1:5173)，应显示“业务服务已连接”。各终端 Ctrl+C 停止服务。默认仅监听本机；无真实密钥也能运行。配置覆盖、原生命令、格式修复及 Windows JDK 说明见 [开发指南](docs/07-开发环境与版本选择.md)。

## 目录

```text
frontend/          Vue 页面、Java 健康客户端、格式/静态/类型检查
business-service/  Java 公共 API、Maven Wrapper、HTTP 契约测试
image-service/     Python 内部 HTTP 服务、uv.lock、Ruff/pytest
scripts/           跨平台启动、聚合检查和实际 HTTP 冒烟
.github/workflows/ Windows / Ubuntu CI
contracts/         后续任务使用的任务 Schema 草案
```

前端只通过 `/api` 访问 Java；Python 不直接写业务数据库。健康接口只说明进程可响应，不代表后续业务功能或依赖已就绪。

## 文档导航

- [AGENTS.md](AGENTS.md)：agent 工作边界、变更流程和完成标准。
- [01 产品设计与开发方案](docs/01-产品设计与开发方案.md)：需求、架构、模块与里程碑。
- [02 接口与数据契约](docs/02-接口与数据契约.md)：已实现的 T01 健康接口，以及尚未实现的业务接口草案。
- [03 验收标准与测试样本](docs/03-验收标准与测试样本.md)：业务验收与 ACC-T01。
- [04 待决策事项](docs/04-待决策事项.md)：P0 决定仍待业务确认。
- [05 实施任务清单](docs/05-实施任务清单.md)：任务依赖与交付门槛。
- [06 交互线框与设计规范](docs/06-交互线框与设计规范.md)：后续业务页面约束。
- [07 开发环境与版本选择](docs/07-开发环境与版本选择.md)：安装、启动、检查、CI、版本兼容依据。
- [08 T01 交付记录](docs/08-T01交付记录.md)：文件清单、实际命令、测试结果及未完成项。
- [任务 Schema 草案](contracts/task.schema.json)：T03 再实现、迁移和验证。

新增开发任务先引用任务 ID 与需求 ID，遵守“更新契约/验收 → 实现 → 检查 → 记录”的流程。涉及 P0 决定时只推进不受其阻塞的部分。
