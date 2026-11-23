# 知序实现契约（接口 / 数据 / 权限 / 引用）

---
文档追踪ID：DOC-ZHIXU-IMPL-CONTRACT-001  
关联设计ID：DES-ZHIXU-API-001（接口与 SSE）、DES-ZHIXU-DATA-001（数据/FTS/版本）；并细化已有 DES-ZHIXU-FE-001、BE-001、STORE-001、MODEL-001、DOC-001、AUTH-001、SEC-001  
版本号：v0.1-draft  
文档类型：面向实现的契约细化（ARCH 自拟，**不是**新的人类批准件，也不是同行评审通过记录）  
状态：草稿；供实施对照。人类已批准的是 APPR-ZHIXU-001 v0.2-draft 的范围/方案/安全默认与三期推进、不合并不上线；**本契约正文未经另一次人类批准**  
责任岗位：AI-ARCH  
起草时间：2026-11-23 14:19–14:22（Asia/Shanghai）  
上游需求：源仓《需求文档.md》V1.0 方案稿（commit `ac62ee813425b2a8494324ae9cb28585e1303e29`）之全部 P0  
上游方案：`/workspace/cmmi5-team/03-projects/zhixu/candidate-implementation-approval.md`（DOC-ZHIXU-CAND-IMPL-001 / APPR-ZHIXU-001 v0.2-draft）  
固定源 commit：`ac62ee813425b2a8494324ae9cb28585e1303e29`  
基线标识：工作区当前未见已落盘的正式 BL- / APPROVAL-RECORD（见第 2 节，未臆测已完成）  
评审记录：无同行评审、无人类对本细化的批准。不得填写“已通过”  
---

## 0. 给 PM 可转 DEV 的注意项（不调度 DEV，不请用户重复审批已批内容）

下列为获批方案内的实现必须项与待验项，不是新范围。合并、上线仍不在批准之内。

**必须实现（期 A 起，除非注明 B）：**

1. **检索字段分离与授权范围：** chunk 同时保存原文 `text`（及页/段/offset）和 jieba 预分词字段；FTS5 只检索分词字段，定位与引用校验只用原文与位置字段。查询同样先 jieba 再检索。索引与检索只能命中**当前会话已授权、未删除、版本匹配**的文档。
2. **删除材料不得再进入后续模型上下文：** 删除/撤销后立即从在线索引移除；构造多轮请求时不得再发送已删文件的 chunk，也不得把旧消息里来自已删材料的正文/引用再送给模型（最小做法见第 11 节）。最终输出与预览前重校验 owner、version、删除标志；取消须中止上游。
3. **SSE 与引用核验：** 流式文本为临时未核验态，未校验引用不可点击。材料结论逐条绑定 chunk+quote，失败则阻止最终化或撤回为「资料中未找到」。支持生成中禁重复发送、请求归属原会话（切会话不串流）、可用 last_event_id 重连；幂等键防重复提交。
4. **文件版本与原型：** 同一 `file_id+version` 内容不可变；内容去重不得跨 owner 授权。改在线前端前，将既有 `index.html` / `styles.css` / `app.js` / `output/` 保留到独立 `prototype/` 目录，不把原型目录改成生产唯一入口。预览接口必须带分页与高亮字段（第 9.3 节）。
5. **账号与任务持久化：** Argon2id、CSRF/Origin、SameSite+HttpOnly（生产 Secure）、登录限速；解析用非特权无网子进程 + SQLite 任务表可恢复；SQLite 用在线备份 API/一致快照，禁止拷 WAL 中主文件。这些是获批约束，**落地后仍待验，不得在实现时改称已通过**。

**待验（可开发、不得标通过，内网不通不全局停工）：** 真实 Qwen 流式兼容与质量、引用支持性/幻觉中文样例、超时/429 映射、删除/取消竞态与部分输出残留、备份恢复、解析隔离有效性、越权与 CSRF 实测。Mock 只用于协议开发。

**不要做：** 合并/上线、改 GitHub 权限、迁 React/Vue 或上向量库、把本契约当成已另批的基线、修改已发给用户的 v0.2 批准附件正文。

---

## 1. 批准来源核验（仅据原文，不以 PM 转述代替）

