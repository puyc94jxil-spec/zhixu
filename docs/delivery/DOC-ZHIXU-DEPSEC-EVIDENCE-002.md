# 依赖安全调查：可解析的单一候选

这是候选闸门 `DOC-ZHIXU-ARCH-DEPSEC-001` 之后的第二份 DEV 证据。它不是升级批准，不是安全通过，也没有改 `server/requirements.txt`。取消修复 `43b0fc3f5db7f1923e1c9b7bf3a4182ad08d0c1c`、固定 A、固定 B、C 期回归都没有改。真实 Qwen 仍未联调。

上一份 `docs/delivery/DOC-ZHIXU-DEPSEC-EVIDENCE-001.md` 只证明了已安装的 fastapi 0.121.0 不能配上工具列出的 starlette 1.x。那组现状带有扫描记录，不能当作修复候选。这一份补的是：打开公告原文、读取更新的官方发布元数据，并给出一组依赖解析能够装上、而且能盖住这次已有扫描记录的具体版本。

## 1. 这一组候选

状态是待判。没有装进跑服务的环境，也没有写进仓库依赖。

| 包 | 现在解析到 | 候选 | 角色 |
| --- | --- | --- | --- |
| fastapi | 0.121.0 | 0.137.2 | 服务框架 |
| starlette | 0.49.3 | 1.3.1 | 服务框架传递依赖，这次显式钉住 |
| pypdf | 5.9.0 | 6.21.4 | 隔离子进程里的 PDF 提取 |
| python-multipart | 0.0.20 | 0.0.31 | 上传解析 |
| pytest | 9.0.1 | 9.0.3 | 测试工具，但仍写在同一份 requirements 里 |

其余直接钉死版本保持不动：uvicorn 0.38.0、argon2-cffi 25.1.0、httpx 0.28.1、jieba 0.42.1、python-docx 1.2.0、lxml 6.1.3、typing-extensions 4.16.0、ruff 0.14.5。

本机 Python 是 3.12.3。候选的 `Requires-Python` 都允许它：fastapi 0.137.2 和 starlette 1.3.1、python-multipart 0.0.31、pytest 9.0.3 是 `>=3.10`，pypdf 6.21.4 是 `>=3.9`。这些都来自 2026-11-23 读取的 PyPI JSON：`https://pypi.org/pypi/<包>/<版本>/json`。四个候选版本都存在，都没有被 yanked。

## 2. 为什么是这一组，而不是现状或最新版

已安装 fastapi 0.121.0 的核心依赖是 `starlette<0.50.0,>=0.40.0`。同一天读到的后续发布里，这个上界是这样变的：

- 0.121.3 到 0.128.0：`starlette<0.51.0,>=0.40.0`
- 0.129.0 到 0.132.1：`starlette<1.0.0,>=0.40.0`
- 0.133.0：去掉上界，写成 `starlette>=0.40.0`
- 0.134.0 起：`starlette>=0.46.0`
- 0.137.2：`starlette>=0.46.0`，另外 `pydantic>=2.9.0`，`Requires-Python >=3.10`
- 0.164.0 和 0.165.0：`starlette>=1.6.0`

官方变更记录在 FastAPI 0.165.0 的 `docs/en/docs/release-notes.md`（`https://raw.githubusercontent.com/fastapi/fastapi/0.165.0/docs/en/docs/release-notes.md`）：

- 0.133.0（2026-02-24）写明「Add support for Starlette 1.0.0+」，对应 PR 14987。
- 0.137.2（2026-06-18）的内部记录写明测试依赖从 starlette 1.2.1 升到 1.3.1，PR 15780。

starlette 1.3.1 的发布说明（`https://raw.githubusercontent.com/encode/starlette/1.3.1/docs/release-notes.md`）把这次扫描里的五条修复落在这些版本上：1.0.1 处理畸形 Host，1.1.0 限制 HTTPEndpoint 只分发标准方法并拒绝 StaticFiles 绝对路径，1.3.0 用结构化部件重建 `request.url`，1.3.1 让表单解析器执行 `max_fields` 和 `max_part_size`。所以 1.3.1 是能同时盖住这五条的最低发布版。

