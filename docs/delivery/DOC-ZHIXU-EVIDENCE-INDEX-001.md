# 证据索引

这份索引只指出已经落地的文件和这次补测实际做了什么。它不改页面、依赖、A/B/C 或 `43b0fc3`。开发自测不是独立验收。C 仍 BLOCKED。真实 Qwen 未验证。没有合并，也没有上线。取消缺陷的独立通过仍然只属于 `43b0fc3f5db7f1923e1c9b7bf3a4182ad08d0c1c`。

## 测在哪一笔

- 修前 HTTP 跑在页面修复的上一笔 `bfb7b84f99b4f4ea55d3ac579d8223960e9a77a8`。那不是 `b7cbfa0`，也不是 `6265ee4`。
- 这次修后 HTTP 和浏览器跑在 `6265ee4972e1c1579f15db674fdf71311e4170ee`。当时 `git diff b7cbfa0f3a5fbf556d5369e70109fac509a75ecd HEAD -- web server/zhixu_server/api.py` 没有文件差异，页面交付文件与 `b7cbfa0` 相同。动作本身是在 `6265ee4` 上执行的。
- `docs/delivery/scans/btest001-dev-after-browser.json` 是更早的工作区记录。它没有 `#app` 是否去掉 `hidden`，也没有 `requestSubmit` / `form.submit`。不能用它代替下面这次。

## 三个模块的真实 HTTP

修前，`markdown.js`、`templates.js`、`upload_rules.js` 都是 **404**，`Content-Type` 为 `application/json`。同一次里 `app.js`、`input_rules.js`、`stream_state.js` 是 200，`text/javascript; charset=utf-8`。

修后，这三个模块都是 **200**，响应头 `Content-Type` 为 `text/javascript; charset=utf-8`。浏览器网络记录里的 MIME 是 `text/javascript`，不带 charset。两处都写在结果里，没有混成同一个字段。

| 结果 | 路径 | SHA256 |
| --- | --- | --- |
| 修前 HTTP | `docs/delivery/scans/page-before-bfb7b84-http.json` | `5f969d5bae82fe2472ad96ba1446a750ca4a214e3f2863143815911cb7afab75` |
| 修后 HTTP 与浏览器 | `docs/delivery/scans/page-recheck-6265ee4.json` | `a468edf38a29f56f1d6aa2453129e6507f3a4665dcacf895d74da8ca04264813` |
| 访问日志 | `docs/delivery/scans/page-recheck-6265ee4-access.log` | `09572e2443c2cf6671814797687a4d9b8d41b55ab2916975baa4f7f52f07ee9c` |

脚本：`docs/delivery/evidence/check-page-fail-closed.mjs`。公开标记是 `NOSSECRET-MARKER`。结果里没有口令，也没有带口令的网址。

## 浏览器实际做了什么

工具是本机 Google Chrome `157.0.8103.50`（`google-chrome --version`）。启动参数含 `--headless=new`。调试协议回报 `Chrome/157.0.8103.50`，协议 1.3；用户代理字符串写成 `HeadlessChrome/157.0.0.0`。Node `v22.23.4` 只负责连接调试端口，没有用 Node 代替页面。没有人看着窗口点击。

正常加载：三个模块在浏览器里是 200 `text/javascript`。登录按钮变为可用。鼠标点击登录后接口返回 401，再点击注册返回 201。随后 `#app` 的 class 是 `app`，`appHidden` 为 false。标记出现在登录和注册的 JSON 请求体里，没有出现在网址查询串。访问日志的请求行也没有标记。

禁用 JavaScript 使用 `--blink-settings=scriptEnabled=false`。阻断模块是调试协议把 `.js` 请求失败掉。两种情况分开记录：

- 鼠标点击登录按钮：之后 0 个请求。登录按钮仍禁用。`#app` 仍带 `hidden`。标记不在网址。
- 在密码框按 Enter：之后 0 个请求。其余同上。
- `requestSubmit()`：调试协议在页面里调用，返回 `called`。浏览器发出一次 `POST /`，查询串和正文都没有标记，服务返回 405。页面因此离开，`#app` 读不到，结果是 null。这不是“没有导航”。
- `form.submit()`：同样是一次 `POST /`，标记不在查询串、正文和访问日志，服务返回 405。

访问日志在写入仓库前已确认整份日志不含该标记（`markerInAccessLog` 为 false）。保存的日志把标记和用户名位置做成可替换文本；这次请求行里本来就没有标记。日志没有被清空。

## 已安装扫描、冻结清单和 23 个修复提交

这些文件在 `6265ee4` 里，这次索引没有重跑漏洞库，也没有改版本。

| 内容 | 路径 | SHA256 |
| --- | --- | --- |
| 生产已安装树扫描，25 个依赖，0 条公告，1452 字节 | `docs/delivery/scans/pip-audit-prod-installed.json` | `feec79ba4f090d04703b03c57e1b25fbca715af446cffdd313bba7b2a2a1a91a` |
| 测试已安装树扫描，31 个依赖，0 条公告，1777 字节 | `docs/delivery/scans/pip-audit-dev-installed.json` | `74bac7ef766f52ee57297a3091b287364620cc7b77afde2c817ef121e14c9197` |
| 生产 freeze，25 行 | `server/requirements-prod.lock` | `512930c9e2b6b5e2c9c7d1925769740dee4f30a1c1db2a17a8b3b2a4b17fd15e` |
| 测试 freeze，31 行 | `server/requirements-dev.lock` | `224a06fc5f4c8e824214c4d2276d7541a36e4e5f235d2d41a6edb0fe5d0e8e3a` |
| 19 条 pypdf、23 个不重复修复提交的祖先比较 | `docs/delivery/scans/pypdf-6.21.4-git-fixed-map.json` | `c914fb686a3fa634ac6dcf0945bfc03cf7008a5680c4a777d3c6cd17027691a3` |

比较来源写在 `docs/delivery/DOC-ZHIXU-DEPSEC-EVIDENCE-003.md`：从当时打开的 OSV 正文取出 `fixed` 里的提交，向 GitHub 比较接口请求 `提交...6.21.4`。23 个结果都是 `ahead` 或 `identical`，且 `behind_by` 为 0。标签对象 `9597d20512390bea3cbc98c6f148fbdda37b0d96` 剥开后是 `b2c3fa2ee689f582a0de256a45e30bd96c68f807`。这不是安全准出。空的 requirements 列表即使退出码为 0 也不是有效扫描，这次没有使用那种结果。

## 这次开发自测的完整输出

命令跑在 `6265ee4` 的代码上，输出随后放进本索引所在提交。

| 输出 | 路径 | SHA256 | 结果 |
| --- | --- | --- | --- |
| pytest | `docs/delivery/scans/pytest-6265ee4.txt` | `5d08205bbf83e99e8a80c240464fc672db933563fc7ff9e5fbdde3c288ba44d5` | 38 passed，3 warnings，26.48s |
| node --test | `docs/delivery/scans/node-test-6265ee4.txt` | `9dd5e554a8b0a0b127a80d8ce20da876f290f6cf9b79f484efbf43dbf786dbfe` | 8 pass |
| ruff check server | `docs/delivery/scans/ruff-6265ee4.txt` | `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18` | All checks passed |

这三份不是独立 TEST，也不覆盖真实 Qwen。Starlette 的 httpx 弃用警告还在，没有因此改用 httpx2。
