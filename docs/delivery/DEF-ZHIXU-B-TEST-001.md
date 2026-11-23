# DEF-ZHIXU-B-TEST-001 页面脚本与登录失败关闭

修复在当前分支上，不改固定 A、固定 B、C 期回归和取消修复 `43b0fc3f5db7f1923e1c9b7bf3a4182ad08d0c1c`。依赖版本在这一提交里还不升级。没有合并，也没有上线。开发自测不是独立验收。

## 来源要分开

TEST 证据和 DEV 后来补的复核不是同一件事。附件里较早把“口令会进地址栏”写成因果说明的句子，不能覆盖下面这条边界。

### TEST 已经证实的

供测 SHA 是 `7e6ad8a6d37009d545316091ea2eb751e6427458`。下列文件是 PM 转来的脱敏包，本岗没有改这些原文，也没有尝试还原查询串。

| 文件 | SHA256 | 能证明的 |
| --- | --- | --- |
| `browser-modules.json` | `e163526308f12343a6a5b3a303475363b6b0cca97042690ae71d96648f7f6200` | `/app.js`、`/input_rules.js`、`/stream_state.js` 为 200；`/markdown.js`、`/templates.js`、`/upload_rules.js` 为 404。`/api/auth/me` 为 200，`#app` 仍 hidden |
| `B-012.json` | `65ce27717a3cf98b0897a2682cde8307ac5392e04529cd092dc86a99abc78359` | 同上三份 404。排版没有走到，复制没有走到 |
| `B-015.json` | `c2552d7cc0d3fe0f8f0d3e82931ef3eb1ef65442e8e6b472f3dc5f21ecb630c1` | 已登录后主界面没有按脚本收起模板按钮 |
| `browser.json` | `eb3676cbdabcf765b82286ca68f47b63c7209c43b35aa84fea3b319cb3da1eb4` | 四枚模板按钮 `disabled` 都是 false。`history` 是空数组，不是地址栏记录 |
| `server-follow2.log` | `a2488003ffc8b2ea8ae6c0346b44f9bf5865fb815827aadcb1125679c93b57c4` | 约第 63–67 行三个脚本 404；约第 90 行是 `GET /?[REDACTED] HTTP/1.1` 200，随后再次 404 这三个脚本 |

这些响应的 MIME / Content-Type，TEST 没有采集。包里没有首页 HTML，所以不能从 TEST 证据读出 `<form method>`。没有地址栏截图。查询串已被换成 `[REDACTED]`，不能独立还原，也不需要恢复。

因此：TEST 证明了三个模块 404、三份已挂上的脚本 200、登录接口 200 但主界面仍隐藏，以及访问日志里有一条脱敏后的带查询串 GET。**“凭据进入 URL”在 TEST 证据上仍是风险和假设，不是已证实的泄露。** 不能根据这条脱敏 GET 断言口令已经进了地址或日志。范围是本机临时实例，不能写成生产泄露，也不能写成生产没有影响。这次没有看到生产访问日志。

### DEV 新增复核

来源是本机对已提交树 `bfb7b84f99b4f4ea55d3ac579d8223960e9a77a8` 和工作区修复的再次请求，不是 TEST 包里的文件。使用的值是公开标记 `NOSSECRET-MARKER`，不是口令。

修前 HTTP（`docs/delivery/scans/btest001-dev-before-http.json`）：

- 服务返回的登录表单标签是 `<form class="auth-card" id="auth-form">`。`method` 属性没有写，`action` 属性没有写。用户名和密码输入框有 `name`。
- 按成功控件规则用该标记提交后，请求目标里有这个标记，访问日志里也有，并且是带查询串的 GET，状态 200。
- 这只说明：当时这份 HTML 的缺省提交会把有 `name` 的字段放进查询串。它不把 TEST 已抹掉的查询内容恢复成口令。
- DEV 这次记下的内容类型：页面和已挂上的脚本是 `text/html`、`text/css`、`text/javascript`；三个 404 和 `copy_feedback.js` 的 404 是 `application/json`。TEST 没有这些类型。
- `copy_feedback.js` 404 是 DEV 在同一棵树上多看到的。`app.js` 第一个导入就是它。TEST 点名的是另外三个，没有把这一份写进那三份 JSON。

修前浏览器（`docs/delivery/scans/btest001-dev-before-browser.json`）是本机 Google Chrome headless。正常、阻断 `.js`、禁用全部脚本三种情况下，点击登录按钮后地址查询串和后续 GET `/` 都带有这个公开标记。Chrome 看到的脚本类型与上面的 HTTP 内容类型一致：200 的是 `text/javascript`，404 的是 `application/json`。这是无界面自动操作，不是地址栏截图。

## 修后

页面会请求的文件放进白名单，并写明内容类型。缺文件就拒绝启动。测试脚本和 `package.json` 不公开。

登录表单写成 `method="post"`、`action="/"`。输入框去掉 `name`。登录和注册默认禁用，只有整页模块执行完才放开。脚本没加载或浏览器不运行脚本时，按钮保持关闭。

修后 HTTP（`docs/delivery/scans/btest001-dev-after-http.json`）：表单属性就是 `method="post"`、`action="/"`。十个页面资源都是 200，内容类型分别为 html、css、javascript。用同一公开标记按成功控件提交时，没有带 name 的控件，请求目标和访问日志都没有这个标记，也没有 `GET /?`。

修后浏览器（`docs/delivery/scans/btest001-dev-after-browser.json`）：

- 正常：按钮放开。登录和注册走 `POST /api/auth/login` 与 `POST /api/auth/register`。标记出现在 JSON 正文，不在查询串。访问日志没有这个标记。地址保持 `/`。
- 阻断 `.js`：按钮保持禁用，提示脚本没有加载。点击和回车后没有新请求。
- 禁用全部脚本：按钮保持禁用。点击和回车后没有新请求，查询串里没有标记。

`server/tests/test_page_delivery.py` 会再查白名单、内容类型、表单属性和标记不进入访问日志。这仍是开发自测。独立 TEST 还没有复验。真实 Qwen 仍未联调。

## 复现时不要带回口令

1. 用修复提交启动，只监听 `127.0.0.1`，不要配置模型。
2. 看 `/` 的 HTML 里登录表单的 `method` 和 `action`，以及每个页面脚本的状态和 Content-Type。
3. 若要看失败关闭，字段里只填公开标记，不要填真实口令。修复后的地址和访问日志不应出现该标记。
4. 回传前不要附上含口令的地址。不要清理真实用户日志，也不要重置真实账号。