核验方法：`GetDynamicTools` 后调用 `cursor.bot.ReadTranscript`（`in=64fb40e3-9660-48b4-9aab-a98bb718f949`，读取该 PM bot 最近对话）及 `SearchTranscripts`。以下为该转写中的**原始用户消息与卡片记录**，不是本岗批准。

| 项 | 核验到的事实 |
| --- | --- |
| 时间 | 用户消息带时间戳 `Monday, Nov 23, 2026, 2:18 PM (UTC+8)`，即 **2026-11-23 14:18（Asia/Shanghai）** |
| 卡片 | PM 此前 `SendToUser` 结果 id 为 **t23s2**，`type=widget`。prompt 原文：「是否批准附件 v0.2 的需求范围、技术方案和安全默认，按三期推进开发？」主选项 value 原文：「批准附件 APPR-ZHIXU-001 v0.2-draft 的完整P0范围、技术方案和安全默认，按三期推进开发，不合并或上线。」另一选项为暂不批准 |
| 附件对象 | 同轮先发出说明（id **t23s0**），再以 `type=attachment`、`url=file:///workspace/cmmi5-team/03-projects/zhixu/candidate-implementation-approval.md` 发送（id **t23s1**）。工具回执写明用户收到的是**当时文件副本** |
| 用户原话 | 该对话中 role=`user` 的 `<user_query>` 正文为：先有一行 `[Answering your question t23s2: "是否批准附件 v0.2 的需求范围、技术方案和安全默认，按三期推进开发？"]`，随后一行完整为：**批准附件 APPR-ZHIXU-001 v0.2-draft 的完整P0范围、技术方案和安全默认，按三期推进开发，不合并或上线。** 与主选项 value 一致 |
| 批准范围（按该句） | 附件所指 APPR-ZHIXU-001 **v0.2-draft** 的完整 P0 范围、技术方案和安全默认；按三期推进开发；**不合并或上线** |
| 本岗未在该条原文中看到 | 签署的法定姓名、逐条勾选第 13 节每一默认值的另附声明。不把 PM 事后对账户名的转述写成该条用户签名 |
| 未核验到 | 正式 BL- 编号已写入工作区；测试通过；发布批准 |

本轮核验时，批准附件本地路径仍为上述文件，文内版本号 `v0.2-draft`，大小 45727 字节，mtime 2026-11-23 14:15:53（Asia/Shanghai），SHA256：`9e2848fac817e01381ad037e42903b7aa8136b2b8509aea8439800a472c36cfe`。该文件文首状态栏仍写「候选未批准 / 人类决策：待审批」（批准前起草遗留），**本岗按指令不修改该正文**。批准事实以 PM 对话原文与本文件第 1 节记录为准，不以该文首过时状态栏否定 14:18 的用户答复。

本契约是获批方案内的实现细化，**不构成用户对本文件的批准，也不扩大已批范围**。

---

## 2. 本地 SCM / 基线文件（只读实测，不臆测已完成）

查询时间：2026-11-23 14:19–14:20（Asia/Shanghai）。`/workspace/cmmi5-team/03-projects/zhixu/` 当时仅有下列文件，**无** `06-baselines/`、**无** `APPROVAL-RECORD.md`、**无** 批准快照目录。PM 已另派 SCM 登记批准快照/基线，本岗写入时这些产物**尚未见到**，记「未采集」，不把派工当成已完成。

