# A 期实现差异记录

这些差异是相对 `DOC-ZHIXU-IMPL-CONTRACT-001` v0.1-draft 和批准附件分期表记下的。契约是获批方案里的草稿细化，不是新的人类批准。安全上更严的做法予以保留，并在这里写明，不把示例原文无差别套进来。

| 项 | 实现 | 原因 |
| --- | --- | --- |
| 登录后的 CSRF | 同时要求允许的 Origin 和 CSRF 令牌 | 批准附件要求两者都有。契约示例写成二者择一。采用更严的同时要求。 |
| CSRF 放在哪里 | 独立 Cookie `zhixu_csrf`，前端再放进 `X-CSRF-Token` | 不把令牌放进 `/auth/me` 正文。会话 Cookie `zhixu_session` 为 HttpOnly。 |
| 会话详情 | 增加 `GET /api/conversations/{id}` | 前端需要一次取回该会话的消息。 |
| 解析重试与取消 | 增加 `POST /api/files/{id}/retry` 和 `POST /api/files/{id}/cancel` | 属于已批准 A 期的可恢复解析，契约路由表未逐条列出。 |
| 错误码 | 另有 `model_unconfigured`、`login_rate_limited` | 未配置模型和登录限流需要可区分的失败，不能标成完成。 |
| 检索词连接 | 有意义的词用 OR | 全部 AND 时，自然问句里的虚词会导致零命中。 |
| 标题 | 列表支持很短的 `q`，可以 `PATCH` 标题 | 与契约列表参数有重叠。完整搜索和编辑体验仍属 B 期，不记成 B 期完成。 |
| 状态文案 | 接口使用英文状态码，界面显示中文 | 机器判断用稳定码，给人看的标签另做。 |
| 已完成请求的取消 | 不把已完成改写成停止 | 避免事后改写终态。 |
| 删除后的历史展示 | 在线读取会话时，来源已删除的助手正文也换成占位句 | 比「只在送模型时遮盖」更严，避免界面继续展示已删材料。 |
| 账号注销 | `DELETE /api/auth/me` 返回 405 | 路由不存在。A 期不实现 B 期注销。 |
| 30 天清除 | 未实现 | 在线备份命令已有，期限清除没有。 |
| 真实模型 | 未调用 | 云端不假设内网可达。协议夹具只在测试进程的本地临时端口。 |

FTS 删除使用普通 `DELETE FROM chunks_fts`。特殊的 FTS5 `INSERT ... VALUES('delete', ...)` 在当前表结构上会报 SQL logic error，不能用它完成在线删除。

上表是 A 期供测 SHA `bc0698bc571f9b859eb28e46aa88058c75ded77d` 的差异原样。DOC 的 DIFF-06 要求把 CSRF/Origin、增补接口和 FTS 删除方式留给 ARCH/TEST，所以这里不改写、不删行，也不把它们说成已经通过。

## B 期在其后的变化

这些变化不推翻上表，只说明后续提交相对 A 期供测又做了什么。

| 项 | B 期现状 | 仍待他人判断 |
| --- | --- | --- |
| 账号在线删除 | `DELETE /api/auth/me?confirm=true` 会立刻撤销会话、移除在线对象和索引，并把助手事件里的摘录清掉 | A 期那一行的 405 只对供测 SHA 成立。安全有效性未签收 |
| 30 天备份清除 | 备份目录写入 `zhixu-backup.json`。`tools purge --yes` 和配置了 `ZHIXU_BACKUP_DIR` 时的启动会删除超过保留天数的子目录。默认 30 天 | DEV 用改过时间的目录跑过。不是 C 期恢复验收。没有用户自助恢复 |
| 标题搜索与删除确认 | 列表按更新时间排序，标题可改可搜；删除会话必须 `confirm=true`，并可选择是否连同只属于该会话的附件一起删除 | 浏览器点击路径未采集 |
| PDF/DOCX | 在同一隔离子进程里用 pypdf 5.9.0、python-docx 1.2.0 提取。缺库或隔离不可用则失败，不改在主进程解析 | 写下 B 期时，中文编码 PDF 样例未采集。许可证登记不是漏洞扫描 |

## DIFF-06 与固定 A 的静态评审