0.133.0 的元数据已经允许 1.3.1，但它的发布日早于 starlette 1.0.0（2026-03-22）。0.137.2 是变更记录里已经写到自己用上 starlette 1.3.1 的版本，元数据又允许把它钉在 1.3.1。因此候选用 0.137.2，而不是停在「还没研究新 FastAPI」。

更新的 fastapi 0.165.0、starlette 1.10.0、pypdf 7.1.1、python-multipart 0.0.34、pytest 9.2.0 都在 PyPI 上。它们不是这一组。这一组只求盖住已有扫描，不把「更新」说成「以后也不会再有记录」。

## 3. 解析差异

用审计环境里的 pip 26.3 做了两次 `--dry-run --ignore-installed`，目标目录是空的 `/tmp/depsec-inv/empty`，结束后里面没有文件。没有装进 `/tmp/zhixu-py`，也没有改审计环境里已装的业务包。

- 修前：`pip install --dry-run -r server/requirements.txt`，退出码 0。解析出 31 个包，starlette 被 fastapi 0.121.0 的上界钉在 0.49.3。
- 修后：同样方式装上第 1 节的候选和其余未改的直接依赖，退出码 0。仍是 31 个包。

两边清单在 `docs/delivery/scans/before-resolve-slim.json` 和 `docs/delivery/scans/after-resolve-slim.json`。版本不同的只有这五个：fastapi、starlette、pypdf、python-multipart、pytest。pydantic 仍解析到 2.14.4，因为它满足 0.137.2 的 `pydantic>=2.9.0`。没有新的 opentelemetry 依赖；那是更后面的 0.165.0 才写进核心依赖的。

## 4. 公告是打开核对的

80 条扫描编号都请求了 `https://api.osv.dev/v1/vulns/<编号>`，80 次都是 HTTP 200，正文是 OSV JSON。整理结果在 `docs/delivery/scans/coverage-summary.json`。

另外实际请求了页面，结果在 `docs/delivery/scans/link-checks.json`：

- 80 个 GitHub Advisory 页面都是 HTTP 200，正文里看得到对应的 GHSA 编号。
- 以 PYSEC 编号打开的 osv.dev 页面是 HTTP 200，正文里看得到该编号。
- NVD 的 80 个地址返回 HTTP 200，但正文是标题为 “NVD - Home” 的站点壳，里面没有 CVE 编号。所以 NVD 没有当作公告正文。
- `X41-2026-002` 没有标准公告站路径。它是 PYSEC-2026-161 的别名，这条的 OSV 记录已打开。该记录没有 `severity` 字段。

其余 79 条 OSV 记录带有 `severity`，类型是 CVSS_V3 或 CVSS_V4，向量写在覆盖文件里。这里不把向量换算成高、中、低，也不凭向量宣布产品风险等级。

覆盖结论：

- 48 条带包名的 pypdf 记录，6.21.4 落在 OSV 的 `fixed` 事件之后，不再落在受影响区间。
- 另外 19 条 pypdf 的 CVE 记录没有 `package.name`，受影响范围在 GIT 事件和 `versions` 列表里。5.9.0 在受影响版本列表中，6.21.4 不在。提取出的修复版本都不高于 6.21.4，其中三条的修复标记就是 6.21.4。
- python-multipart 7 条、starlette 5 条、pytest 1 条，候选版本都落在各自 `fixed` 事件上或之后，OSV 判定不再受影响。
- 没有一条在候选版本上仍被判为受影响。这只覆盖这次已有扫描的 80 个编号，没有对候选组合重跑 pip-audit。

## 5. 适用在哪，不在哪

不把隔离或「代码里没写到」写成漏洞消失。