| 路径 | 角色 | SHA256（本岗 sha256sum） | 备注（文件自身陈述） |
| --- | --- | --- | --- |
| `/workspace/cmmi5-team/03-projects/zhixu/repository-register.md` | SCM 来源登记 AUD-ZHIXU-SCM-REG-001；采集 2026-11-23 14:02:05（Asia/Shanghai） | `d490d1113e2930a155e30fed22e7f7ae1d8c5442a571ce93908b791fca1cc946` | 与登记文内自称完整文件 SHA256 一致。记录源仓 public、`main`、完整 SHA `ac62ee813425b2a8494324ae9cb28585e1303e29`、`protected=false`；当时正式批准/冻结基线未采集。本登记本身不是编码/冻结/合并/发布授权 |
| `/workspace/cmmi5-team/03-projects/zhixu/document-register.md` | DOC-ZHIXU-001 v0.1-draft | `96ce682c5304b9db3d21c67abaa9a59edc1b5144554674620abd69915e732481` | 登记时写明未纳入基线。其后用户批准发生在 14:18，该文件是否已更新**本轮未当作已完成基线** |
| `/workspace/cmmi5-team/03-projects/zhixu/candidate-implementation-approval.md` | 已发用户并在 t23s2 获答复的批准对象 | `9e2848fac817e01381ad037e42903b7aa8136b2b8509aea8439800a472c36cfe` | 见第 1 节。本岗不改 |
| `/workspace/cmmi5-team/03-projects/zhixu/architecture-readiness.md` | 旧准入核查 DOC-ZHIXU-ARCH-RDY-001 v0.3 | `931e102fad8fa2b3c543b64d8a8b39192fe47961d734d21e1f030fa56a863292` | 按指令本轮不改 |
| `/workspace/cmmi5-team/03-projects/zhixu/test-readiness.md` | DOC-ZHIXU-TEST-READY-001 v0.1-draft | `82740dbdf8408063963b934636e17e7f31aa6e346cf1226b18d359a94263e9bd` | 测试就绪当时为 BLOCKED；本轮不改 |

`demo-cmmi5/06-baselines` 与本项目无关，不引用为知序基线。

---

## 3. 适用分期

与获批三期一致，不减 P0、不把 C 期当成上线批准。

| 期 | 本契约优先落地 |
| --- | --- |
| A | 账号/会话/CSRF、SSE 与 Qwen 适配、TXT/MD 上传解析检索引用、预览高亮、删除与在途校验的最小闭环、任务表、原型目录保留 |
| B | PDF/DOCX 与页码定位、完整限额与状态机、三类删除、反馈、标题搜索、Q05 消毒、跨设备完善、账户删除在线生效 |
| C | 安全与质量真实验证（含支持性样例、竞态、备份恢复）；通过与否未采集；≠ 合并/上线 |

接口路径可加统一前缀 `/api`，语义不变。JSON 使用 snake_case。时间字段用 ISO-8601，对用户展示换算 Asia/Shanghai。

---

## 4. 接口表（DES-ZHIXU-API-001）

公共约定：写接口需登录会话 + CSRF（见第 7 节）；成功包可含 `request_id`；错误包 `{ "error": { "code", "message", "request_id?" } }`，`message` 不回显密钥或文档全文。

| 方法路径 | 期 | 输入（关键字段） | 成功输出 | 主要状态码 |
| --- | --- | --- | --- | --- |
| `POST /auth/register` | A | `username` 或 `email`，`password`（明文仅在本次请求中出现，服务端 Argon2id 后丢弃） | `{ user_id }` + 设置会话 Cookie | 201；400 校验；409 已存在；429 限速 |
| `POST /auth/login` | A | 标识 + `password` | `{ user_id }` + 会话 Cookie | 200；401 失败；429 限速 |
| `POST /auth/logout` | A | 无（凭 Cookie） | 204，清除 Cookie | 204；401 |
| `GET /auth/me` | A | — | `{ user_id, username? }` 无密码哈希 | 200；401 |
| `POST /conversations` | A | 可选 `title`；`Idempotency-Key` | `{ id, title, created_at, updated_at }` | 201；401 |
| `GET /conversations` | A | `q?` 标题搜索，`cursor?`/`limit?` | `{ items:[{ id, title, updated_at }], next_cursor? }` 仅本人，按 `updated_at` 降序 | 200 |
| `PATCH /conversations/:id` | A/B | `title?` | 更新后对象 | 200；403/404；B 期完善可编辑标题规则 |
| `DELETE /conversations/:id` | A 最小 / B 齐备 | `confirm=true`，`delete_files?`（是否一并删仅被该会话引用的文件） | 204 | 200/204；400 缺确认；403/404。删除后见第 11 节 |
| `POST /files` | A：TXT/MD；B：PDF/DOCX | `multipart`：`file`，`conversation_id`；可选 `Idempotency-Key` | `{ file_id, version, name, mime, size, hash, status, job_id }` | 201/202；400/413/415 超限或格式；401/403 |
| `GET /files/:id/status` | A | — | `{ file_id, version, status, progress?, error_code?, page_count? }` 状态枚举与获批稿一致：`uploaded`→`scanning`→`parsing`→`indexing`→`ready` / `failed` | 200；403/404 |
| `DELETE /files/:id` | A 最小 / B 齐 | `confirm=true` | 204；在线索引与可见对象立即不可用 | 204；403/404 |
| `GET /files/:id/preview` | A/B | 见第 9.3 节分页与高亮查询参数 | 见第 9.3 节 | 200；403/404；409 版本不匹配或已删除 |
| `POST /conversations/:id/messages` | A | `{ content, client_message_id? }`，`Idempotency-Key` 推荐；空内容 400 | `{ message_id, request_id, status:"accepted" }` | 202；400 空白；409 生成中重复发送；401/403/404 |
| `GET /requests/:id/events` | A | SSE；可选 `Last-Event-ID` | 见第 8 节 | 200 `text/event-stream`；403/404 |
| `POST /requests/:id/cancel` | A | 幂等 | `{ request_id, status:"stopped" }` | 200；404；重复取消仍 200 |
| `POST /messages/:id/feedback` | B | `{ reason, note? }` 不默认多采私人字段 | `{ message_id, accepted:true }` | 201；403/404 |

