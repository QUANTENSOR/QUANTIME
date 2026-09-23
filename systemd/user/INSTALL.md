# quantime 摄取 timer 安装手册（QNT-45 第 5 项）

本目录只交付**文件**。QNT-45 的任何 agent 都不得在主机上执行下面任何一条命令
（出差期规则：不改主机、不安装 unit、不启动 timer）。下列步骤**由 owner 回来后逐项执行**。

命令里的 `<SOURCE>` 当前只有一个取值：`binance_vision`。实例名就是 `--source` 的值。

**换源不是「adapter 实现三个方法、换个实例名」就完事。** CLI 今天的组装写死给公开源：
`--source` 在 `BUILTIN_ADAPTERS`（`packages/data/quantime_data/adapter.py`）里查 adapter；
网络出口一律 `PublicTransport(_http_opener())`，`transport.get` 作为 `fetch` 传给通用层；
spec 由 `_specs_for` 按 `universe.yaml` 的 spot / perp 腿展开，请求日 `as_of` 默认取运行当天。
QNT-47（Massive）/ QNT-48（Tushare Pro）接入时，除了 adapter 本身，还要在 CLI 里登记该源、
按源组装它的出口（Tushare 是需凭据的 `CredentialedTransport`，届时 unit 要启用文件末尾的
`op run` 占位）、必要时扩展清单与 spec 展开。这些落地后，timer 才是「换实例名即可」。

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

unit 只传 `--end 昨日` + `--since-last`，**不传 `--start`**：起点只来自已提交数据的水位线
（水位线次日）。首跑没有水位线时只取昨日一天——更早的历史用第 6 节的手动命令回填，
不要指望 timer 去补。关机几天后 timer 只补跑一次（`Persistent=true` 的语义），那一次从水位线
取到昨日，停机期间的每一天都会回来。

journal 里若出现 `# note --start ... 被忽略`：手动运行给了 `--start`，但已有水位线，按水位线续取。

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

# 当天全部报告的汇总（汇总 unit 跑的就是这条；按 JSON 字段读，非 complete 退出码 1）
cd ~/quantime && uv run --no-sync --offline --package quantime-data \
  quantime-ingest --root ~/quantime report-summary
journalctl --user -u quantime-ingest-report.service -n 50 --no-pager

# 运行记录（空增量的那天没有 batch，但有这一条）
ls ~/quantime/data/runs/
```

## 6. 报告里出现缺口时的补采

报告里每条序列有 `status` 与 `coverage`，整份报告的 `coverage` 是它们的汇总：

| 序列 `status` / `coverage` | 含义 | 要不要补采 |
|---|---|---|
| `ok` / `complete` | 取全了 | 不用 |
| `ok` / `partial` | 取到了一部分，`missing_archives` 列出 404 的归档 | 按报告补采 → `kind='rerun'` + `rerun_of`（接原 batch） |
| `failed` / `failed` | 整条没写进湖（`batch_id=null`），`error_class` / `attempts` 说明怎么失败的 | 按报告补采 → `kind='ingest'`，batch 清单记 `from_report=<报告路径>` |
| `pending` / `pending` | 上游按发布节奏还没发布（如 funding 月档在次月第一个周一前），`pending_upstream` 列出区间 | **不用**——不算缺失、不进覆盖率分母，下一次 `--since-last` 自然取回 |

任何一条 `failed`，整份报告与该源的 `coverage` 都是 `failed`，不会是 `complete`。
按报告补采写的都是**新批次**，被补的批次一个字节都不动：

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

没有水位线时手动回填更早的历史（`--start` 只在没有水位线时生效）：

```sh
cd ~/quantime && uv run --package quantime-data --extra ingest quantime-ingest \
  --root ~/quantime --source binance_vision daily --start 2026-08-01 --end 2026-08-31
```

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
