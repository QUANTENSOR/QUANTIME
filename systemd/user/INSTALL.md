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

## 部署约定（R8，owner 2026-09-23 05:37 裁决）

| 项 | 取值 / 做法 |
|---|---|
| 常驻检出 | `/home/workspace/quantime`（unit 的 `WorkingDirectory=`；**只读**，`data/` 是唯一例外） |
| 数据根 | `/home/workspace/quantime/data`（软链接 → 本机另一处目录）。两个 service 都用 `Environment=QUANTIME_DATA_ROOT=/home/workspace/quantime/data` 给出，CLI 的 `--root` 缺省取它；手动运行时写 `--root /home/workspace/quantime/data`，效果相同。`--root` 写数据目录本身或它的父目录都行，不会写出 `data/data/` |
| 运行前拉代码 | `ExecStartPre=+/usr/bin/git -C /home/workspace/quantime pull --ff-only`。`+` = 只有这一条不受沙箱约束（拉代码要写 `.git`、要出网；摄取进程本身仍只能写数据根） |
| 拉代码失败 | ExecStart **不启动**（不摄取），unit 结果 failed（非零）。**选 `ExecStopPost` 记录**（不用 `OnFailure=`：那要另写一个 unit，且分不清 pull 失败与摄取失败）：结果非 `success` 且 `$EXIT_CODE` 为空（主进程没跑过）→ `quantime-ingest record-abort --reason pull_failed`，写一份运行记录（`abort_reason: pull_failed`）+ 一份 `coverage: failed` 的报告 |
| 只读沙箱 | `ProtectSystem=strict`、`ProtectHome=read-only`、`ReadOnlyPaths=/home/workspace/quantime`、`ReadWritePaths=/home/workspace/quantime/data`（**只**这一项）。`uv run --no-sync --offline` 不写 `.venv`；`PYTHONDONTWRITEBYTECODE=1` 不写 `__pycache__`；uv 缓存在私有 `/tmp` |
| 磁盘守卫 | **全部写入口**（`daily` / `backfill` / `ingest` / `ingest --rerun-of`）共用同一处守卫：它在开 batch 的共用边界（`ingest_one` 开头，取任何字节之前）量数据根所在文件系统的剩余空间，低于 `--min-free-gb`（三个写子命令同一参数；unit 里写的 5，缺省也是 5，可由 `QUANTIME_MIN_FREE_GB` 改缺省；只有显式 `0` 关闭）→ 不发请求、不开新 batch，运行记录 `abort_reason: disk_low`（备注写明剩余 / 阈值），报告 `coverage: failed` 并写明剩余 / 阈值，退出码 1。`daily` / `backfill` 的报告按序列列出被拦下的缺档；`ingest` 平时不写运行记录与报告，被拦下时补写一份运行记录 + 一份 `mode: aborted` 的报告（无序列明细，与 `record-abort --reason disk_low` 同形），之后的序列不再尝试 |
| 首跑遇到 pending | funding 月档在次月第一个周一才发布。没有水位线的首跑整段 pending 时，请求起点记进运行记录 `pending_since`；之后的 `--since-last` 从 `min(水位线次日, 未消化的 pending 起点)` 取，月档发布后真正落成 batch。**不需要手工回填或任何人工步骤来接住它** |

## 0. 前置检查（只读，不改任何东西）

```sh
# 常驻检出在位、代码是要装的那个 commit；能快进拉取（unit 每次运行前都会做这一步）
git -C /home/workspace/quantime log --oneline -1
git -C /home/workspace/quantime status --short        # 期望为空（/data 已在 .git/info/exclude）
git -C /home/workspace/quantime pull --ff-only --dry-run 2>&1 || echo "注意：不能快进"

# 数据根在位、剩余空间 > 5 GB
ls -ld /home/workspace/quantime/data
df -h "$(readlink -f /home/workspace/quantime/data)"

# uv 与 Python 3.14 可用
uv --version
```

## 0.5 准备运行环境（owner 回来执行；写常驻检出里的 `.venv`，所以 unit 不做）

unit 用 `uv run --no-sync --offline`：不解析依赖、不写 `.venv`、不出网拉包——常驻检出里除
`data/` 外一个字节都不写。所以环境要事先装好，**依赖变更（`uv.lock` 变了）之后也要重跑这一步**：

