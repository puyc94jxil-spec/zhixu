# A 期接手说明

这份说明给独立 TEST 接手用。它记录的是 DEV 自测当时的代码和命令。DEV 自测不是测试签收。用例计划、协议夹具和下面的通过条数都不能写成正式执行成功。

范围基线 `BL-ZHIXU-REQ-001` 与设计基线 `BL-ZHIXU-DES-001` 只说明批准了什么。它们不是代码基线、测试基线或发布基线。测试计划 `DOC-ZHIXU-TEST-PLAN-001` 与用例目录 `DOC-ZHIXU-TEST-CASES-001` 均为 `v0.1-draft`，未审定、未执行（目录共 51 条：A 17、B 16、C 18）。A 期不提前完成 B/C。

## 1. 代码位置

- 分支：`cursor/zhixu-p0-phase-a-71ab`
- 源锚点（需求与设计来源，不是本实现）：`ac62ee813425b2a8494324ae9cb28585e1303e29`
- 实现提交：`54f84fce2fef4dd3bf75eab893e16b4437734b54`
- 接手版本：分支 HEAD。若本说明在实现提交之后又有补记，以 `git rev-parse HEAD` 的完整 SHA 为准，并在 `git log` 里确认上面的实现提交仍是祖先。
- 服务版本字符串：`0.1.0-phase-a`

根目录原型文件相对源锚点没有改动。生产界面在 `web/`。原型快照在 `prototype/`，服务只在 `/prototype-snapshot/` 下提供对照页面。

## 2. 依赖、版本与启动

DEV 自测环境：

| 组件 | 版本 |
| --- | --- |
| Python | 3.12.3 |
| SQLite | 3.45.1（含 FTS5、WAL） |
| FastAPI | 0.121.0 |
| Uvicorn | 0.38.0 |
| argon2-cffi | 25.1.0（Argon2id，time_cost=2，memory_cost=65536，parallelism=1） |
| httpx | 0.28.1 |
| python-multipart | 0.0.20 |
| jieba | 0.42.1 |
| pytest | 9.0.1 |
| ruff | 0.14.5 |
| Node | v22.23.4（只跑前端规则测试，没有打包步骤） |
| bubblewrap | 0.9.0，另需 `newuidmap` |

本环境没有 `python3-venv` / `ensurepip`。自测把依赖装到 `/tmp/zhixu-py`，并用 `PYTHONPATH=/tmp/zhixu-py:/workspace/server`。接手机器应使用自己的虚拟环境安装 `server/requirements.txt`，不要依赖 `/tmp/zhixu-py`。

启动（默认不调用模型）：

```bash
cd server
export PYTHONPATH="$PWD"
export ZHIXU_DATA_DIR="$PWD/data"
export ZHIXU_UPSTREAM_MODE=unconfigured
python3 -m zhixu_server.main
```

进程监听 `ZHIXU_HOST`（默认 `127.0.0.1`）和 `ZHIXU_PORT`（默认 `8000`）。首页是 `http://127.0.0.1:8000/`。

DEV 自测命令（在 `server/` 下，`PYTHONPATH` 指向依赖和 `server`）：

```bash
python3 -m compileall -q zhixu_server tests
python3 -m ruff check zhixu_server tests
node --test ../web/input_rules.test.js
python3 -m pytest -q --tb=line
```

本次 DEV 结果：ruff 通过；Node 3 项通过；pytest 16 项通过。这只覆盖 A 期自测脚本，不是 51 条正式用例的执行。

## 3. 配置：哪些可以写，密钥怎么注入

非秘密项可以用环境变量设置：

| 变量 | 作用 | 未设置时 |
| --- | --- | --- |
| `ZHIXU_DATA_DIR` | 数据库、对象和日志目录 | `./data` |
| `ZHIXU_ALLOWED_ORIGINS` | 允许的浏览器来源，逗号分隔 | `http://127.0.0.1:8000,http://localhost:8000` |
| `ZHIXU_COOKIE_SECURE` | 生产置 `1` 后会话 Cookie 带 Secure | 关闭 |
| `ZHIXU_SESSION_TTL_HOURS` | 会话小时数 | 12 |
| `ZHIXU_UPSTREAM_MODE` | `live`、`fixture` 或 `unconfigured` | 有地址和模型名则视为 `live`，否则 `unconfigured` |
| `ZHIXU_UPSTREAM_CONNECT_TIMEOUT` | 连接超时秒 | 15 |
| `ZHIXU_UPSTREAM_FIRST_BYTE_TIMEOUT` | 首字节超时秒 | 15 |
| `ZHIXU_UPSTREAM_TOTAL_TIMEOUT` | 整次超时秒 | 120 |
| `ZHIXU_UPSTREAM_RETRY_DELAYS` | 两次重试间隔秒 | `0.5,1.5` |
| `ZHIXU_FIXTURE_HOLD` | 仅 `fixture` 模式在首个增量后暂停约 2 秒 | 关闭；`live` 下忽略 |
| `ZHIXU_HOST` / `ZHIXU_PORT` | 监听地址和端口 | `127.0.0.1` / `8000` |
| `ZHIXU_FIXTURE_USER1_NAME` / `ZHIXU_FIXTURE_USER2_NAME` | 夹具账号名 | `fixture_user_a` / `fixture_user_b` |