账号数据删除（B）：建议 `DELETE /auth/me` 且 `confirm=true`（获批「账号数据删除」，路径为细化建议）。在线数据立即不可用，见第 14 节。

---

## 5. 幂等与并发

- 写接口支持 `Idempotency-Key`（或 `client_message_id`）：同一用户同一键在窗口内返回同一业务对象，不创建第二条用户消息、不启动第二个生成请求。
- **生成中禁止重复发送**（获批 Q02）：同一 `conversation_id` 存在 `status=streaming|verifying` 的请求时，新的 `POST .../messages` 返回 **409** `generation_in_progress`，不插入新用户消息。
- **切会话：** 进行中的请求仍绑定原 `conversation_id` 与 `request_id`；订阅必须带该 `request_id`。打开另一会话不得把原 SSE 事件写入另一会话视图，也不得默认取消原请求（获批：切换会话保留所属请求状态）。取消只通过 `POST /requests/:id/cancel`。
- **SSE 重连：** 每条事件有单调 `id`（字符串化序号）。重连带 `Last-Event-ID`：若请求仍在进行或缓冲仍在，从下一条重放；若已结束，重放自该 id 之后的终结事件（`done`/`error`）或 410/409 提示改拉消息快照。禁止重连导致重复最终化或再调一次上游。
- 解析任务：同一 `file_id+version` 不并行跑两个成功路径；取消/失败后重试生成新 `job_id` 或明确 `attempts+1`，写入任务表。

---

## 6. 数据实体与约束（DES-ZHIXU-DATA-001）

沿用获批实体，补可执行字段。均含 `owner_user_id`（User 为自身 id）。禁止仅凭可猜测 id 访问。

| 实体 | 关键字段与约束 |
| --- | --- |
| User | `id`，凭证 **Argon2id** 哈希（非明文），`deleted_at?`。无匿名用户（获批默认） |
| Session | `id`，`user_id`，`expires_at`，csrf 秘密与会话分开存放 |
| Conversation | `id`，`owner_user_id`，`title`，时间戳，`deleted_at?` |
| Message | `id`，`conversation_id`，`role`，`content`（最终可见正文），`status`（见第 8 节），`model?`，`request_id?`，`version`（Q04 新回答版本递增），`withdrawn_reason?` |
| File | `id`，`owner_user_id`，`hash`，`name`，`mime`，`size`，**`version` 不可变**，`status`，`object_key`，`deleted_at?` |
| ConversationFile | `(conversation_id, file_id, version)`，`enabled`，授权不得超出该 file 的 owner |
| Chunk | `id`，`file_id`，`version`，`page?`，`paragraph?`，`offset`（原文起始字符，0 基），`length`，**`text` 原文**，**`fts_lex` jieba 分词以空格连接**。位置字段与 `text` 只来自提取结果，不经 FTS 回写 |
| Citation | `message_id`，`claim_id`，`chunk_id`，`quote`，位置拷贝，`verified_at?`；仅 `verified` 可对前端作为可信引用 |
| ParseJob | `id`，`file_id`，`version`，`status`，`progress`，`error_code`，`attempts`，时间戳；**持久化 SQLite，勿只放内存** |
| Request | `id`，`conversation_id`，`owner_user_id`，`status`，`last_event_id`，`upstream_cancelable` |

