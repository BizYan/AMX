# 平台运维与发布负责人操作手册

## 1. 角色定位

平台运维与发布负责人对系统可用性、运行风险、故障处置、版本发布、OCI 部署、生产验证和回滚负责。该角色必须基于命令和系统证据判断状态，不得把“PR 已合并”或“工作流已启动”表述为“生产已发布”。

## 2. 主要入口与工具

| 入口或工具 | 用途 |
|---|---|
| `/system-health`、`/health` | 系统健康、能力准备度和风险 |
| `/agent-ops` | Agent 运行、任务、事件、取消和重试 |
| `/providers` | Provider 健康、运行和回退 |
| `/integrations` | 同步、Webhook、入站、投递和事故 |
| `/quotas` | 使用量、限流、熔断和告警 |
| `/exports` | 导出任务、产物和失败重试 |
| `/audit` | 操作与治理证据 |
| GitHub Actions | CI、Release 和生产部署 |
| OCI SSH / Docker Compose | 生产状态、日志、健康和回滚 |

## 3. 日常运行检查

建议按风险分层检查：

### 每日

- 生产 `/health` 是否正常；
- API、Web、Worker、数据库和 Redis 容器状态；
- Agent 和导出失败任务；
- Provider 健康与异常率；
- 集成事故、Webhook 和 Outbox 堆积；
- 配额、限流和熔断状态。

### 每次发布后

- GitHub Actions 部署结果；
- 生产健康检查；
- 登录、当前用户、项目、文档、准备度和验收关键 Smoke；
- OCI 当前提交与请求版本一致；
- 工作树没有非预期改动；
- GitNexus 服务健康并完成索引刷新；
- GitHub Release 与生产 Deployment 状态一致。

## 4. 运行故障处置

### 4.1 Agent 或工作流失败

1. 在 Agent 运行中心检查运行、任务和事件；
2. 判断是输入、工作流、Skill、Agent、Provider、配额还是 Worker 问题；
3. 对可恢复故障执行重试；
4. 对错误配置先修复再重试；
5. 避免对不可重入任务盲目重复执行；
6. 保留故障原因和恢复证据。

### 4.2 Provider 故障

检查连接、健康、版本、能力、限流和最近运行。必要时停用异常 Provider、启用回退或暂停相关自动化。确认恢复后再逐步放量。

### 4.3 集成故障

查看生产联调指挥台、同步运行、入站事件、投递和 Outbox。重试前确认失败是否会产生重复数据，并核对外部系统幂等能力。

### 4.4 导出故障

查看导出任务错误、输入文档、模板、变量和存储状态。门禁失败属于业务准备问题，应交由项目负责人处理；技术执行失败才由运维处置。

## 5. 发布概念

必须区分：

- **PR 合并**：代码进入目标分支。
- **GitHub Release**：语义化版本标签通过发布验证，并形成正式版本记录。
- **生产 Deployment**：某个批准版本被部署到 OCI。

完整版本发布要求 Release 和 Deployment 均成功，并通过生产验证。页面显示最新提交不等于生产已运行该提交。

## 6. 标准发布流程

### 6.1 发布前门禁

1. 确认目标 PR 已通过 CI、审查和业务验收；
2. 确认 `main` 是预期发布源；
3. 运行交付准备度检查；
4. 对发布关键路径执行必要的确定性 E2E 或 Smoke；
5. 检查数据库迁移、配置和回滚方案；
6. 确认无密钥、Token、私钥或生产 `.env` 进入仓库。

### 6.2 创建版本

使用语义化版本标签：

```powershell
git checkout main
git pull --ff-only
git tag -a v0.3.0 -m "AMX v0.3.0"
git push origin v0.3.0
```

标签触发 Release 工作流。只有工作流通过并形成 GitHub Release，版本发布记录才完整。

### 6.3 部署生产

优先使用仓库的 GitHub Actions 生产部署工作流，并指定已批准标签或 Ref。生产部署路径为：

```text
/home/ubuntu/amx/production/AMX
```

生产部署必须使用受控 GitHub Environment 和 Secrets。不要把生产凭据写入命令日志或仓库。

### 6.4 生产验证

至少验证：

- `https://amx.yuanda.win/health`
- 登录和当前用户；
- 项目与文档查询；
- 准备度和验收关键路径；
- OCI 当前提交；
- 容器状态和必要日志；
- GitNexus 服务健康与索引刷新；
- GitHub production Deployment 成功。

## 7. OCI 操作

生产访问使用既有 SSH 配置和密钥路径。不得输出私钥内容。

### 7.1 查看容器和日志

```bash
cd /home/ubuntu/amx/production/AMX
docker compose -f infra/docker-compose.yml ps
docker compose -f infra/docker-compose.yml logs --tail=200 api
docker compose -f infra/docker-compose.yml logs --tail=200 worker
docker compose -f infra/docker-compose.yml logs --tail=200 web
```

### 7.2 健康检查

```bash
cd /home/ubuntu/amx/production/AMX
bash infra/deploy/health-check.sh --base-url https://amx.yuanda.win
```

生产 `.env` 权限应为 `600`，PostgreSQL、Redis、API 和 Web 的绑定地址必须保持为本机地址。部署预检会拒绝公开绑定。

## 8. 回滚

出现以下情况应立即考虑回滚：

- 部署重试后 `/health` 仍失败；
- 引导管理员无法登录；
- 工作台、项目、文档或设置出现客户端异常；
- Worker 持续退出；
- 数据库迁移失败或导致 API 重启循环。

使用已知良好标签或 SHA 回滚：

```bash
cd /home/ubuntu/amx/production/AMX
bash infra/deploy/rollback-oci.sh \
  --base-path /home/ubuntu/amx/production/AMX \
  --ref <known-good-tag-or-sha>
bash infra/deploy/health-check.sh --base-url https://amx.yuanda.win
```

回滚后仍需执行关键 Smoke，并记录事故、影响和后续修复计划。

## 9. 发布与运维安全

- 不绕过 CI、审查、生产 Environment 和验证门禁；
- 不手工随意修改生产代码；
- 不在日志、PR、工单或聊天中暴露密钥；
- 不把生产 `.env` 纳入 Git；
- 不使用强制推送或重写发布历史；
- 部署前确认数据库迁移可升级且有恢复方案；
- 重试集成、Agent 或导出任务前确认幂等性；
- 保留发布、部署、健康、Smoke 和回滚证据。

## 10. 发布记录模板

每次发布至少记录：

```text
版本/Ref：
包含 PR：
GitHub Release：
生产 Deployment：
OCI 当前提交：
健康检查：
关键 Smoke：
GitNexus 健康/刷新：
已知风险：
回滚目标：
结论：
```

## 11. 运维与发布检查清单

- [ ] 运行状态、失败任务和 Provider 健康已检查
- [ ] 配额、限流、熔断和集成事故已检查
- [ ] 发布前 CI、验证和回滚方案通过
- [ ] GitHub Release 已形成
- [ ] 生产 Deployment 成功
- [ ] 生产健康、关键 Smoke 和来源提交一致
- [ ] GitNexus 服务健康并完成刷新
- [ ] 发布与故障证据已记录
