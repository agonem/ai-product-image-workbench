# T06-PROD-B2：Python 协调会话到期

需求 PRD-G10；范围 ACC-T06-PROD B2，兼顾既有 B1–B5 回归。2026-09-27。

## 范围与验收

浏览器不再启动 psql。测试专用 Python 协调器监听本轮私有目录中的原子文件同步点；仅允许到期、分页造数两个固定动作，不接受 SQL。浏览器发送本次普通用户及管理员令牌的 SHA-256；Python 先确认两条记录有效，精确更新这两条记录，再确认同一哈希对应记录已到期，才写确认文件。浏览器核对确认哈希、数量，验证同一令牌的 API 均为 401，并保留两个页面返回登录页的原断言。未增加产品接口或测试后门。

分页造数也移至 Python。浏览器环境不再传递数据库密码、psql 命令及 schema；同步超时、非法哈希、更新或回查数量不符均失败。测试进程结束时只清理本次启动的进程。

## 交付方实际运行

- `uv run --frozen --project image-service ruff check scripts`：通过。
- `uv run --frozen --project image-service ruff format --check scripts/check_t06_prod.py scripts/check_t06_sync.py scripts/test_t06_sync.py`：通过。
- `python -m unittest discover -s scripts -p 'test_*.py'`：10 项通过，含精确哈希、非法输入、有效会话不足、更新/回查失败。
- `npm --prefix frontend run check`：整条命令退出 0；格式、ESLint、73 项测试、Vue 类型检查和 Vite 构建通过。
- `BUSINESS_TEST_JAR='D:/Project/ai-product-image-workbench/business-service/target/business-service-t06-prod.jar' python scripts/check_db.py --t06-prod-only`：退出 0；Python `expire`/`seed` 同步点与 B1–B5 浏览器断言完成。证据目录 `.artifacts/postgres/20260927-222323-ade5b5/t06-prod`（不提交运行日志/数据库）。

使用已有独立 JAR、临时数据库、随机独立 Java/Vite 端口、独立前端构建目录；未重建或覆盖常驻开发 JAR，未终止常驻开发服务。测试证书只加入本轮受信集合，产品 TLS 校验未修改。

## 验收来源与剩余范围

用户已确认此前三个提交的独立验收完成。本次上述执行结果均为**交付方证据**，本次 B2 修复待独立验收方复跑，不宣称独立通过。生产受信证书部署、完整 Worker TLS、容量目标、真实商品图与人工验图均不在本次完成范围。
