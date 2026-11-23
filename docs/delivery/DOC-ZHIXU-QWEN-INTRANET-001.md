# 真实 Qwen 内网验收包

本云端连不到用户内网，这份材料只交给内网执行。这里没有启动服务，没有连接模型，也没有用协议夹具冒充真实结果。不合并，不上线，不改权限和依赖栈。

## 沿用的服务端配置

批准附件里的内网服务是 `http://192.168.2.46:9938/v1`，模型名是 `Qwen3.8-27B`。运行代码没有这两项默认值。验收时由操作者导出环境变量，不要写进 Python、页面或浏览器。

不假设该服务需要 API key。`ZHIXU_MODEL_API_KEY` 留空即可。如果现场后来确有密钥，只放在环境里，脚本不打印、不写入证据。

## 开始前要具备的条件

- Python 版本不低于 3.10。本仓库自测用过 3.12.3，内网可以更高，但不要低于 3.10。
- 用 `server/requirements-prod.lock` 安装产品包。测试工具不要装进这个运行目录。
- 解析需要 `bwrap`。没有它时上传会失败，不能改到主进程解析。
- `ZHIXU_DATA_DIR` 指向只有这个服务能读写的私有目录。里面会有数据库、上传对象和日志。
- 浏览器打开的来源必须写进 `ZHIXU_ALLOWED_ORIGINS`。服务和浏览器不在本机、或者使用 HTTPS 时，设置 `ZHIXU_COOKIE_SECURE=1`。
- 运行这台服务的机器要能访问上面的模型地址。本验收脚本默认只监听 `127.0.0.1`，不新建隧道，也不对公网开放。

## 怎么执行

先只做条件检查，这一步不连接模型：

```bash
python3 docs/delivery/evidence/qwen_intranet_accept.py check
```

内网真正验收时再导出变量并运行 `accept`。下面的地址就是上面的既有服务，由操作者自己导出：

```bash
export ZHIXU_MODEL_BASE_URL='http://192.168.2.46:9938/v1'
export ZHIXU_MODEL_NAME='Qwen3.8-27B'
export ZHIXU_MODEL_API_KEY=
export ZHIXU_UPSTREAM_MODE=live
export ZHIXU_ALLOWED_ORIGINS='http://127.0.0.1:8000'
python3 docs/delivery/evidence/qwen_intranet_accept.py accept
```

`accept` 会安装到临时目录、在本机端口启动、用两个临时账号做注册、上传一份自带的非秘密样本、看流式事件的终态、取消一次、删除样本文件后再问一次，然后停止服务。证据只留版本、状态码、事件名、终态，以及样本标记是否出现在日志里。不保存回答正文、口令和密钥。

停止就是脚本结束时关掉它启动的进程。不要用这份脚本改系统服务或已有数据目录。

## 仍不能在云端勾掉的项

真实流式、引用是否在语义上成立、真实上游取消、删除后的占位句和 SSE 终态，都要等内网跑完 `accept` 才算看到。云端这次只跑了 `check`，结果是待内网执行。
