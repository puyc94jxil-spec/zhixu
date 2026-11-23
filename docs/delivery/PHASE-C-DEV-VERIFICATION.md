# C 期开发侧核对

这是开发自己跑过的安全回归和剩余实现核对。它不是 C 期独立验收，不是 TEST 签收，也不是上线或合并批准。

固定 A 供测 SHA 仍是 `bc0698bc571f9b859eb28e46aa88058c75ded77d`。固定 B 说明 SHA 仍是 `7e6ad8a6d37009d545316091ea2eb751e6427458`。这次没有改这两次历史，没有 force-push，没有合并。

## 1. 这次的提交和合并请求

| 用途 | 完整 SHA |
| --- | --- |
| A 期供测，独立 TEST 仍钉这一版 | `bc0698bc571f9b859eb28e46aa88058c75ded77d` |
| A 期措辞修正 | `5ddbc5827741b49802f5bc2df302874537109f6d` |
| B 期实现 | `e54c405f400ee2571692c23b704bd50f6808fff9` |
| B 期 SHA 补记，已交 PM | `7e6ad8a6d37009d545316091ea2eb751e6427458` |
| C 期开发回归和 ADV-11 进度字段 | `f62debf71f02f889fc340a241c686accbbbc94e1` |

若后面还有只改说明、不改行为的提交，它不替换上面这一行，也不替换固定 A 或固定 B。

合并请求仍是 https://github.com/puyc94jxil-spec/zhixu/pull/1 ，开着，未合并。分支是 `cursor/zhixu-p0-phase-a-71ab`。

版本号改成 `0.3.0-phase-c`，只用于辨认这次开发构建，不是发布号。

## 2. 文件状态 progress（ADV-11）

固定 A 和 B 期 SHA `7e6ad8a6d37009d545316091ea2eb751e6427458` 都没有把 `progress` 放进 `GET /api/files/{id}/status`。任务表里本来就有这个字段，接口没返回。

`f62debf71f02f889fc340a241c686accbbbc94e1` 的 `server/zhixu_server/api.py` 现在按该文件当前任务回传 `progress` 和 `job_id`。别人的文件仍是 403，响应里没有进度。就绪后进度为 100。自测是 `server/tests/test_phase_c.py` 的 `test_file_status_returns_job_progress`。界面轮询时会把百分比放进提示文字。浏览器没有点击这条提示，不能写成已经点过。

## 3. 这次实际跑的命令

环境：Python 3.12.3，SQLite 3.45.1，Node v22.23.4，bubblewrap 0.9.0。业务依赖在 `/tmp/zhixu-py`，因为本机没有 `python3-venv`。

```bash
cd /workspace/server
export PYTHONPATH="/tmp/zhixu-py:$PWD"
python3 -m ruff check zhixu_server tests
python3 -m pytest tests -q --tb=line
cd /workspace/web
node --test input_rules.test.js phase_b.test.js phase_c.test.js
```

结果：ruff 通过。pytest 32 项通过，约 22.9 秒，没有失败项。Node 8 项通过，没有失败项。其中 C 期新增的是 `tests/test_phase_c.py` 9 项和 `web/phase_c.test.js` 2 项。这些是开发自测，不是 51 条正式用例，也不是独立 TEST。

协议和竞态用的是本机临时端口上的夹具。夹具通过不能写成真实 Qwen、语义支撑、真实上游取消或性能通过。

## 4. 漏洞查询

许可证登记在 `docs/delivery/DEPENDENCY-REVIEW.md` 前半，不是漏洞扫描。

pip-audit 2.10.1 对 OSV 的查询时间和结果也写在该文件后半。直接用系统 Python 解析 `requirements.txt` 时因为没有 `ensurepip` 失败，那一次没有查到漏洞库。`--local` 那次只看到扫描工具自己的 24 个包，不能当成业务依赖已经扫过。

真正查到业务依赖的两次都有发现：pypdf 5.9.0、python-multipart 0.0.20、pytest 9.0.1，以及环境查询里由 FastAPI 带入的 starlette 0.49.3。本次没有改这些版本。pypdf 升到 6 和 starlette 升到 1 会离开当前获批主版本，留给 PM 决定。没有把「有发现」写成「没有漏洞」。

