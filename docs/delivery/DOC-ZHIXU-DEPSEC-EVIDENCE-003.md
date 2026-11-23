# 依赖候选的受控安装与复扫

这是 ARCH 闸门 `DOC-ZHIXU-ARCH-DEPSEC-001` v0.2 之后的实施记录。闸门把 fastapi 0.137.2、starlette 1.3.1、pypdf 6.21.4、python-multipart 0.0.31、pytest 9.0.3 定为同范围普通安全修复，不因主版本另开变更请求。本记录不是安全准出，不是独立验收，也没有合并或上线。

页面失败关闭的提交是 `b7cbfa0f3a5fbf556d5369e70109fac509a75ecd`。依赖变更是其后的另一笔，不能把取消缺陷的独立通过从 `43b0fc3f5db7f1923e1c9b7bf3a4182ad08d0c1c` 说成新提交已经独立通过。progress 在 C 与该取消提交上已由独立测试看到 100 和 `job_id`，这次没有再改。

## 解释器

本机实际运行的是 Python 3.12.3。候选要求 fastapi、starlette、python-multipart、pytest 为 `>=3.10`，pypdf 为 `>=3.9`，3.12.3 满足。仓库里的启动说明没有另外写死一个更低的解释器。这次没有看到另一台已部署机器的解释器，所以不能替生产环境声明版本，只能记录这台实施机器。

## 安装集

生产运行集是 `server/requirements.txt`。测试工具改到 `server/requirements-dev.txt`，先包含生产集，再加 pytest 9.0.3 和 ruff 0.14.5。starlette 在 fastapi 允许的 `>=0.46.0` 内钉死为 1.3.1。其余原来直接钉死的包版本不变。

隔离目录安装，没有改到业务正在使用的旧目录：

- 生产：`/tmp/zhixu-prod-site`，冻结清单 `server/requirements-prod.lock`，25 个包。pytest 和 ruff 不在里面。
- 测试：`/tmp/zhixu-dev-site`，冻结清单 `server/requirements-dev.lock`，31 个包。

先前 dry-run 的组合树也是 31 个包，版本与这次测试树一致（只是冻结文件把 `pydantic_core`、`typing_extensions` 写成下划线，dry-run 用了连字符）。生产树比那 31 个少 6 个，都是测试侧才需要的：pytest、ruff、iniconfig、packaging、pluggy、Pygments。不是解析失败，也不是少装了运行库。

这次导入到的版本是 fastapi 0.137.2、starlette 1.3.1、pypdf 6.21.4、pytest 9.0.3。没有把 `strict_content_type` 关掉，没有放宽表单字段数或单段大小，没有把解析改回主进程，也没有改 CSRF、Origin、Cookie、Argon2id 或所有者校验。测试客户端出现了 Starlette 关于改用 httpx2 的弃用提示。运行库仍是已批的 httpx 0.28.1，没有为此换库。

## 19 条 pypdf CVE 的映射

证据 002 说过 80 条都已覆盖。其中 19 条没有包版本上的 `fixed` 事件，只有 git 提交。不能因为受影响版本列表里没有 6.21.4，就说这 19 条已被该版本修好。

这次的核对方法是：从当时打开的 OSV 正文取出 `fixed` 里的 40 位提交，共 23 个不重复提交；向 GitHub 比较接口请求 `提交...6.21.4`。附注标签 `6.21.4` 的对象是 `9597d20512390bea3cbc98c6f148fbdda37b0d96`，剥开后的提交是 `b2c3fa2ee689f582a0de256a45e30bd96c68f807`。23 个提交的比较结果都是 `ahead` 或 `identical`，且 `behind_by` 为 0，也就是这些修复提交都在该标签的历史上。19 条各自的每个 git 修复提交都如此。明细在 `docs/delivery/scans/pypdf-6.21.4-git-fixed-map.json`。

这是标签包含关系，不是“列表里没有就算修好”，也不能代替下面的已安装树复扫。

## 已安装树复扫

工具是 pip-audit 2.10.1，服务是 OSV，目标是上面两个已经安装的目录，不是空的 requirements 列表，也不是 dry-run，也不是 PyPI 页面上的空漏洞数组。

| 树 | 清单条数 | 退出码 | 带公告的包 |
| --- | --- | --- | --- |
| 生产 25 包 | `docs/delivery/scans/pip-audit-prod-installed.json` | 0 | 0 |
| 测试 31 包 | `docs/delivery/scans/pip-audit-dev-installed.json` | 0 | 0 |

两份 JSON 的 `dependencies` 条数与冻结清单一致，漏洞数组是空的。这表示这次查询没有返回仍影响这些已装版本的记录。它不是“以后没有漏洞”，也不是安全准出。以前对空依赖列表得到退出码 0 的扫描仍然无效，这次没有用那种结果。

## 开发回归

在测试安装集上跑了现有套件：pytest 38 项通过，ruff 通过，node 8 项通过。其中包含会话与 CSRF/Origin、缺少 Content-Type 的 JSON 被拒绝（422）而带 `application/json` 的错误口令仍是 401、中文 PDF/DOCX 与隔离、SSE 重连、取消与删除竞态、progress、以及 `43b0fc3` 的取消回归。

这些是开发自测。独立测试对取消的通过只关闭 `43b0fc3`。不能在这一笔新提交上写成独立通过。TEST 对 C 期仍是阻塞。真实 Qwen 仍未联调。
