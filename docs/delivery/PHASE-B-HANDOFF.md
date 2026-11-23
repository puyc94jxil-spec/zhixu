# B 期接手说明

A 期供测基准保持不动：`bc0698bc571f9b859eb28e46aa88058c75ded77d`。实现祖先仍是 `54f84fce2fef4dd3bf75eab893e16b4437734b54`。措辞修正提交是 `5ddbc5827741b49802f5bc2df302874537109f6d`。后面的分支 HEAD 不能替换这个 A 期供测 SHA。

B 期快照是包含本说明的提交。完整 SHA 写在交付回报里；若本文件再补一行 SHA，那一行只标记 B，不改 A。

本说明记录 DEV 自己跑过的命令。它不是独立 TEST 签收，不是正式用例通过，也不是安全验收或上线。

## 1. 范围完成矩阵

依据仍是 `APPR-ZHIXU-001` v0.2-draft、`BL-ZHIXU-REQ-001`、`BL-ZHIXU-DES-001`。下表只区分「A 期供测已有」「B 期 DEV 又做了并跑过自测」「还没验」。

| 需求 | B 期代码 | DEV 自测 | 还没验 |
| --- | --- | --- | --- |
| REQ-ZHIXU-P0-01 跨客户端 | 同一账号两次登录都读服务端会话 | `test_feedback_account_delete_and_second_client` | 独立 TEST |
| REQ-ZHIXU-P0-04 标题/搜索/排序/删除确认 | 标题可改，列表按 `updated_at` 倒序并按标题包含搜索；删除要 `confirm=true`，可选是否删仅属于该会话的附件 | 同一条自测覆盖改标题和另一个客户端搜索 | 浏览器点击未采集 |
| REQ-ZHIXU-P0-05 PDF/DOCX、限额、异常、去重、幂等 | `parser_child.py` 在 bubblewrap 中调用 pypdf / python-docx；20MB、5 个、50MB、PDF 200 页；加密、损坏、无文字、超页、类型不符分开 | `test_pdf_and_docx_location_and_independent_failure`、`test_pdf_error_classes_and_dedup` | 中文编码 PDF 未采集 |
| REQ-ZHIXU-P0-07 页/段定位 | PDF 块带页码；DOCX 块带段落，`parse_notice=page_unavailable` | 预览断言页内文字含 `1200`；DOCX 断言缺页提示 | 点击高亮的浏览器路径未采集 |
| REQ-ZHIXU-P0-08 三类删除 | 文件删除、带确认的会话删除、账号在线删除都会摘掉索引和对象；已存 SSE 的增量和引用摘录被清空 | 账号删除与完成后删除文件的事件重放 | C 期竞态验收未签 |
| REQ-ZHIXU-P0-09 反馈 | `POST /api/messages/{id}/feedback`，只存原因和最多 200 字说明 | 说明没有进日志；别人的消息返回 403 | 独立 TEST |
| REQ-ZHIXU-P0-12 排版与复制 | `web/markdown.js` 只用文本节点画出段落、列表、表格、代码；复制成功或失败都有提示 | `phase_b.test.js` 断言脚本文字不会变成可执行结构 | 浏览器复制未采集 |
| REQ-ZHIXU-P0-13 超限摘要 | 超限时记下消息 ID、附件 ID 和省略的块 ID；仍放不下则 `context_too_large`，附件保持启用 | 把上限临时改成 120 后断言附件 ID 仍在 | 真实模型摘要质量未验 |
| REQ-ZHIXU-P0-15 模板 | 没有就绪文档时，三个文档模板禁用并说明原因；自由提问仍可用 | `phase_b.test.js` | 浏览器未采集 |
| 30 天备份清除 | `purge_expired_backups`；数据目录本身拒绝清除 | 31 天目录删除、1 天目录保留 | 不是恢复验收 |

Q03、Q04 和 Q07 的基础映射仍在 A 期自测里。真实超时、限流和断线上游仍待验。

## 2. 这次 DEV 实际跑的命令

环境：Python 3.12.3，SQLite 3.45.1，Node v22.23.4，bubblewrap 0.9.0。依赖装在 `/tmp/zhixu-py`，因为本机没有 `python3-venv`。接手方应自己安装 `server/requirements.txt`。

```bash
cd server
export PYTHONPATH="/tmp/zhixu-py:$PWD"
python3 -m ruff check zhixu_server tests
python3 -m pytest -q --tb=line
node --test ../web/input_rules.test.js ../web/phase_b.test.js
```

结果：ruff 通过；pytest 23 项通过（含原 A 期 16 项和 B 期 7 项）；Node 6 项通过。没有失败项。没有把测试计划 `DOC-ZHIXU-TEST-PLAN-001` 或用例目录拿来执行。

新增钉选：pypdf 5.9.0、python-docx 1.2.0、lxml 6.1.3、typing-extensions 4.16.0。审查做到哪一步见 `docs/delivery/DEPENDENCY-REVIEW.md`。

## 3. 怎么启动和清除备份

常规（非夹具）启动与 A 期相同：`ZHIXU_UPSTREAM_MODE=unconfigured` 或显式 `live`。模型地址、模型名和密钥只从环境变量来。

```bash
python3 -m zhixu_server.tools backup --dest /path/to/backup-root/snapshot-1
python3 -m zhixu_server.tools purge --backup-root /path/to/backup-root --yes
```

也可以设置 `ZHIXU_BACKUP_DIR`。进程启动时会按 `ZHIXU_BACKUP_RETENTION_DAYS`（默认 30）清除该目录下过期且带 `zhixu-backup.json` 的子目录。清除不会动带 `ZHIXU_DATA_MARKER` 的在线数据目录。没有用户自助恢复接口。运维恢复仍是 `tools restore`，写到新目录。

## 4. 剩余的 C 期和模型待验

- 真实 Qwen 连通、鉴权、流式、超时和真实上游取消：未验证。
- 引用是否在语义上支持结论：未验证。当前仍是摘录和数字是否出现在对应块里。
- 隔离强度、提示注入、越权之外的安全验收：未签收。本环境隔离探针和「缺库则拒绝解析」只是 DEV 证据。
- 中文编码 PDF 的提取：未采集。这次 PDF 自测用的是能抽出 `Budget 1200` 的一页文件；中文段落用的是 DOCX。
- 浏览器里的改标题、删除确认、复制和模板点击：未采集。
- 性能和容量阈值：未采集，也不当作已经达标。

DIFF-06 里的 CSRF 与 Origin 同时要求、增补接口、检索用 OR、FTS 用普通 DELETE，都还留在差异清单里，等 ARCH/TEST，没有在文档里改成「已无差异」。