## 5. 需求对照

「已实现」指当前分支代码里有相应行为。「开发自测」指上面的命令真的跑过对应脚本。「独立验证」一律还没有签收。空白格不用夹具填成通过。

| 需求 | 已实现 | 开发自测 | 独立验证 |
| --- | --- | --- | --- |
| REQ-ZHIXU-P0-01 登录与隔离 | 注册登录、HttpOnly 会话、跨用户 403 | A 期登录测试；C 期 `test_cross_user_csrf_session_and_sse_reconnect` | 未签收。HTTPS 上的 Secure Cookie 未在浏览器核对 |
| REQ-ZHIXU-P0-02 流式问答 | 服务端 SSE、停止保留已写出的半句 | A 期夹具流；C 期取消竞态看到停止态且上游调用次数不增加 | 未签收。真实 Qwen 和真实上游取消未测 |
| REQ-ZHIXU-P0-03 多轮上下文 | 同一会话历史进入下一次请求；其他会话不并入 | A 期多轮测试；C 期撤销后的下一次请求含占位句、不含已删原句 | 未签收。真实模型上下文未测 |
| REQ-ZHIXU-P0-04 标题搜索和排序 | 列表按更新时间倒序，标题包含搜索；删除要确认 | C 期 `test_title_search_and_sort` | 未签收。浏览器点击未测 |
| REQ-ZHIXU-P0-05 上传、状态、恢复、幂等、去重 | 状态轨迹写入日志；重启后未完成解析重新排队；同一幂等键冲突返回 409；同用户哈希复用、跨用户不复用；状态接口返回 progress | C 期 `test_upload_status_restart_idempotency_and_dedup`、`test_file_status_returns_job_progress`、中文 PDF/DOCX/长文测试 | 未签收 |
| REQ-ZHIXU-P0-06 材料问答与拒编 | 无依据或数字对不上时整段撤回为「资料中未找到」；一条对不上的声明不会留在最终正文 | C 期夹具 `test_cancel_delete_race_and_prompt_injection`。这只是字面守卫 | 未签收。语义是否支持结论未测 |
| REQ-ZHIXU-P0-07 可定位引用 | PDF 带页，DOCX 带段并提示没有页码；预览按同一版本定位 | B 期定位测试；C 期中文 PDF 抽出「预算」和「1200」，长文锚点可定位 | 未签收。浏览器点击高亮未测 |
| REQ-ZHIXU-P0-08 删除、备份和 30 天清除 | 在线删除去掉对象和索引；WAL 用 SQLite 备份接口，不手拷主库；过期备份目录可删；数据目录拒绝被当成备份根目录 | C 期删除竞态、`test_wal_backup_restore_and_purge`；B 期账号删除 | 未签收。没有用户自助恢复 |
| REQ-ZHIXU-P0-09 反馈 | 只存原因和短说明 | B 期测试确认说明不进日志，别人的消息 403 | 未签收 |
| REQ-ZHIXU-P0-10 输入 | 空白不发送；Enter 与 Shift+Enter、输入法组词分开 | `web/input_rules.test.js` | 未签收。浏览器未点 |
| REQ-ZHIXU-P0-11 失败重试 | 失败保留原问题，重试不重复插入用户消息 | A 期相应测试 | 未签收 |
| REQ-ZHIXU-P0-12 排版和复制 | 回答用文本节点绘制；脚本、事件和 `javascript:` 链接保持为文字；复制成功或失败有固定短句 | `web/phase_c.test.js` | 未签收。浏览器剪贴板未点 |
| REQ-ZHIXU-P0-13 上下文边界 | 超限时记下摘要策略、被摘要的消息和全部附件 ID；放不下则要求新建会话，附件仍启用 | C 期 `test_context_bound_records_attachments` | 未签收。不是模型摘要质量 |
| REQ-ZHIXU-P0-14 错误和重连 | 未配置、超时、限流等有分开的失败码；重连续传只回放已保存事件 | A 期错误映射；C 期重连续传不增加上游调用次数 | 未签收。真实断网、限流和超时未测 |
| REQ-ZHIXU-P0-15 模板 | 没有就绪文档时，文档模板禁用并说明原因 | `web/phase_b.test.js` | 未签收。浏览器未点 |

