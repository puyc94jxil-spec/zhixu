# 知序（zhixu）

这是 A 期可运行的问答与文档工作台。根目录原来的 `index.html`、`styles.css`、`app.js`、`output/`、`使用说明.md`、`验证记录.md`、`需求文档.md` 和 `docs/plans/` 保持原样，只作对照。A 期业务界面在 `web/`，由服务端一起提供，不是上线或对外发布入口。

本说明对应的实现只完成获批范围里的 A 期纵切。它不是完整 P0，也不是测试签收或上线版本。

## 这次实现依据什么

- 批准登记：`AUD-ZHIXU-APPR-REC-001`。用户原话批准的是附件 `APPR-ZHIXU-001` `v0.2-draft` 的完整 P0 范围、技术方案和安全默认，按三期推进，不合并、不上线。
- 范围基线：`BL-ZHIXU-REQ-001`。设计基线：`BL-ZHIXU-DES-001`。这两条只说明批准了什么范围和方案，不是代码基线、测试基线或发布基线。
- 批准对象快照（字节未改，文头仍保留当时的「候选未批准」字样）：`docs/constraints/APPR-ZHIXU-001-v0.2-draft.md`。
- 契约草稿 `docs/constraints/DOC-ZHIXU-IMPL-CONTRACT-001-v0.1-draft.md` 只是方案内的细化，不是新的批准或测试通过。
- 测试计划 `DOC-ZHIXU-TEST-PLAN-001` 与用例 `DOC-ZHIXU-TEST-CASES-001` 均为 `v0.1-draft`，未审定、未执行。仓库里的自测不能代替它们。

独立接手步骤、命令和未验证项写在 `docs/delivery/PHASE-A-HANDOFF.md`。与契约不一致的地方写在 `docs/delivery/DEVIATIONS.md`。

## 现在能做什么

以下为 A 期设计与 DEV 已运行的自测范围，供接手和对照。独立 TEST 尚未签收。不能把这一节当成行为验收、安全验收、模型联调或上线已经通过。

在供测 SHA 的自测里，DEV 实际跑过这些路径：

1. 注册并登录。登录后只能看到自己的会话和文件。
2. 新建会话，输入中文问题，看到服务端逐段返回的回答。
3. 上传 `.txt` 或 `.md`。服务会在隔离环境里读出文字，再按问题检索，并给出能定位到段落和偏移的引用。
4. 停止正在生成的回答。已经写出的半句会保留，状态是停止，不会改写成完成。
5. 删除自己的文件或会话。删除进行中的依据文件后，未完成的回答会撤回，已删除文件的旧回答不会再把原文送回模型。

还不能做、也不要当成已经做好的事：PDF 和 Word、完整删除种类、意见反馈、账号注销、30 天备份清除、回答排版消毒、超长上下文的正式摘要，以及真实模型质量验收。这些留在 B 期或 C 期。

## 怎么启动

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

重置、备份和夹具账号命令见接手说明。30 天自动清除备份尚未实现。恢复只能由运维命令做到新目录，没有用户自己点的恢复按钮。