```sh
cd /home/workspace/quantime && uv sync --package quantime-data --extra ingest

# 摄取 CLI 能跑（dry-run，只打印 URL，不出网写盘）
cd /home/workspace/quantime && uv run --no-sync --offline --package quantime-data quantime-ingest \
  --source binance_vision plan --start 2026-09-01 --end 2026-09-01 --symbol BTCUSDT --datatype kline
```

`WorkingDirectory=/home/workspace/quantime` 与 `QUANTIME_DATA_ROOT=/home/workspace/quantime/data`
是 unit 里写死的路径。若布局不同，**先改 unit 再装**，不要装完再改。

## 1. 安装 unit 文件

```sh
mkdir -p ~/.config/systemd/user
cp /home/workspace/quantime/systemd/user/quantime-ingest@.service        ~/.config/systemd/user/
cp /home/workspace/quantime/systemd/user/quantime-ingest@.timer          ~/.config/systemd/user/
cp /home/workspace/quantime/systemd/user/quantime-ingest-report.service  ~/.config/systemd/user/
cp /home/workspace/quantime/systemd/user/quantime-ingest-report.timer    ~/.config/systemd/user/
systemctl --user daemon-reload
```

装之前自查一遍（无 root，对文件运行）：

```sh
cd /home/workspace/quantime/systemd/user && systemd-analyze verify --user \
  ./quantime-ingest@.service ./quantime-ingest@.timer \
  ./quantime-ingest-report.service ./quantime-ingest-report.timer
```

无输出且退出码 0 = 通过（实例化后的 `quantime-ingest@binance_vision.*` 同样通过，
`tests/test_systemd_units.py` 里各有一条测试）。

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
`"outcome": "ok"`、`"coverage"` 为 `"complete"`——或在 funding 月档尚未发布的日子里为
`"pending"`（见下）。非零退出码 = 本次有失败，先看报告再往下走。

unit 只传 `--end 昨日` + `--since-last`，**不传 `--start`**：起点是
`min(水位线次日, 未消化的 pending 起点)`。首跑没有水位线时只取昨日一天——更早的历史用
第 6 节的手动命令回填，不要指望 timer 去补。首跑那天 funding 月档还没发布、整段 pending
也没关系：起点已记进运行记录 `pending_since`，月档发布后的那次运行会从它取起。关机几天后
timer 只补跑一次（`Persistent=true` 的语义），那一次从上面的起点取到昨日，停机期间的每一天
都会回来。

首跑当天 funding 为 `pending` 时，整份报告的 `coverage` 是 `pending`（不是 `complete`）——
这是预期的；月档发布、那段被真正取回之前它一直是 `pending`。

若 journal 里 ExecStopPost 记了一笔 `pull_failed`：说明 `git pull --ff-only` 没成功（常驻检出
有本地改动 / 分叉 / 没网），本次**没有摄取**。先看 `git -C /home/workspace/quantime status`，
处理好之后下一次 timer 从断点续取，不必补跑。

journal 里若出现 `# note --start ... 被忽略`：手动运行给了 `--start`，但已有水位线，按水位线续取。

当天的报告：

```sh
ls /home/workspace/quantime/data/reports/$(date -u +%Y-%m-%d)/
cat /home/workspace/quantime/data/reports/$(date -u +%Y-%m-%d)/*.md
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
cat /home/workspace/quantime/data/reports/$(date -u +%Y-%m-%d)/*.md

# 当天全部报告的汇总（汇总 unit 跑的就是这条；按 JSON 字段读，非 complete 退出码 1；
# 被拦下的运行会带 abort_reason=pull_failed / disk_low）
cd /home/workspace/quantime && uv run --no-sync --offline --package quantime-data \
  quantime-ingest --root /home/workspace/quantime/data report-summary
journalctl --user -u quantime-ingest-report.service -n 50 --no-pager

# 运行记录（空增量的那天没有 batch，但有这一条）
ls /home/workspace/quantime/data/runs/
```

## 6. 报告里出现缺口时的补采

报告里每条序列有 `status` 与 `coverage`，整份报告的 `coverage` 是它们的汇总：

