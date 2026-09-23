# Massive Flat Files 每日摄取 timer（QNT-47 阶段 2，**只交付文本，不装主机**）

本页是 QNT-45 `systemd/user/INSTALL.md` 的 Massive 增补。unit 文本放在文档里而不是
`systemd/user/`，原因两条（PR「偏离项」已报）：

1. QNT-45（PR #23）尚未合入 main，`systemd/user/` 目录在 main 上还不存在；
2. QNT-45 的 `tests/test_systemd_units.py` 要求磁盘上的 unit 与 `UNIT_FILES` **逐个相等**，
   本卡若往那个目录加文件，两个 PR 谁后合谁红。QNT-45 合入后由 planner 决定是否把下面两个
   文件移进 `systemd/user/` 并登记进 `UNIT_FILES`。

**为什么不是 `quantime-ingest@massive`：** QNT-45 的模板实例跑的是
`quantime-ingest --source %i daily --since-last`（公开源、`PublicTransport`、水位线续取）。
Massive 走的是另一个入口 `quantime-ingest-us`（需凭据、boto3 只读闸），且幂等键是
「对象 key + ETag」而不是水位线——换实例名不能复用那个模板（QNT-45 INSTALL.md 顶部已预告）。

**订阅期限：** Massive Stocks Starter 于 **2026-10-23** 到期（owner 2026-09-23 裁决）。本 timer
只在订阅期内有意义；到期后 op 注入的 key 失效，每次运行都会以 403 → `coverage=failed` 结束。
不续订就在到期前按第 5 节停用。

## 1. unit 文本

`~/.config/systemd/user/quantime-ingest-massive.service`：

```ini
# quantime · Massive Flat Files 日线（us_stocks_sip/day_aggs_v1）每日增量（QNT-47）。
#
# **本 unit 不含任何凭据。** 四个字段（Access Key ID / Secret / S3 Endpoint / Bucket）由
# `op run` 按 docs/ops/massive-flatfiles.env.tpl 注入子进程环境，读取时 .strip()；
# 不写 Environment=、不写 EnvironmentFile=、不落任何文件（AGENTS.md §3 / ADR-0001）。

[Unit]
Description=quantime Massive Flat Files 日线每日增量
Documentation=https://github.com/QUANTENSOR/QUANTIME/blob/main/docs/ops/massive-systemd.md
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=%h/quantime

# 区间 = 最近 7 个自然日 .. UTC 昨日。幂等键是 key+ETag：已提交且 ETag 未变的日期只列举、
# 不下载（报告里记 skipped_idempotent）；上游改过的文件以 kind='rerun' 写新 batch。
# 7 天窗口让关机一周后的那一次补跑（Persistent=true 只补一次）把缺的日期全取回来。
ExecStart=/usr/bin/env sh -c '\
  cd "%h/quantime" && \
  exec op run --env-file="%h/quantime/docs/ops/massive-flatfiles.env.tpl" -- \
    uv run --package quantime-data --extra ingest quantime-ingest-us \
      --root "%h/quantime" flatfiles \
      --start "$(date -u -d "7 days ago" +%%Y-%%m-%%d)" \
      --end "$(date -u -d "yesterday" +%%Y-%%m-%%d)"'

Nice=10
IOSchedulingClass=idle
TimeoutStartSec=3600
Restart=no

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
# op 需要写自己的会话缓存；除此之外只写数据目录。
ReadWritePaths=%h/quantime/data %h/.config/op
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
RestrictNamespaces=true
LockPersonality=true
SystemCallArchitectures=native
# op 与 1Password 桌面/代理通信需要 AF_UNIX；摄取本身只出 HTTPS。
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX

StandardOutput=journal
StandardError=journal
SyslogIdentifier=quantime-ingest-massive
```

`~/.config/systemd/user/quantime-ingest-massive.timer`：

```ini
[Unit]
Description=每日触发 quantime Massive Flat Files 摄取
Documentation=https://github.com/QUANTENSOR/QUANTIME/blob/main/docs/ops/massive-systemd.md

[Timer]
# Flat Files 次日文件约在美东上午发布（未验证，以首周报告为准）；16:30 UTC（夏令时 12:30 ET / 冬令时 11:30 ET）之后取。
# 当日文件尚未发布时只是列举不到，不算缺口（缺口基线 = 列举到的日期集）。
OnCalendar=*-*-* 16:30:00 UTC
Persistent=true
RandomizedDelaySec=20m
FixedRandomDelay=true
AccuracySec=1m
Unit=quantime-ingest-massive.service

[Install]
WantedBy=timers.target
```

与 QNT-45 unit 的差异只有三处，均因凭据注入：`ExecStart` 经 `op run`；`ReadWritePaths` 多
`%h/.config/op`；`RestrictAddressFamilies` 多 `AF_UNIX`，且去掉了 `MemoryDenyWriteExecute`
（op 二进制是 Go，需要可执行匿名映射；未在本机验证，owner 装前以第 3 节手工跑为准）。

## 2. 前置检查（只读）

```sh
# op 已登录且能读到 Flat Files 条目的四个字段（只看是否成功，不打印值）
op read "op://quant-dev/Massive Quantime Flat Files/Access Key ID" >/dev/null && echo ok

# 两个模板文件自查
cd ~/.config/systemd/user && systemd-analyze verify --user \
  ./quantime-ingest-massive.service ./quantime-ingest-massive.timer
```

## 3. 先手工跑一次

```sh
systemctl --user daemon-reload
systemctl --user start quantime-ingest-massive.service
journalctl --user -u quantime-ingest-massive.service -n 100 --no-pager
cat ~/quantime/data/reports/$(date -u +%Y-%m-%d)/massive/*.md
```

期望退出码 0、报告 `coverage: complete`、`gaps` 为空；首跑之后再跑一次应全部 `skipped`。

## 4. 启用

```sh
systemctl --user enable --now quantime-ingest-massive.timer
systemctl --user list-timers --all --no-pager | grep massive
```

## 5. 停用 / 卸载（订阅到期前必做）

```sh
systemctl --user disable --now quantime-ingest-massive.timer
rm -f ~/.config/systemd/user/quantime-ingest-massive.service \
      ~/.config/systemd/user/quantime-ingest-massive.timer
systemctl --user daemon-reload
```

已落盘的 batch、raw 副本、报告不受影响（只 insert）。

## 6. REST 参考数据（不进 timer）

ticker 全表 / 拆股 / 分红 / ticker 事件是**一次性全量 + 手动增量**，不配 timer：

```sh
cd ~/quantime && op run --env-file=docs/ops/massive.env.tpl -- \
  uv run --package quantime-data --extra ingest quantime-ingest-us \
    --root ~/quantime reference --corp-start 2021-09-23 --corp-end 2026-10-17
```

每次运行写新 batch（`source='massive_rest'`），不覆盖旧 batch。
