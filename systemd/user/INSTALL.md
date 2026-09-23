# quantime 摄取 timer 安装手册（QNT-45 第 5 项）

本目录只交付**文件**。QNT-45 的任何 agent 都不得在主机上执行下面任何一条命令
（出差期规则：不改主机、不安装 unit、不启动 timer）。下列步骤**由 owner 回来后逐项执行**。

命令里的 `<SOURCE>` 当前只有一个取值：`binance_vision`。QNT-47（Massive 美股 + 期权）与
QNT-48（Tushare Pro A 股）接入后，同一套模板换实例名即可，unit 文件不用改。

## 0. 前置检查（只读，不改任何东西）

```sh
# 常驻检出在位、代码是要装的那个 commit
git -C ~/quantime log --oneline -1

# uv 与 Python 3.14 可用
uv --version
uv run --package quantime-data --python 3.14 python -V

# 摄取 CLI 能跑（dry-run，只打印 URL，不出网写盘）
cd ~/quantime && uv run --package quantime-data --extra ingest quantime-ingest \
  --source binance_vision plan --start 2026-09-01 --end 2026-09-01 --symbol BTCUSDT --datatype kline
```

`WorkingDirectory=%h/quantime` 与 `--root %h/quantime` 是 unit 里写死的路径。
若常驻检出不在 `~/quantime`，**先改 unit 再装**，不要装完再改。

## 1. 安装 unit 文件

```sh
mkdir -p ~/.config/systemd/user
cp ~/quantime/systemd/user/quantime-ingest@.service        ~/.config/systemd/user/
cp ~/quantime/systemd/user/quantime-ingest@.timer          ~/.config/systemd/user/
cp ~/quantime/systemd/user/quantime-ingest-report.service  ~/.config/systemd/user/
cp ~/quantime/systemd/user/quantime-ingest-report.timer    ~/.config/systemd/user/
systemctl --user daemon-reload
```

装之前自查一遍（无 root，对文件运行）：

```sh
cd ~/quantime/systemd/user && systemd-analyze verify --user \
  ./quantime-ingest@.service ./quantime-ingest@.timer \
  ./quantime-ingest-report.service ./quantime-ingest-report.timer
```

无输出且退出码 0 = 通过。

## 2. 允许用户服务在未登录时运行

user timer 默认只在有登录会话时存在。没有这一步，注销之后 timer 就没了，
而**它恰好是在你不在的时候该跑的那个东西**：

```sh
loginctl enable-linger "$USER"
loginctl show-user "$USER" --property=Linger   # 期望 Linger=yes
```

## 3. 先手工跑一次，再交给 timer

不要直接 enable 就走人——先确认这台机器上真能跑完一次：

```sh
systemctl --user start quantime-ingest@binance_vision.service
systemctl --user status quantime-ingest@binance_vision.service --no-pager
journalctl --user -u quantime-ingest@binance_vision.service -n 100 --no-pager
```

期望：`Main PID: ... (code=exited, status=0/SUCCESS)`，且 journal 里最后一行 JSON 的
`"outcome": "ok"`、`"coverage": "complete"`。非零退出码 = 本次有失败，先看报告再往下走。

当天的报告：

```sh
ls ~/quantime/data/reports/$(date -u +%Y-%m-%d)/
cat ~/quantime/data/reports/$(date -u +%Y-%m-%d)/*.md
```

## 4. 启用 timer

```sh
systemctl --user enable --now quantime-ingest@binance_vision.timer
systemctl --user enable --now quantime-ingest-report.timer
systemctl --user list-timers --all --no-pager | grep quantime
```

`NEXT` 列应显示次日 02:30 UTC 之后（含最多 20 分钟随机延迟）；报告汇总在 04:30 UTC。

## 5. 日常查看

```sh
# 最近一次运行
journalctl --user -u quantime-ingest@binance_vision.service -n 200 --no-pager

# 只看今天
journalctl --user -u quantime-ingest@binance_vision.service --since today --no-pager

# 跟着看
journalctl --user -u quantime-ingest@binance_vision.service -f

# 每日报告（Markdown 给人看，JSON 给补采读）
cat ~/quantime/data/reports/$(date -u +%Y-%m-%d)/*.md

# 运行记录（空增量的那天没有 batch，但有这一条）
ls ~/quantime/data/runs/
```

## 6. 报告里出现缺口时的补采

报告 `coverage: partial` 说明请求区间内有整档没取到。按那份报告补采，
写的是 `kind='rerun'` 的**新批次**，被补的批次一个字节都不动：

```sh
cd ~/quantime
REPORT=~/quantime/data/reports/2026-09-23/<run_id>.json

# 先看计划，不取任何字节
uv run --package quantime-data --extra ingest quantime-ingest \
  --root ~/quantime --source binance_vision backfill --from-report "$REPORT" --dry-run

# 确认后执行
uv run --package quantime-data --extra ingest quantime-ingest \
  --root ~/quantime --source binance_vision backfill --from-report "$REPORT"
```

补完会产出一份新报告，那几条序列应当变成 `coverage: complete`。

若核对后确认**上游本来就没有**那个归档（不是我们漏采），把它加进
`packages/data/quantime_data/upstream_missing.yaml` 并**走 PR**——带上核对依据与日期。
加进去之后补采会跳过它，报告不再因它停在 partial。

## 7. 停用 / 卸载

```sh
# 只停不卸
systemctl --user disable --now quantime-ingest@binance_vision.timer
systemctl --user disable --now quantime-ingest-report.timer

# 彻底卸载
systemctl --user stop quantime-ingest@binance_vision.timer quantime-ingest-report.timer
systemctl --user disable quantime-ingest@binance_vision.timer quantime-ingest-report.timer
rm -f ~/.config/systemd/user/quantime-ingest@.service \
      ~/.config/systemd/user/quantime-ingest@.timer \
      ~/.config/systemd/user/quantime-ingest-report.service \
      ~/.config/systemd/user/quantime-ingest-report.timer
systemctl --user daemon-reload
systemctl --user reset-failed

# linger 若不再需要（会影响该用户的所有 user service，确认没别的在用再关）
loginctl disable-linger "$USER"
```

已经落盘的数据、报告、运行记录不会被卸载动到——它们只 insert，卸载 timer 不删任何数据。

## 凭据

**这四个 unit 不含任何凭据，也不需要任何凭据。** 当前数据源是公开只读归档
（无 key、无签名）。将来接入付费源时，凭据一律经 1Password 在 `ExecStartPre` / `op run`
注入子进程环境（vault `quant-dev`，读取时 `.strip()`）——写法见
`quantime-ingest@.service` 末尾的注释占位。禁止 `Environment=` 明文、禁止
`EnvironmentFile=` 指向含明文 key 的文件、禁止把 key 写进 unit 或任何落盘文件
（AGENTS.md §3 / ADR-0001）。