| 序列 `status` / `coverage` | 含义 | 要不要补采 |
|---|---|---|
| `ok` / `complete` | 取全了 | 不用 |
| `ok` / `partial` | 取到了一部分，`missing_archives` 列出 404 的归档 | 按报告补采 → `kind='rerun'` + `rerun_of`（接原 batch） |
| `failed` / `failed` | 整条没写进湖（`batch_id=null`），`error_class` / `attempts` 说明怎么失败的 | 按报告补采 → `kind='ingest'`，batch 清单记 `from_report=<报告路径>` |
| `pending` / `pending` | 上游按发布节奏还没发布（如 funding 月档在次月第一个周一前），`pending_upstream` 列出区间 | **不用**——不算缺失、不进覆盖率分母；起点记在运行记录 `pending_since`，月档发布后的 `--since-last` 从那里取回 |
| `failed`，`error_class: disk_low` | 磁盘守卫拦下，没开 batch | 腾出空间即可：下一次 `--since-last` 从原起点续取；也可按报告补采 |

整份报告 / 分源 `coverage` 的汇总顺序：运行被拦下（`abort_reason` = `pull_failed` / `disk_low`）
或任一条 `failed` → `failed`；任一条 `partial` → `partial`；还有未消化的 pending → `pending`；
都取全了 → `complete`。有 `failed` 或未取回的 pending 时都不会是 `complete`。
按报告补采写的都是**新批次**，被补的批次一个字节都不动：

```sh
cd /home/workspace/quantime
REPORT=/home/workspace/quantime/data/reports/2026-09-23/<run_id>.json

# 先看计划，不取任何字节
uv run --no-sync --offline --package quantime-data quantime-ingest \
  --root /home/workspace/quantime/data --source binance_vision backfill --from-report "$REPORT" --dry-run

# 确认后执行（磁盘守卫同一处生效：--min-free-gb，默认 5）
uv run --no-sync --package quantime-data quantime-ingest \
  --root /home/workspace/quantime/data --source binance_vision backfill --from-report "$REPORT"
```

补完会产出一份新报告，那几条序列应当变成 `coverage: complete`。

没有水位线时手动回填更早的历史（`--start` 只在没有水位线、也没有未消化的 pending 起点时
生效）。这是**历史回填**，不是让 timer 能跑起来的前置步骤——timer 首跑遇到 pending 不需要它：

```sh
cd /home/workspace/quantime && uv run --no-sync --package quantime-data quantime-ingest \
  --root /home/workspace/quantime/data --source binance_vision daily --start 2026-08-01 --end 2026-08-31
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

## 需要 root 的步骤（owner 回来执行）

上面第 1–7 节全是 `systemctl --user` / `loginctl`（本用户），不需要 root。已知需要 root 或
需要 owner 本人决定的只有下面几项；出差期间一律不做：

1. `loginctl enable-linger witnessj`——若当前 polkit 策略不允许本用户对自己开 linger，要
   `sudo loginctl enable-linger witnessj`（第 2 节）。
2. 若要让 user unit 的 `ProtectSystem=` / `ProtectHome=` 等沙箱**真正生效**：它们在 user
   manager 下依赖非特权 user namespace；宿主（LXC）若禁用了 unprivileged userns，这些指令
   会被忽略或导致启动失败。核查 `sysctl kernel.unprivileged_userns_clone`（Debian）/
   `user.max_user_namespaces`，需要改的话是宿主层的 root 操作——先在卡里逐项列出再动手。
3. 数据根的属主 / 权限（当前 0700，软链接目标在本用户家目录下）：若将来换盘或改属主，是
   root 操作，同样先列出再动手。

## 凭据

**这四个 unit 不含任何凭据，也不需要任何凭据。** 当前数据源是公开只读归档
（无 key、无签名）。将来接入付费源时，凭据一律经 1Password 在 `ExecStartPre` / `op run`
注入子进程环境（vault `quant-dev`，读取时 `.strip()`）——写法见
`quantime-ingest@.service` 末尾的注释占位。禁止 `Environment=` 明文、禁止
`EnvironmentFile=` 指向含明文 key 的文件、禁止把 key 写进 unit 或任何落盘文件
（AGENTS.md §3 / ADR-0001）。