**FTS5：** 使用单独虚拟表，索引 `chunk.fts_lex`（及 `chunk_id`），查询前对用户查询做**同一 jieba 模式**分词再匹配。过滤必须 JOIN：`ConversationFile.enabled=1` 且 file/chunk `version` 一致且 `deleted_at IS NULL` 且 `owner_user_id` 为当前用户且属于该 `conversation_id`。不得对全库或他用户文档建可用检索。检索质量用中文样例量测（待验），不宣称优于向量、不宣称杜绝错引。

**去重与隔离：** 相同 `owner_user_id+hash` 可复用对象与提示「同内容」，但 **ConversationFile 授权仍按会话显式绑定**；**禁止**因 hash 相同把 A 用户文件授权给 B 用户。

---

## 7. 个人 owner 隔离与 session / CSRF

- 默认须登录。Cookie：`HttpOnly`、`SameSite`（建议 `Lax` 或更严），生产 **Secure**。会话服务端存储，可吊销。
- 所有读/写/预览/SSE/检索按 `owner_user_id` 与会话授权过滤；跨用户 id 一律 403，不泄露是否存在。
- 状态变化的请求（POST/PATCH/DELETE 及带副作用的 GET 除外的写）校验 **CSRF 令牌或 Origin/Referer 白名单**（与获批 CSRF/Origin 一致）。SSE 订阅必须已鉴权，且 `request_id` 属于当前用户。
- 登录/注册限速。以上均为必须实现的获批约束，**实现完成 ≠ 已通过安全验收**。

---

## 8. SSE 状态机与事件结构

Request / Message 状态：`accepted` → `streaming` → `verifying` → `completed` | `withdrawn` | `stopped` | `failed`。禁止从失败/中止直接标 `completed`。材料结论未核验通过不得进入 `completed`（应 `withdrawn` 或继续修订后再次 `verifying`）。

事件（`id` 单调；`event` 名；`data` 为 JSON）：

| event | data 关键字段 | 含义 |
| --- | --- | --- |
| `delta` | `{ request_id, text, provisional:true }` | 临时生成，UI 须标未核验 |
| `citation` | `{ request_id, claim_id, file_id, version, page?, paragraph?, offset, length, quote, chunk_id, verified:true }` | **仅核验通过后**发出，才可点击 |
| `done` | `{ request_id, message_id, status:"completed"\|"withdrawn"\|"stopped", withdrawal_reason? }` | 终结。`withdrawn` 表示材料结论已撤回为未找到/未最终化 |
| `error` | `{ request_id, code:"timeout"\|"network"\|"rate_limited"\|"unauthorized_upstream"\|"internal", message }` | 非完成；可按获批映射提示 |

不得在 `delta` 中夹带 `verified:true` 的可点击引用。前端在 `done` 前把临时引用区保持不可信。

---

## 9. 文档 chunk、版本与预览高亮

- 提取：TXT/MD（A）；PDF=pypdf、DOCX=python-docx（B；许可证未审，仍为获批候选库）。扫描件不 OCR，无文本则不可 `ready`。
- `file_id+version` 对应唯一不可变对象。内容变更只能升 `version` 并重切块；旧 version 的引用仍指向旧对象，若文件已删则不可预览内容（可保留出处元数据并提示失败，不得跳转无关页）。
- chunk.`text` 用于展示、quote 校验（允许有限空白折叠后的子串命中）与高亮；`fts_lex` 只用于检索。`page`/`paragraph`/`offset`/`length` 映射原文，不因分词改变。

### 9.3 预览分页与高亮字段（必须实现）