来源是 ARCH 的 `DOC-ZHIXU-ARCH-DEVREV-001` / `RV-ZHIXU-ARCH-PR1-A-001` v0.2。它只审固定 A 供测 SHA `bc0698bc571f9b859eb28e46aa88058c75ded77d` 的接口、配置和 FTS 源码，没有运行程序。

该评审把下面四项看成获批方案里的实现细化，不需要另开变更请求：接口增补、查询词用 OR、FTS 使用普通 `DELETE FROM chunks_fts`、登录后同时校验 CSRF 令牌和 Origin。这比契约草稿里的「令牌或 Origin」更严，保持同时校验，不改回择一。

这份静态意见的效力停在固定 A 的上述范围。它不是安全验收，不是越权或竞态的运行通过，不是独立 TEST 签收，也不能外推成 B 期或 C 期已经通过。A 期表里的原行继续保留，不改写成「已无差异」。

生产环境的 Secure Cookie 和 Origin 白名单没有被豁免。`ZHIXU_COOKIE_SECURE` 默认关闭、`ZHIXU_ALLOWED_ORIGINS` 默认只含本机地址，只表示本机 HTTP 的出厂值。抄到 HTTPS 或别的网址上，不能称为已经满足获批安全默认。

## C 期开发侧补上的缺陷

这些是本次开发回归里看到并改的实现缺口，不是旧批准，也不是旧缺陷单。

| 发现 | 关联 | 改动 | 还不能说的 |
| --- | --- | --- | --- |
| ADV-11 | 契约 `GET /files/:id/status` 的 `progress`；REQ-ZHIXU-P0-05 | B 期 SHA `7e6ad8a6d37009d545316091ea2eb751e6427458` 的状态接口仍不返回 progress。`f62debf71f02f889fc340a241c686accbbbc94e1` 的 `server/zhixu_server/api.py` 按当前任务回传 `progress` 和 `job_id` | 不是独立验收。越权仍返回 403 |
| FIND-ZHIXU-CDEV-001 | REQ-ZHIXU-P0-05，DES-ZHIXU-BE-001 | 重启后未完成的解析改为按已保存文件重新排队，最多三次；进行中的生成标为中断，不自动重放给模型 | 不是真实上游取消验收 |
| FIND-ZHIXU-CDEV-002 | REQ-ZHIXU-P0-05，同一版本索引 | 重新索引前先删掉该版本旧分块，避免重试后检索到重复段 | 不是检索质量验收 |

## DEF-ZHIXU-A-TEST-001

独立 TEST 的 `followup.json` 校验和是 `b993c029e67086f81ddaae856d3be283e2b620d0213b2ed47fce4329a739be93`。那份记录是他们在固定 A `bc0698bc571f9b859eb28e46aa88058c75ded77d` 上的 8 次：6 次停在 `cancel_requested` 且 `finalized=1`、再发 409，2 次 `stopped` 且再发 202。那不是这次开发自己的次数。已撤回的两条删除误报不在这次修改里。

这次先在已提交的 `5c2b93eabcf784ddbdcc90d0d125e83bbb0edfaa` 上按同样步骤复现：夹具、`ZHIXU_FIXTURE_HOLD=1`、同一登录的 Cookie、Origin 和 CSRF，等第一条 `delta`，连续两次取消，再向同一会话发送。8 次里 5 次停在 `cancel_requested` 且 `finalized=1`、再发 409 `generation_in_progress`；3 次 `stopped` 且再发 202。助手正文仍是已经写出的半句，终态事件只有一条。

原因是后一次取消先读到进行中，生成线程已经写成 `stopped` 之后，取消接口仍把状态改回 `cancel_requested`，`finalized` 保持 1。进行中的取消继续拒绝再发，这条 409 没有放宽。

修复只让尚未结束的请求写成 `cancel_requested`。已经结束的行不再被改回去。生成侧第一个终态才能落库，完成和失败不能盖过取消。修后同样步骤连续 16 次，16 次都是 `stopped`、`finalized=1`、一条完成事件、半句保留、再发 202。上游返回 500，以及流在 `[DONE]` 之前断开，终态都是 `failed`，各有一条错误事件，之后可以再发。这仍是夹具协议，不是真实 Qwen 取消，也不是独立 TEST 复验。
