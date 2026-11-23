# 安装工具 pip 与产品锁

独立扫描里，产品生产锁 25 个包、测试锁 31 个包的已安装树退出码 0，没有公告。另有一次测试环境 `site-packages` 扫到 `pip` 24.0，6 条公告，退出码 1。`pip` 不在两份产品锁里。这次不把那 6 条算进产品漏洞，也不说整台机器已经清零。

## 本云端实际看到的边界

- 产品锁：`server/requirements-prod.lock` 25 行，`server/requirements-dev.lock` 31 行。两份都没有 `pip`。
- 隔离安装目录 `/tmp/zhixu-prod-site` 和 `/tmp/zhixu-dev-site` 的元数据里没有 `pip`。
- 运行服务的代码没有 `import pip`，也没有把用户输入交给 `pip`。解析子进程只挂解析库，清空环境，不执行安装器。上传文件是解析数据，不是安装命令。
- 本机 `python3 -m pip --version` 是 Ubuntu 的 `pip` 24.0，位置 `/usr/lib/python3/dist-packages/pip`，包名 `python3-pip 24.0+dfsg-1ubuntu1.3`。它在系统解释器的路径上，所以同一个 Python 能执行安装命令。
- 说明里的安装步骤 `python3 -m pip install -r server/requirements.txt` 会调用这个安装器。公告描述的是安装时处理压缩包、入口脚本路径和索引地址，落在这条安装命令上，不落在聊天请求上。
- 解析隔离会只读挂载 `/usr`，因此磁盘上的 `pip` 文件能被看见。子进程的 `PYTHONPATH` 只有解析包和解析库，入口是固定解析模块。没有一条请求会去运行 `pip`。

## 编号从哪来

TEST 没有附上那 6 条的编号，也没有附上他们的安装树 JSON。缺的这部分继续待证据，这里不编造他们的清单。

本云端自己向 `https://api.osv.dev/v1/query` 查询了已安装的 PyPI `pip` 24.0。返回记录按别名合并后是 6 组，写在 `docs/delivery/scans/pip-24.0-osv-query.json`。同一查询对审计虚拟环境里的 `pip` 26.3 返回 0 组。这只说明这次查询，不是“以后没有公告”，也不是 TEST 那次扫描的原件。

对整个 `/usr/lib/python3/dist-packages` 跑 `pip-audit` 时，工具在 Debian 版本号 `0.8.3ubuntu7.5` 上中断，没有留下完整 JSON。因此本岗没有复现出他们那个退出码 1 的 site-packages 原文。

## 最小修复计划

不改系统上的 `python3-pip`，也不改用户已经装好的环境。受控做法是：

1. 新建一个只用于安装的虚拟环境，把里面的 `pip` 升到不低于这次查询里最晚的修复版本 `26.2.0`。本云端审计环境已经是 26.3，查询为 0 组。
2. 用那个新 `pip`，按 `server/requirements-prod.lock` 或测试锁安装到新目录。
3. 产品目录和安装器分开再扫。产品目录仍应没有 `pip`。安装器的结果单独记录。
4. 服务启动继续用产品目录的 `PYTHONPATH`，不要把系统 `dist-packages` 里的 `pip` 当成产品依赖。

可复现检查是 `docs/delivery/evidence/check-pip-tooling.sh`。它只读取版本和锁，默认不安装、不升级系统包。`APPLY=1` 才会在 `/tmp` 里新建目录并用已有的较新 `pip` 装锁；那一步本岗没有拿去改用户环境。