秘密只从环境注入，命令行和文档都不传明文：

- `ZHIXU_MODEL_BASE_URL`
- `ZHIXU_MODEL_NAME`
- `ZHIXU_MODEL_API_KEY`
- `ZHIXU_FIXTURE_USER1_PASSWORD`
- `ZHIXU_FIXTURE_USER2_PASSWORD`

`live` 却缺少地址或模型名时，会降为 `unconfigured` 并拒绝生成。代码、前端和测试树不写死批准附件中的内网地址。该地址只存在于冻结的批准快照里。

## 4. 数据库、私有对象与解析隔离

- 数据库文件：`$ZHIXU_DATA_DIR/zhixu.db`，启动时打开 WAL。检索使用单独的 `fts_lex` 字段，原文、页、段和偏移另存。入库和查询都用 jieba（`cut_all=False`，`HMM=True`）。查询用有意义词的 OR，避免虚词把命中清掉。
- 对象目录：`$ZHIXU_DATA_DIR/objects/`。检索条件同时限制拥有者、当前会话已启用、文件版本和未删除。相同内容哈希只在同一用户内复用，不会因此把文件授给别人。
- 解析：独立的 bubblewrap 子进程，不是工作线程。参数包括 `--unshare-user --unshare-net --unshare-pid --unshare-ipc --unshare-uts --die-with-parent --new-session --cap-drop ALL --uid 65534 --gid 65534`，只读绑定运行所需系统目录。子进程限制：地址空间 256MB、CPU 60 秒、单文件 32MB、文件描述符 64、进程数 32。墙钟 120 秒。输出超过原文件 10 倍则失败。
- 启动探针只访问文档用测试地址 `203.0.113.1:9`，确认非 root、无网络、读不到哨兵文件。探针失败或没有 `bwrap` 时，解析返回 `isolation_unavailable`，不产生分块。探针通过只说明这台机器的隔离原语可用，不是 C 期安全验收。
- 本 DEV 启动日志中的 `isolation_probe` 为 `ready=true`、`reason=ok`、`uid=65534`。

## 5. 真实模型与夹具

真实 Qwen 连通：**未验证**。本环境没有访问批准附件中的内网服务，没有隧道，也没有扫描。`GET /api/health` 的 `model_configured` 只表示环境变量是否齐，不表示连通。

协议夹具与生产隔离的方式：

1. 生产启动保持 `ZHIXU_UPSTREAM_MODE=unconfigured` 或显式 `live`。不要把夹具地址配进生产。
2. 自测夹具是 `server/tests/conftest.py` 里的 `FixtureUpstream`。它只在 pytest 进程中监听 `127.0.0.1` 的临时端口，测试再把 `ZHIXU_UPSTREAM_MODE=fixture` 和 `ZHIXU_MODEL_BASE_URL` 指到这个临时地址，模型名使用 `fixture-model`。
3. `fixture` 模式仍然按配置地址发 HTTP。若把真实模型地址填进去，那就是真实调用，不再是夹具。夹具成功不能写成真实模型、真实引用或检索质量通过。
4. `ZHIXU_FIXTURE_HOLD=1` 只在 `fixture` 模式生效，用来制造「已经写出第一段、上游还停着」的窗口。

## 6. 双账号与中文夹具

不要把密码写进命令、日志或本说明。

双账号：

```bash
cd server
export PYTHONPATH="$PWD"
export ZHIXU_DATA_DIR=/path/to/zhixu-data
export ZHIXU_FIXTURE_USER1_PASSWORD='由环境注入，至少 10 位'
export ZHIXU_FIXTURE_USER2_PASSWORD='由环境注入，至少 10 位'
python3 -m zhixu_server.tools fixture-users
```

命令只打印用户 ID。密码短于 10 位时拒绝执行，也不生成密码。已存在的同名账号不会改密码。也可以用界面或 `POST /api/auth/register` 各注册一次。自测脚本内部另有本地口令常量，只用于 pytest，不要拿到环境外复用。

中文夹具文件（仓库内明文样例，不含口令）：

- `server/fixtures/zh_has_answer.txt`：含预算、地点和名额，用于「能定位引用」。
- `server/fixtures/zh_no_answer.md`：不含预算，用于「应撤回无依据结论」。
- `server/fixtures/zh_amount.txt`：另一条金额，用于区分材料。

异常文件由测试临时生成：空文件、含空字节的二进制、超限体积、`.pdf`。PDF/DOCX 在 A 期返回 415，这是预期残留，不是解析成功。

## 7. 重置、在线备份与恢复

重置会删除整个数据目录。目录里必须已有 `ZHIXU_DATA_MARKER`，否则拒绝，避免误删别的文件夹。