`GET /files/:id/preview?version={int}&page={int?}&paragraph={int?}&start_offset={int?}&end_offset={int?}&quote={?}`

| 字段 | 位置 | 说明 |
| --- | --- | --- |
| `file_id` | 路径 | — |
| `version` | 查询，必填 | 必须与引用或当前授权版本一致，否则 409 |
| `page` | 查询 | PDF 页，1 基；TXT/MD 可省略或恒 1 |
| `paragraph` | 查询 | 段序号，可选 |
| `start_offset` `end_offset` | 查询 | 该页/全文原文偏移，闭开或闭区间须在响应中声明；建议半开 `[start,end)` |
| `quote` | 查询 | 可选，服务端用其校验与定位，失败仍返回出处元数据 + `highlight_error` |
| 响应 `content` | 体 | 当前页或段落原文（非 fts_lex） |
| 响应 `page` `page_count` `paragraph` | 体 | 分页信息 |
| 响应 `highlights[]` | 体 | `{ page, paragraph, start_offset, end_offset, quote, exact_match:boolean }` |
| 响应 `file_id` `version` `name` | 体 | 回显 |

预览前重校验 owner、会话授权、version、`deleted_at`。已删除：404/409，不返回正文。

---

## 10. 逐声明证据绑定与临时 / 最终核验

- 材料性结论（含金额、日期、来源断言）必须有 `claim_id`，绑定一个或多个 `{ chunk_id, quote }`。
- 流式阶段只有 `delta`（临时）。校验：quote 经空白折叠后须为对应版本 `chunk.text` 的子串。此检查**只证可溯源，不证语义支持**；支持性/幻觉用中文样例在 C 期量测（待验）。
- 失败：该 `claim` 不得最终化；消息进入 `withdrawn` 或去掉该结论并改为「资料中未找到」。**禁止**删除 citation 却保留无依据结论作为 `completed`。
- 已流出的临时文字须在 UI 与持久化中改为撤回/未核验，不得标「已完成且已引用」。

---

## 11. 删除 / 取消 / 在途输出与旧上下文防泄露

删除（会话/文件/账号）后立即：在线索引、ConversationFile.enabled、对象可见路径对在线请求不可用（获批）。

**在途竞态（必须实现，效果待验）：**

1. `cancel`：中止上游，停止新 `delta`，状态 `stopped`，已推增量按临时/中止保留（Q02），不标完成。
2. 删除或撤销授权：对相关 `request` 尝试中止上游；在**最终 `done` 与任何 preview 之前**再读库校验 owner、version、删除标志。失败则不得再推正文/引用，改为 `withdrawn`/`failed`/`stopped`。
3. **部分输出残留风险：** 若校验前已有 `delta` 到达客户端，须发撤回/中止事件；承认用户可能已看见片段。此风险 C 期真实验证，不能只靠设计声称已消除。

**多轮旧消息最小安全实现（必须，属获批「移除后不再读取」的可执行细化，不扩范围）：**

构造发给 Qwen 的 `messages` 时：

- 不附加已删/未授权文件的 chunk。
- 若历史 assistant 消息含已删或已撤销材料的引用或摘录：将该条 **不按原文重放**；替换为不含材料正文的占位，例如「[依据文件已删除或撤销，该轮材料内容不再纳入上下文]」。用户纯文本问题可保留。
- 已删文件 id 从本会话启用列表消失；后续追问不得再检索它们。
- 日志默认不写全文。

不要求物理粉碎历史审计备份中的副本（备份 30 天默认仍有效），但**在线生成路径不得再读**。

---

## 12. 解析任务恢复与 SQLite 备份 / 部署

- 解析仅在非特权独立子进程：无网络、受限目录、限 CPU/内存/解压/超时（获批建议值：墙钟 120 秒、展开体积 ≤ 原文件 10 倍，未实测）。工作线程不是隔离边界。
- `ParseJob` 落库；进程重启后扫描未完成任务，按幂等恢复或标记失败后可重试。禁止仅内存队列。
- 备份：SQLite **在线备份 API 或等效一致快照**，并连同私有对象与 file.version 对齐；**禁止**在 WAL 使用中简单拷贝主库文件。恢复验证待做（C，未采集）。
- 部署：后端须能达 `http://192.168.2.46:9938/v1`（或受控代理）；模型名 `Qwen3.8-27B`；密钥只在服务端环境/受控配置，不进仓库与浏览器。内网试验若无 TLS 须自担已批风险说明，密钥仍不得进浏览器。不可达时独立工作可继续，真实联调待验。

