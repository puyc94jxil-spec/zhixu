# 知序（zhixu）

这是按已批准 P0 分期做出的问答与文档工作台。根目录原来的 `index.html`、`styles.css`、`app.js`、`output/`、`使用说明.md`、`验证记录.md`、`需求文档.md` 和 `docs/plans/` 保持原样，只作对照。业务界面在 `web/`，由服务端一起提供，不是上线或对外发布入口。

A 期供测基准固定为 `bc0698bc571f9b859eb28e46aa88058c75ded77d`，不因后面的提交改变。文档措辞修正是 `5ddbc5827741b49802f5bc2df302874537109f6d`。B 期快照另见 `docs/delivery/PHASE-B-HANDOFF.md`。这些都不是测试签收或上线版本。

## 这次实现依据什么

- 批准登记：`AUD-ZHIXU-APPR-REC-001`。用户原话批准的是附件 `APPR-ZHIXU-001` `v0.2-draft` 的完整 P0 范围、技术方案和安全默认，按三期推进，不合并、不上线。
- 范围基线：`BL-ZHIXU-REQ-001`。设计基线：`BL-ZHIXU-DES-001`。这两条只说明批准了什么范围和方案，不是代码基线、测试基线或发布基线。
- 批准对象快照（字节未改，文头仍保留当时的「候选未批准」字样）：`docs/constraints/APPR-ZHIXU-001-v0.2-draft.md`。
- 契约草稿 `docs/constraints/DOC-ZHIXU-IMPL-CONTRACT-001-v0.1-draft.md` 只是方案内的细化，不是新的批准或测试通过。
- 测试计划 `DOC-ZHIXU-TEST-PLAN-001` 与用例 `DOC-ZHIXU-TEST-CASES-001` 均为 `v0.1-draft`，未审定、未执行。仓库里的自测不能代替它们。

A 期接手步骤在 `docs/delivery/PHASE-A-HANDOFF.md`。B 期接手步骤在 `docs/delivery/PHASE-B-HANDOFF.md`。C 期开发侧回归在 `docs/delivery/PHASE-C-DEV-VERIFICATION.md`。与契约不一致的地方仍写在 `docs/delivery/DEVIATIONS.md`，没有为了措辞把差异删掉。C 期开发回归完成不是独立验收，也不是上线批准。其后对 DEF-ZHIXU-A-TEST-001 的取消修复也不替换固定 A、固定 B 和 C 期回归的提交，夹具通过不是真实模型取消。

## 现在能做什么

以下为 A 期设计与 DEV 已运行的自测范围，供接手和对照。独立 TEST 尚未签收。不能把这一节当成行为验收、安全验收、模型联调或上线已经通过。

在供测 SHA 的自测里，DEV 实际跑过这些路径：

1. 注册并登录。登录后只能看到自己的会话和文件。
2. 新建会话，输入中文问题，看到服务端逐段返回的回答。
3. 上传 `.txt` 或 `.md`。服务会在隔离环境里读出文字，再按问题检索，并给出能定位到段落和偏移的引用。
4. 停止正在生成的回答。已经写出的半句会保留，状态是停止，不会改写成完成。
5. 删除自己的文件或会话。删除进行中的依据文件后，未完成的回答会撤回，已删除文件的旧回答不会再把原文送回模型。

上面 5 条对应 A 期供测 SHA 上 DEV 已经跑过的自测。后来的 B 期又在同一分支补了 PDF/DOCX、反馈、账号在线删除、标题搜索、安全排版、可追踪摘要和 30 天备份清除，并另有一轮 DEV 自测。细节和命令以 B 期接手说明为准。独立 TEST 对 A、B 都还没有签收。

仍然不能当成已经验收的事：真实模型连通和质量、引用是否在语义上站得住、真实上游取消、浏览器点击，以及独立 TEST 的安全签收。C 期开发自测里已经用可提取文字的中文 PDF 跑过解析，这不是中文质量验收。没有用户自己点的恢复按钮。

## 常规（非夹具）启动

需要 Python 3.12。本机自测使用的是 Python 3.12.3、SQLite 3.45.1。解析隔离还需要 `bwrap`（本机 0.9.0）和 `newuidmap`。没有这两样时，上传解析会直接失败，不会改在主进程里偷偷解析。

```bash
python3 -m pip install -r server/requirements.txt
cd server
export PYTHONPATH="$PWD"
export ZHIXU_DATA_DIR="$PWD/data"
export ZHIXU_UPSTREAM_MODE=unconfigured
python3 -m zhixu_server.main
```

浏览器打开 `http://127.0.0.1:8000/`。健康检查是 `GET /api/health`，只返回模式和「模型是否已配置」，不会访问模型，也不会写出模型地址。

上面这组启动命令只适合本机 HTTP。它默认不给 Cookie 加 Secure，来源也只允许本机两个地址。这不是生产环境可以照抄的安全配置，偏差记录也不豁免下面这些约束：

- 用 HTTPS 或放到本机以外时，必须设置 `ZHIXU_COOKIE_SECURE=1`。
- `ZHIXU_ALLOWED_ORIGINS` 必须写成用户浏览器里真正打开的来源，包含 `http` 或 `https`、主机和端口。写错或漏写，登录后的写入会被拒绝。
- 登录后的写入同时要 CSRF 令牌和 Origin。契约草稿里的「二者择一」不能拿来放宽。

要接真实模型，只通过环境变量注入，不要写进代码或前端：

- `ZHIXU_UPSTREAM_MODE=live`
- `ZHIXU_MODEL_BASE_URL`
- `ZHIXU_MODEL_NAME`
- `ZHIXU_MODEL_API_KEY`（没有密钥就留空，不要写进文件）

批准附件里记录了指定的内网服务和模型名。运行时代码没有这项默认值。本云端环境没有验证该内网是否连通，不能把未验证写成联调成功。

## 数据放在哪里

`ZHIXU_DATA_DIR` 下面有：

- `zhixu.db`：SQLite 数据库，使用 WAL。
- `objects/`：上传文件的私有对象。删除后在线目录不再保留该对象。
- `logs/zhixu.log`：JSON 日志。只记事件名、错误码和标识。密码、密钥、文档正文、提示词和引用原文不会写入。超过 200 字的字符串也会丢掉。

重置、备份、过期清除和夹具账号命令见 B 期接手说明。清除只处理带备份标记且超过 30 天的备份目录。恢复仍只给运维命令，写到新目录，没有用户自己点的恢复按钮。
