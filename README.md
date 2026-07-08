# 复星保德信 2026 年度红利实现率监控

自动监控复星保德信人寿官网，每天北京时间 10:00 检查 **2026 年度（红利分配期间 2026/07/01 - 2027/06/30）** 红利实现率是否公布，通过 **钉钉群机器人** 推送通知到钉钉。

## 监控原理

脚本访问复星保德信官网“红利实现率”查询页，读取“分红年度”下拉框中的年份选项列表。

- 分红年度 `2025`：对应 2025/07/01 - 2026/06/30（已公布）
- 分红年度 `2026`：对应 2026/07/01 - 2027/06/30（当前监控目标）

判据：当下拉框出现 `2026` 时，判定为“已公布”。

## 仓库结构

```text
fosun-dividend-monitor/
├── check_fosun_dividend.py
├── .github/workflows/check_dividend.yml
└── README.md
```

## 通知方式

使用钉钉“自定义群机器人” Webhook 推送。

- 未公布：`⏳ 复星保德信2026年度红利实现率尚未公布`
- 已公布：`✅ 复星保德信2026年度红利实现率已公布`
- 脚本异常：`⚠️ 复星保德信红利监控脚本异常`

如果不想每天收到“未公布”通知，可在 `check_fosun_dividend.py` 的 `else` 分支注释 `SendDingTalk(...)` 那一行。

## 部署步骤

### 1. 创建钉钉群机器人

在钉钉群里添加“自定义机器人”，推荐安全设置选择“加签”。

保存以下信息：

- Webhook 地址（完整 URL）
- 加签密钥（`SEC` 开头）

### 2. 推送代码到 GitHub

```bash
git init
git add .
git commit -m "复星保德信2026红利实现率监控-钉钉通知"
git branch -M main
git remote add origin https://github.com/<你的用户名>/fosun-dividend-monitor.git
git push -u origin main
```

### 3. 配置 GitHub Secrets

仓库路径：`Settings -> Secrets and variables -> Actions`

新增两个 Secret：

- `DINGTALK_WEBHOOK`：机器人 Webhook 地址
- `DINGTALK_SECRET`：机器人加签密钥（关键词模式可留空）

### 4. 启用并测试 Actions

1. 进入仓库 `Actions` 页面，启用 workflow。
2. 手动触发：`检查复星保德信2026红利实现率 -> Run workflow`。
3. 约 2-3 分钟后，钉钉应收到通知消息。

## 常见问题排查

- `errcode: 310000`：Webhook 或 Secret 配置错误。
- 使用了 IP 白名单：GitHub Actions 出口 IP 不固定，建议改为“加签”。
- 关键词模式发不出：确认消息包含关键词（建议关键词设为“复星保德信”）。
- 页面结构改版：脚本会进入异常分支并发送告警，请更新页面选择器。

## 停止任务

在 `.github/workflows/check_dividend.yml` 注释掉：

```yaml
schedule:
  - cron: "0 2 * * *"
```

或直接删除仓库。

## 手动查询入口

官网页面：

<https://www.pflife.com.cn/fbofficialweb/Special?submenu=Special&itemsmenu=NewProducts&childmenu=DividendProducts&redFitShowflag=redFitShow>