---

## 13. 原型目录

在修改将作为生产入口的页面/脚本之前，必须把源仓既有 `index.html`、`styles.css`、`app.js` 及 `output/` 保留到仓库内独立目录 **`prototype/`**（只对照、不作为生产唯一入口）。这是获批「另置 prototype 快照」的实现约定，不是新栈。

---

## 14. 账户删除与恢复策略

- 获批：账号数据删除后立即从在线索引与对象可见层移除；备份建议 30 天内清除。
- **实现建议（安全默认细化，不新增用户「一键恢复」产品能力，故不请用户再批）：** P0 不提供终端用户自助恢复。30 天内若需恢复，仅能由受控运维按一致快照处理，并须留下审计；期满按默认清除。若将来要做用户自助恢复，属范围扩展，须 **CR**，不得私自做进本包。

---

## 15. ARCH 自查：发现 / 处理 / 剩余风险

本次为 ARCH 对 v0.2 可执行性的自查与契约补全，**证据是 v0.2 文本与本文件**，不是测试运行，也**不是同行评审已过或人类批准了本细化**。

| 发现（v0.2 可执行性遗漏） | 处理（写入本契约，仍在获批方案内） | 剩余风险 |
| --- | --- | --- |
| FTS5 未规定原文位置字段与预分词字段如何并存，中文查询如何强制同分词 | 第 6、9 节：`text`+位置 vs `fts_lex`；查询同样 jieba | 分词质量与错引率未测；不宣称优于向量 |
| 未写死「索引/检索仅限会话授权文档」的过滤条件 | 第 6 节 JOIN 约束 | 实现若漏过滤会造成越权，属实现缺陷待测 |
| 删除后旧多轮消息可能把已删材料再送入模型，v0.2 未给出最小做法 | 第 11 节占位替换，禁止重放材料正文 | 占位策略仍可能残留提示性元数据；部分输出竞态待验 |
| SSE 重连、重复发送、生成中切会话缺少字段级约定 | 第 5、8 节：409、Last-Event-ID、请求绑定原会话 | 重连缓冲时长未规定（建议实现侧有限环形缓冲，不另开产品范围） |
| 文件版本不可变与跨用户 hash 去重隔离需写死 | 第 6、9 节 | — |
| 账户删除后「恢复」未说明，避免做成隐式新功能 | 第 14 节：无自助恢复；自助恢复须 CR | 30 天备份的恢复演练待做 |
| 在线改原型可能覆盖对照基线 | 第 13 节强制 `prototype/` | 若已有人直接改根目录文件，对照完整性待 DEV 开工时检查（本轮未看代码行为） |
| 预览/高亮缺少分页与字段 | 第 9.3 节 | 超长页的截断窗口大小未规定，实现可按页或按段返回全文再高亮，不扩范围 |
| 备份/隔离/会话防护已写约束但易被理解成已落地 | 文首与第 0 节标明必须实现但仍待验 | 未实现、未实测 |

---

## 16. CR 与未定（不要求用户重复审批已批内容）

- **不提 CR、不请再批：** 已获批的完整 P0、三期、栈、安全默认、不合并不上线；以及本文件中对 FTS 字段、删除后上下文、SSE 重连、预览字段、`prototype/`、账户删除无自助恢复等实现细化。
- **若要做则须 CR（当前不要做）：** React/Vue 迁移、独立向量库/多服务拆分、跨用户共享、匿名试用、用户自助恢复删除数据、P1/P2、合并或上线。
- **仍待定但不阻塞 A 期开工：** 上游鉴权头具体格式（服务端注入密钥时适配）、内网可达性、品牌/机房/预算（已批部署约束仅为网络可达）。这些按获批方案实施与待验，不必再问用户已知 URL/模型名或已批条款。

本文件不调度 DEV。由 PM 决定是否转达第 0 节注意项。