```bash
python3 -m zhixu_server.tools reset --yes
python3 -m zhixu_server.tools backup --dest /path/to/backup-dir
python3 -m zhixu_server.tools restore --src /path/to/backup-dir --data-dir /path/to/new-data
```

备份使用 SQLite 在线 `backup()`，不直接复制正在写的 WAL 库文件，并复制未删除对象，写出 `manifest.json`。恢复写到带标记的新目录，没有用户自助恢复接口。

DEV 自测 `test_backup_and_restore_roundtrip` 做过一次往返。C 期恢复验收未做。备份保留 30 天后自动清除：**尚未实现**。

## 8. 删除、取消与日志入口

操作点（都要带登录 Cookie、`Origin` 和 `X-CSRF-Token`）：

1. 取消竞态：`ZHIXU_FIXTURE_HOLD=1` 时发送消息，等 `request_events` 出现第一条 `delta`，再 `POST /api/requests/{request_id}/cancel`。重复取消仍返回成功。最终状态是 `stopped`，已写出的半句保留，后续增量不再写入，也不会标成 `completed`。
2. 删除竞态：文件已 `ready` 且生成已写出第一条 `delta` 时，`DELETE /api/files/{file_id}?confirm=true`。在途回答应变成 `withdrawn`，正文不再含被删材料中的数字或原句。事件流里也不应出现这些原文。
3. 删除后的多轮：再次提问时，旧助手消息在送往模型前换成占位句「[依据文件已删除或撤销，该轮材料内容不再纳入上下文]」。用户自己输入过的问题原文可以保留。
4. 幂等：创建会话和发送消息可带 `Idempotency-Key`。同一键返回同一个对象。生成中再次发送返回 409 `generation_in_progress`。
5. 重连续传：`GET /api/requests/{request_id}/events`，用请求头 `Last-Event-ID` 或查询参数 `last_event_id`。已结束的请求不会再次调用上游。

不泄密日志：

- 标准错误输出，以及 `$ZHIXU_DATA_DIR/logs/zhixu.log`。
- 每行是 JSON。关心的事件名包括 `boot`、`isolation_probe`、`isolation_unavailable`、`login`、`login_failed`、`login_rate_limited`、`file_stored`、`parse_ready`、`parse_failed`、`file_deleted_online`、`generation_completed`、`generation_withdrawn`、`generation_stopped`、`generation_failed`、`cancel`、`unhandled`。
- 字段名属于密码、密钥、Cookie、正文、引用、提示词的会被丢掉。`unhandled` 只记路径和 `error_code=internal`，不记异常原文。

## 9. A 已实现并经 DEV 自测

下列是自测脚本实际走到的行为，不是正式用例通过。

- 未登录拒绝；注册登录后服务端会话；换账号看不到对方资源（跨用户返回 403）。
- 登录后写操作同时检查 Origin 和 CSRF。登录失败限流。
- TXT 上传、隔离解析、预览、同用户哈希复用；另一用户持有相同内容不能复用。
- 空文件、PDF、超限文件被拒绝。隔离不可用时解析失败且没有分块。
- 协议夹具下：引用核验通过、坏引用整段撤回为「资料中未找到」、删除后的上下文使用占位句。
- 取消保留半句且可重复取消。429 映射为失败，重试产生新的助手消息而不重复用户消息。
- 连不上上游或未配置模型时，结果不是完成。
- 幂等键与删除进行中的文件。
- 日志不含口令和样例原句。
- 在线备份与恢复到新目录的一次往返。
- 前端规则：空白不可发送，Enter 发送，Shift+Enter 与输入法组合不发送；增量不是已核验引用，事件不串到别的会话。

## 10. B/C 剩余

仍属后续分期，A 期接口故意不做或只做最小行为：

- PDF、DOCX 与对应解析。
- 反馈入口。`POST /api/messages/{id}/feedback` 不存在，返回 404。
- 账号注销。`DELETE /api/auth/me` 没有该路由，现返回 405。这表示 A 期未提供，不是注销成功。
- 完整的标题搜索与编辑体验。列表可以带很短的标题过滤，可以改标题，但不等于 B 期搜索完成。
- Q05 回答 HTML 消毒。当前按文本放入页面。
- Q06 超长上下文的正式摘要。超过约 8 万字时返回内部错误并保留附件，这不是 B 期完成。
- 30 天备份清除、用户自助恢复、账号删除后的数据处置。
- C 期：隔离有效性、删除/取消竞态、恢复、真实引用是否语义支持、性能与容量观察。DEV 探针和协议夹具都不能代替这些验收。

## 11. 真实模型仍待验证

以下全部保持未验证，不能用夹具填通过：

- 到指定 Qwen 服务的真实连通、鉴权、流式和超时。
- 真实回答是否被材料语义支持。当前核验只做摘录是否出现在分块中，以及声明里的数字是否出现在分块中。
- 真实上游上的取消是否确实中止对端请求。
- 真实负载下的删除/取消竞态和隔离强度。