## 6. 安全回归里实际看到的行为

下面都来自 `tests/test_phase_c.py` 的通过结果。夹具不是模型验收。

- 另一个账号读会话、订阅 SSE、看文件状态，得到 403。缺 CSRF、错误 Origin、登出后继续写，都被拒绝。
- 已完成请求用 `Last-Event-ID` 再拉一次，上游调用次数不变，不会重新生成。
- 生成暂停时取消：状态变为停止，已写出的半句保留，上游只被调用一次。
- 生成暂停时删除依据文件：最终正文变成占位句，保存的增量里不再有原句，预览不再成功，下一次送给模型的内容含占位句、不含被删原句。
- 夹具若给出对不上的数字或原文里没有的摘录，最终正文撤回为「资料中未找到」。有一条对得上、一条对不上时，只留下对得上的那句。
- 隔离探针在同一套 bubblewrap 参数下测到：不是 root、访问测试地址 `203.0.113.1:9` 失败、哨兵文件读不到。子进程里的资源上限是地址空间 256MB、CPU 60 秒、单文件 32MB、64 个文件描述符、32 个进程，并且不能往 `/usr` 写。探针被改成不可用时，解析直接失败，不在主进程里改解析。
- 中文样例是 `server/fixtures/zh_budget.pdf`，沙箱里的 pypdf 能抽出「预算」「1200」和「市民图书馆」。另有中文 DOCX 和超过一段的长文。没有用只有英文或没有文字的 PDF 代替这次中文提取。
- SQLite 在另一个连接已提交之后做在线备份，恢复出的库含有提交后的标题。删除之后的备份则带删除标记。超过 30 天的备份目录被删，1 天内的留下。在线数据目录因为带数据标记而拒绝被清除。

日志和夹具不写密码、密钥或样例正文。模型地址只从环境变量来。本次没有扫描、隧道或公开内网地址。

## 7. 固定 A 静态评审怎么用

`DOC-ZHIXU-ARCH-DEVREV-001` / `RV-ZHIXU-ARCH-PR1-A-001` v0.2 只覆盖固定 A 的接口、配置和 FTS 源码。它认可接口增补、OR 分词查询、普通 FTS DELETE、CSRF 与 Origin 同时校验属于获批实现细化，不需要变更请求。

这不等于那些机制已经运行通过，更不能外推成 B 期或 C 期验收通过。DIFF-06 的记录见 `docs/delivery/DEVIATIONS.md`。生产 Secure Cookie 和 Origin 限制没有被这份记录豁免。

## 8. 还没做，以及内网和 TEST 至少要补的步骤

本环境没有做的：

- 真实 Qwen 连通、流式、鉴权和真实上游取消。
- 引用在语义上是否支持结论。
- 性能和容量。
- 浏览器点击。本机有 Chrome，但这次没有打开页面去点登录、复制、删除或进度提示。
- 在 HTTPS 上核对 `Set-Cookie` 是否带 Secure。

内网或独立 TEST 至少还要：

1. 只用环境变量注入获批的模型地址、模型名和密钥，测通流式、取消是否真的停掉上游、引用核验和撤回。内网不可达就记为未测，不要用夹具填通过。不要从这台云环境扫描或转发该内网。
2. 在目标 HTTPS 站点设置 `ZHIXU_COOKIE_SECURE=1`，并把 `ZHIXU_ALLOWED_ORIGINS` 设成实际页面来源。核对 Secure、HttpOnly、SameSite，以及跨源写入被拒绝。
3. 用浏览器走一遍标题搜索、删除确认、复制和文件进度提示。
4. 由 TEST 按自己的用例签收。开发这 32 项 pytest 不能代替。
5. 由 PM 决定 pypdf、python-multipart、starlette 的版本是否升级。开发没有自行换到 6.x 或 1.x。

C 期开发回归到这里结束。这不是 C 期独立验收，也不是上线批准。
