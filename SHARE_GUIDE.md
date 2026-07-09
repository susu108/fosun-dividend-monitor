# 复星保德信 2026 红利实现率监控方案说明（可分享版）

本文档用于对外分享本项目的完整方案，包含技术实现流程、部署操作流程、排障方法和日常维护建议。

---

## 1. 方案目标

每天北京时间 10:00 自动检查复星保德信官网“分红年度”下拉选项中是否出现 `2026`，并通过钉钉群机器人推送结果：

- 未公布：`⏳ 复星保德信2026年度红利实现率尚未公布`
- 已公布：`✅ 复星保德信2026年度红利实现率已公布`
- 异常：`⚠️ 复星保德信红利监控脚本异常`

---

## 2. 技术实现流程

## 2.1 总体架构

```text
cron-job.org (每天10:00)
    -> GitHub API: workflow_dispatch
    -> GitHub Actions 执行 check_fosun_dividend.py
    -> Playwright 抓取“分红年度”下拉年份
    -> 判断是否包含 2026
    -> 钉钉机器人推送消息
```

## 2.2 核心判定逻辑

监控脚本 `check_fosun_dividend.py` 的核心判定规则：

- 抓取下拉年份列表 `years`
- 执行 `target_year in years`（目标年 `2026`）

结论分支：

- `True` -> 发送“已公布”强提醒
- `False` -> 发送“未公布”弱提醒
- 异常 -> 发送“脚本异常”提醒

## 2.3 页面抓取策略

为兼容页面结构变化，脚本采用多重兜底策略：

- 通过“分红年度”标签关联定位下拉输入框并点击展开
- 在多个下拉容器中选择“可解析年份最多”的容器
- 兼容不同 DOM 结构与异步渲染
- 对异常路径统一捕获并告警

## 2.4 触发策略说明

当前采用“外部定时触发 GitHub”的方式：

- 触发来源：`cron-job.org`
- 触发方式：调用 GitHub `workflow_dispatch` API
- GitHub 工作流仅保留 `workflow_dispatch`（已注释内置 `schedule`，避免双触发）

该方式相对 GitHub 原生 `schedule` 更稳定。

---

## 3. 仓库结构

```text
Annual_Payout_Monitor/
├── check_fosun_dividend.py
├── .github/workflows/check_dividend.yml
├── README.md
└── SHARE_GUIDE.md
```

---

## 4. 操作流程（从 0 到可运行）

## 4.1 准备钉钉机器人

1. 在钉钉群创建“自定义机器人”
2. 安全设置建议使用“加签”
3. 保存：
   - `Webhook URL`
   - `SEC...` 加签密钥

## 4.2 配置 GitHub Secrets

仓库 -> `Settings` -> `Secrets and variables` -> `Actions`：

- `DINGTALK_WEBHOOK` = 钉钉 Webhook 完整地址
- `DINGTALK_SECRET` = 钉钉加签密钥（使用加签时必填）

## 4.3 配置 cron-job.org 定时触发

在 cron-job.org 创建任务：

- URL:
  `https://api.github.com/repos/<你的用户名>/fosun-dividend-monitor/actions/workflows/check_dividend.yml/dispatches`
- Method: `POST`
- Headers:
  - `Authorization: Bearer <GitHubToken>`
  - `Accept: application/vnd.github+json`
- Body:

```json
{"ref":"main"}
```

- Timezone: `Asia/Shanghai`
- Time: 每天 `10:00`

## 4.4 验证

1. 在 cron-job.org 执行一次 `Test Run`
2. 预期返回 `HTTP 204`
3. GitHub Actions 出现一条新的 `workflow_dispatch` 运行
4. 钉钉收到对应消息

---

## 5. 常见问题排查

## 5.1 cron-job 返回 401

原因：认证失败  
检查：

- `Authorization` 是否为 `Bearer <token>`
- Token 是否过期
- Token 是否对目标仓库有 `Actions: Read and write`

## 5.2 cron-job 返回 404

原因：API 地址不正确  
检查：

- 仓库名是否正确
- workflow 文件名是否为 `check_dividend.yml`

## 5.3 Actions 执行成功但钉钉无消息

检查：

- `DINGTALK_WEBHOOK` / `DINGTALK_SECRET` 是否正确
- 钉钉机器人安全策略是否与脚本一致（加签或关键词）
- Actions 运行日志中是否出现钉钉接口报错

## 5.4 年份抓取不全

脚本已加入下拉容器选择与兜底策略。若后续官网改版导致失效：

- 查看 Actions 错误日志
- 根据页面结构调整下拉定位器

---

## 6. 日常维护建议

- 建议开启 cron-job 失败通知（邮件）
- 每月手动执行一次 Test Run，确认链路健康
- 若收到“脚本异常”消息，优先查看 GitHub Actions 日志
- GitHub Token 到期前提前更新

---

## 7. 变更记录建议

后续每次改动建议记录：

- 改动时间
- 改动内容（例如 cron 时间、文案、选择器）
- 验证结果（204 / Actions 成功 / 钉钉收到）

便于后续快速回溯问题。