- starlette 和 fastapi 在服务进程里处理 HTTP、会话和 SSE。Host、`request.url`、表单大小限制这些修复落在这条路径上。PYSEC-2026-2280 的正文要求用 `HTTPEndpoint` 且注册时不写 `methods=`；本仓库服务代码没有这个类。PYSEC-2026-2281 的正文写明 POSIX 不受那个 Windows UNC 问题影响，服务代码也没有挂 StaticFiles。这两条仍随库升级一起走，不单独销掉。
- python-multipart 用在 `POST /api/files` 的 Form 和 UploadFile。0.0.22 起去掉文件名里的目录，0.0.26 和 0.0.27 限制头和前言，0.0.30 改查询串分隔和 Content-Disposition 扩展参数，0.0.31 拒绝负的 Content-Length。变更记录在 `https://github.com/Kludex/python-multipart/blob/0.0.31/CHANGELOG.md`。
- pypdf 只在无网络、非特权、限资源的子进程里调用 `PdfReader`、`is_encrypted`、`pages`、`extract_text`。6.0.0 的变更记录写了停止支持 Python 3.8，并清理已废弃接口；本机是 3.12。隔离仍然只是缓解，不是这 67 条记录的修复。
- pytest 9.0.3 的变更记录写明修了不安全的临时目录，对应 CVE-2025-71176（`https://github.com/pytest-dev/pytest/blob/9.0.3/doc/en/changelog.rst`）。服务包没有 import pytest。可是它和运行库在同一份 `requirements.txt` 里，按这份文件安装会把它装进同一环境。临时目录问题发生在测试运行器，不在请求路径上。

PYSEC-2026-161 没有严重度字段，不补。

## 6. 已知的兼容变化

这些是发布说明里写了、但本轮没有跑升级后测试的变化：

- FastAPI 0.132.0 起，JSON 请求默认要带合法的 `Content-Type`，例如 `application/json`，否则拒绝。关闭方式是 `strict_content_type=False`。候选包含这个行为。不能为了兼容去关它。
- FastAPI 0.134.0 把 starlette 下界抬到 0.46.0，说明是为了从异常组里重新抛出异常，并增加了流式 JSON 行。0.135.0 的说明新增了 SSE 辅助能力。现有 SSE 仍走现在的流式响应，升级后要再对一遍重连。
- Starlette 1.0 删掉了 `on_event`、`add_event_handler`、`@app.route` 等旧接口，改用 lifespan 和显式路由。本仓库服务代码没有这些名字。FastAPI 在更早的说明里写过为下一代 Starlette 重新实现 `on_event`。这不能代替升级后的登录、上传、取消和 SSE 回归。
- pypdf 6.21.4 仍提供现在用的 `PdfReader` 和 `extract_text`。6.0 清理过废弃接口。子进程导入失败时现在的代码会失败关闭，这个行为要保持。
- python-multipart 0.0.31 会拒绝一部分以前可能收下的畸形头、负长度和带目录的文件名。正常的小文件上传要仍能通过，超限仍要拒绝。

## 7. 若 PM 选定这组，再做的回归和复询

本轮不做。选定并真正改依赖之后：

1. 写操作仍同时检查登录会话、Origin 和 CSRF。生产 Secure Cookie 的含义不变。别人的资源和 SSE 仍按拥有者拒绝。
2. JSON 请求在新的 Content-Type 检查下仍能登录和发消息。不把 `strict_content_type` 关掉。
3. 上传的类型和大小限制仍在。正常文件能进解析队列。畸形 multipart 失败时不改到主进程提取。
4. PDF 和 DOCX 仍只在隔离子进程里导入。隔离不可用就失败关闭。现有中文 PDF 样例仍要抽出汉字和数字。
5. 取消仍按 `43b0fc3` 的路径：等第一条增量，连续取消两次，再发。夹具通过不是真实 Qwen 取消。
6. 用同一套 pip-audit 2.10.1 和 OSV，对升级后的安装集再查一次，交完整 JSON。写明这 80 个编号是否消失，以及有没有新编号。复询没有记录，也不等于安全准出。
7. pytest 若仍和生产依赖写在一起，安装清单要单独说明。更好的做法是拆出测试依赖，但那不是这次调查已经做的事。

## 8. 本轮没有做

- 没有升级、强行钉到元数据不允许的版本、关闭校验，也没有改库的职责、权限、存储或隔离。
- 没有把这组候选写成已获准。
- 没有重跑 pip-audit。覆盖判断来自已有扫描编号和这次打开的 OSV 记录。
- 没有把 NVD 壳页面当作公告正文。
- 没有把现状 fastapi 0.121.0 加 starlette 0.49.3 当作修复候选。
