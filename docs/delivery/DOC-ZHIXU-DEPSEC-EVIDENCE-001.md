# 依赖安全调查证据

这是按候选闸门 `DOC-ZHIXU-ARCH-DEPSEC-001` / `RV-ZHIXU-ARCH-DEP-GATES-001` v0.1-draft 第 7 节补回的 DEV 证据。它不是升级批准，不是安全通过，不是独立验收，也不改任何已装版本。

取消修复 `43b0fc3f5db7f1923e1c9b7bf3a4182ad08d0c1c` 保持不动。固定 A `bc0698bc571f9b859eb28e46aa88058c75ded77d`、固定 B `7e6ad8a6d37009d545316091ea2eb751e6427458`、C 期回归 `f62debf71f02f889fc340a241c686accbbbc94e1` 也不改。`server/requirements.txt` 的 12 个钉死版本与这次调查开始前相同。真实 Qwen 仍未联调。

严重度：当次 JSON 的每条记录只有 `id`、`aliases`、`description`、`fix_versions`。没有 severity 或 CVSS 字段。下面不填写严重度，记为未采集。链接是用记录里已有的编号按公开站点的固定路径拼出来的，本轮没有打开这些网页，也没有再查漏洞库。

## 1. 三次查询要分开看

工具是 pip-audit 2.10.1，成功的两次走 OSV。时间以 `docs/delivery/DEPENDENCY-REVIEW.md` 已写下的为准：2026-11-23 07:01:35Z 至 07:01:47Z。本轮没有重跑。

| 哪一次 | 结果 | 原文 |
| --- | --- | --- |
| 直接对 `requirements.txt` 建临时环境 | 失败。本机没有 `ensurepip`，没有连上漏洞库，没有留下 JSON。`/tmp/pip-audit-req.json` 不存在。 | 无 |
| `--local` 已安装清单 | 24 个包，漏洞数组都是空的。这 24 个是 pip-audit 自己的依赖，不是产品依赖。默认源和 `-s osv` 两份文件字节相同。 | `docs/delivery/scans/pip-audit-local.json` |
| 审计虚拟环境里的已安装包 | 55 个包，退出码 1。含产品直接依赖、传递依赖，以及上面那 24 个审计工具包。 | `docs/delivery/scans/pip-audit-all.json` |
| 只查 12 个钉死版本，`--no-deps --disable-pip` | 12 个包，退出码 1。看不到 starlette。 | `docs/delivery/scans/pip-audit-pins.json` |

空的漏洞数组只表示这次查询没有返回记录。不能写成这些包没有漏洞。仓库里没有 lock、freeze 或 constraints 文件；下面的 freeze 是事后从仍在的虚拟环境抄出来的安装清单，不是新的锁，也没有用它重新安装。

校验和：

- `pip-audit-all.json` SHA256 `73920f77a5ad059cb560835516346dbac908f75fbe6885cdaafaa3ef73d91430`
- `pip-audit-pins.json` SHA256 `75a672bda999f240efe74ca4c047ec85c4f5d55ae24389461b4b004e9d4c3d17`
- `pip-audit-local.json` SHA256 `30306eb5d5fb2750b4c8808995e978ff9da47435af4af28cdbe3a617cd8afacf`（与当时的 `pip-audit-osv-local.json` 相同，所以只存一份）
- `fastapi-0.121.0.METADATA` SHA256 `b992972d0bc820c7c4b926aecef524f39c0349c3d071b67a0a2d7f33a6798274`

## 2. 安装边界

跑服务和开发自测时，Python 路径用的是 `/tmp/zhixu-py`。那里有 31 个发行包，清单在 `docs/delivery/scans/zhixu-py-dist-info.txt`。其中包含 pytest 和 ruff，因为它们和运行库写在同一份 `requirements.txt` 里。这里没有 pip-audit。

55 个包的环境是 `/tmp/zhixu-audit-venv`。`pip freeze --all` 在 `docs/delivery/scans/audit-venv-freeze.txt`。它等于上面 31 个，再加上审计工具 24 个。`boolean.py` 在 freeze 里写成 `boolean.py`，在扫描 JSON 里写成 `boolean-py`，是同一个 5.0。

按已安装元数据的核心依赖（不含 extra）拆开这 55 个：

- 直接钉死 12 个：fastapi 0.121.0、uvicorn 0.38.0、argon2-cffi 25.1.0、httpx 0.28.1、python-multipart 0.0.20、jieba 0.42.1、pypdf 5.9.0、python-docx 1.2.0、lxml 6.1.3、typing-extensions 4.16.0、pytest 9.0.1、ruff 0.14.5。
- 运行传递 15 个：starlette 0.49.3、pydantic 2.14.4、pydantic-core 2.50.5、annotated-types 0.8.0、annotated-doc 0.0.7、typing-inspection 0.4.5、anyio 4.16.0、h11 0.16.0、click 8.5.1、httpcore 1.0.9、certifi 2026.11.20、idna 3.20、argon2-cffi-bindings 26.2.0、cffi 2.1.1、pycparser 3.12。
- pytest 带入的 4 个：iniconfig 2.3.1、packaging 26.3、pluggy 1.7.0、pygments 2.21.0。
- 审计工具 24 个：boolean-py、cachecontrol、charset-normalizer、cyclonedx-python-lib、defusedxml、filelock、license-expression、markdown-it-py、mdurl、msgpack、packageurl-python、pip 26.3、pip-api、pip-audit 2.10.1、pip-requirements-parser、platformdirs、py-serializable、pyparsing、requests、rich 15.0.0、sortedcontainers、tomli、tomli-w、urllib3。这 24 个在 55 包扫描里漏洞数组也是空的。空数组不是无漏洞证明。

`server/zhixu_server` 的代码没有 import pytest。可是按现在的 `requirements.txt` 安装，生产环境会把 pytest 和 ruff 一起装上。所以「pytest 只影响测试」还没有被安装清单证明。本轮没有拆分这个文件。

12 个钉死版本里，这次返回了记录的是 pypdf、python-multipart、pytest。fastapi、uvicorn、argon2-cffi、httpx、jieba、python-docx、lxml、typing-extensions、ruff 在这份 12 包查询里漏洞数组为空。starlette 只出现在 55 包查询里。

## 3. 记录与链接

去重后：pypdf 原始 115 条、唯一 67 条；python-multipart 原始 14 条、唯一 7 条；pytest 原始 2 条、唯一 1 条；starlette 原始 10 条、唯一 5 条。同一编号的重复来自工具输出，不是 115 个不同的 pypdf 编号。完整字段在 `docs/delivery/scans/advisories-unique.json`，它是从 `pip-audit-all.json` 整理的，不是新查询。

工具给每条记录的 `fix_versions` 是它列出的修复版本，不是「这个版本以及之后都算修好」的证明。下面的「最低列出修复版」只是该列表里版本号最小的一项。

### pypdf 5.9.0

运行。PDF 提取。代码只在无网络、非特权、有资源上限的子进程里导入 pypdf。隔离是已有缓解，不是修复，也不是验收。

| 编号 | 别名与链接 | 工具列出的修复版本 | 描述原文 |
| --- | --- | --- | --- |
| CVE-2026-113786 | [CVE-2026-113786](https://nvd.nist.gov/vuln/detail/CVE-2026-113786); [GHSA-5hx5-vpf9-5wcv](https://github.com/advisories/GHSA-5hx5-vpf9-5wcv) | 6.21.1 | pypdf: Unvalidated JPEG image data loading |
| CVE-2026-113789 | [CVE-2026-113789](https://nvd.nist.gov/vuln/detail/CVE-2026-113789); [GHSA-6vvc-x485-93v7](https://github.com/advisories/GHSA-6vvc-x485-93v7) | 6.21.0 | pypdf: Possible long runtimes/large memory usage when retrieving form fields |
| CVE-2026-113790 | [CVE-2026-113790](https://nvd.nist.gov/vuln/detail/CVE-2026-113790); [GHSA-f54x-cmq8-qg57](https://github.com/advisories/GHSA-f54x-cmq8-qg57) | 6.21.0 | pypdf: Possible large memory usage when parsing arrays and dictionaries |
| CVE-2026-113791 | [CVE-2026-113791](https://nvd.nist.gov/vuln/detail/CVE-2026-113791); [GHSA-cgf9-327m-v77c](https://github.com/advisories/GHSA-cgf9-327m-v77c) | 6.21.0 | pypdf: Possible large memory usage when parsing content streams |
| CVE-2026-113792 | [CVE-2026-113792](https://nvd.nist.gov/vuln/detail/CVE-2026-113792); [GHSA-qfv9-64jg-mh7p](https://github.com/advisories/GHSA-qfv9-64jg-mh7p) | 6.20.1 | pypdf: Possible infinite loop in PdfWriter.find_outline_item |
| CVE-2026-113793 | [CVE-2026-113793](https://nvd.nist.gov/vuln/detail/CVE-2026-113793); [GHSA-9mx8-4j7g-633p](https://github.com/advisories/GHSA-9mx8-4j7g-633p) | 6.20.1 | pypdf: Possible infinite loop when removing tree items |
| CVE-2026-113794 | [CVE-2026-113794](https://nvd.nist.gov/vuln/detail/CVE-2026-113794); [GHSA-39mj-jf6j-2qj3](https://github.com/advisories/GHSA-39mj-jf6j-2qj3) | 6.20.0 | pypdf: Possible infinite loop when hitting EOF in standard xref table |
| CVE-2026-113795 | [CVE-2026-113795](https://nvd.nist.gov/vuln/detail/CVE-2026-113795); [GHSA-7mh2-4gg2-979f](https://github.com/advisories/GHSA-7mh2-4gg2-979f) | 6.20.0 | pypdf: Possible large memory usage for streams with multiple filters |
| CVE-2026-115572 | [CVE-2026-115572](https://nvd.nist.gov/vuln/detail/CVE-2026-115572); [GHSA-6c7f-9265-g8fw](https://github.com/advisories/GHSA-6c7f-9265-g8fw) | 6.21.2 | pypdf: Possible long runtimes for repeated references to the same missing object |
| CVE-2026-115580 | [CVE-2026-115580](https://nvd.nist.gov/vuln/detail/CVE-2026-115580); [GHSA-gmh7-3g9r-mjh5](https://github.com/advisories/GHSA-gmh7-3g9r-mjh5) | 6.21.2 | pypdf: Possible long runtimes for large xref table header limits |
| CVE-2026-115585 | [CVE-2026-115585](https://nvd.nist.gov/vuln/detail/CVE-2026-115585); [GHSA-jr96-gvgh-j3r4](https://github.com/advisories/GHSA-jr96-gvgh-j3r4) | 6.21.2 | pypdf: Possible long runtimes for repeated malformed cross-reference entries (Follow-up) |
| CVE-2026-119203 | [CVE-2026-119203](https://nvd.nist.gov/vuln/detail/CVE-2026-119203); [GHSA-5849-834g-hvw5](https://github.com/advisories/GHSA-5849-834g-hvw5) | 6.21.4 | pypdf has possible infinite loop when hitting EOF in standard xref table during trailer search |
| CVE-2026-119204 | [CVE-2026-119204](https://nvd.nist.gov/vuln/detail/CVE-2026-119204); [GHSA-cggf-277g-3q54](https://github.com/advisories/GHSA-cggf-277g-3q54) | 6.21.4 | pypdf has possible large memory usage when parsing page tree |
| CVE-2026-119205 | [CVE-2026-119205](https://nvd.nist.gov/vuln/detail/CVE-2026-119205); [GHSA-mfr5-77xh-9j7h](https://github.com/advisories/GHSA-mfr5-77xh-9j7h) | 6.21.4 | pypdf has possible infinite loop when cloning dictionaries |
| CVE-2026-119206 | [CVE-2026-119206](https://nvd.nist.gov/vuln/detail/CVE-2026-119206); [GHSA-42gh-23hr-vphw](https://github.com/advisories/GHSA-42gh-23hr-vphw) | 6.21.3 | pypdf has possible long runtimes when retrieving page labels |
| CVE-2026-119207 | [CVE-2026-119207](https://nvd.nist.gov/vuln/detail/CVE-2026-119207); [GHSA-4vqv-7265-gm2w](https://github.com/advisories/GHSA-4vqv-7265-gm2w) | 6.21.3 | pypdf has possible large memory usage for exceptions in strict mode |
| CVE-2026-119208 | [CVE-2026-119208](https://nvd.nist.gov/vuln/detail/CVE-2026-119208); [GHSA-62m5-6wh8-28x7](https://github.com/advisories/GHSA-62m5-6wh8-28x7) | 6.21.3 | pypdf has possible long runtimes/large memory usage for encrypted PDF files |
| CVE-2026-119209 | [CVE-2026-119209](https://nvd.nist.gov/vuln/detail/CVE-2026-119209); [GHSA-x3rh-gjgm-fmqc](https://github.com/advisories/GHSA-x3rh-gjgm-fmqc) | 6.21.3 | pypdf has possible large memory usage when parsing cross-reference streams |
| CVE-2026-57204 | [CVE-2026-57204](https://nvd.nist.gov/vuln/detail/CVE-2026-57204); [GHSA-jm82-fx9c-mx94](https://github.com/advisories/GHSA-jm82-fx9c-mx94) | 6.13.3 | pypdf: Missing stream length values ignore defined limits |
| PYSEC-2026-1827 | [PYSEC-2026-1827](https://osv.dev/vulnerability/PYSEC-2026-1827); [GHSA-2q4j-m29v-hq73](https://github.com/advisories/GHSA-2q4j-m29v-hq73); [CVE-2026-24688](https://nvd.nist.gov/vuln/detail/CVE-2026-24688) | 6.6.2 | pypdf has possible Infinite Loop when processing outlines/bookmarks |
| PYSEC-2026-1828 | [PYSEC-2026-1828](https://osv.dev/vulnerability/PYSEC-2026-1828); [GHSA-4f6g-68pf-7vhv](https://github.com/advisories/GHSA-4f6g-68pf-7vhv); [CVE-2026-22691](https://nvd.nist.gov/vuln/detail/CVE-2026-22691) | 6.6.0 | pypdf has possible long runtimes for malformed startxref |
| PYSEC-2026-1829 | [PYSEC-2026-1829](https://osv.dev/vulnerability/PYSEC-2026-1829); [GHSA-4xc4-762w-m6cg](https://github.com/advisories/GHSA-4xc4-762w-m6cg); [CVE-2026-22690](https://nvd.nist.gov/vuln/detail/CVE-2026-22690) | 6.6.0 | pypdf has possible long runtimes for missing /Root object with large /Size values |
| PYSEC-2026-1830 | [PYSEC-2026-1830](https://osv.dev/vulnerability/PYSEC-2026-1830); [CVE-2025-55197](https://nvd.nist.gov/vuln/detail/CVE-2025-55197); [GHSA-7hfw-26vp-jp8m](https://github.com/advisories/GHSA-7hfw-26vp-jp8m) | 6.0.0 | PyPDF's Manipulated FlateDecode streams can exhaust RAM |
| PYSEC-2026-1831 | [PYSEC-2026-1831](https://osv.dev/vulnerability/PYSEC-2026-1831); [GHSA-jfx9-29x2-rv3j](https://github.com/advisories/GHSA-jfx9-29x2-rv3j); [CVE-2025-62708](https://nvd.nist.gov/vuln/detail/CVE-2025-62708) | 6.1.3 | pypdf can exhaust RAM via manipulated LZWDecode streams |
| PYSEC-2026-1832 | [PYSEC-2026-1832](https://osv.dev/vulnerability/PYSEC-2026-1832); [CVE-2025-66019](https://nvd.nist.gov/vuln/detail/CVE-2025-66019); [GHSA-m449-cwjh-6pw7](https://github.com/advisories/GHSA-m449-cwjh-6pw7) | 6.4.0 | pypdf's LZWDecode streams be manipulated to exhaust RAM |
| PYSEC-2026-1833 | [PYSEC-2026-1833](https://osv.dev/vulnerability/PYSEC-2026-1833); [CVE-2025-62707](https://nvd.nist.gov/vuln/detail/CVE-2025-62707); [GHSA-vr63-x8vc-m265](https://github.com/advisories/GHSA-vr63-x8vc-m265) | 6.1.3 | pypdf possibly loops infinitely when reading DCT inline images without EOF marker |
| PYSEC-2026-3004 | [PYSEC-2026-3004](https://osv.dev/vulnerability/PYSEC-2026-3004); [CVE-2026-48156](https://nvd.nist.gov/vuln/detail/CVE-2026-48156); [GHSA-248m-82v9-q6g6](https://github.com/advisories/GHSA-248m-82v9-q6g6) | 6.12.0 | pypdf: Possible long runtimes for zero-only width values in cross-reference streamsuntimes for zero-only width values in cross-reference streams |
| PYSEC-2026-3005 | [PYSEC-2026-3005](https://osv.dev/vulnerability/PYSEC-2026-3005); [CVE-2026-27628](https://nvd.nist.gov/vuln/detail/CVE-2026-27628); [GHSA-2rw7-x74f-jg35](https://github.com/advisories/GHSA-2rw7-x74f-jg35) | 6.7.2 | pypdf has a possible infinite loop when loading circular /Prev entries in cross-reference streams |
| PYSEC-2026-3006 | [PYSEC-2026-3006](https://osv.dev/vulnerability/PYSEC-2026-3006); [CVE-2026-40260](https://nvd.nist.gov/vuln/detail/CVE-2026-40260); [GHSA-3crg-w4f6-42mx](https://github.com/advisories/GHSA-3crg-w4f6-42mx) | 6.10.0 | pypdf: Manipulated XMP metadata entity declarations can exhaust RAM |
| PYSEC-2026-3007 | [PYSEC-2026-3007](https://osv.dev/vulnerability/PYSEC-2026-3007); [CVE-2026-41313](https://nvd.nist.gov/vuln/detail/CVE-2026-41313); [GHSA-4pxv-j86v-mhcw](https://github.com/advisories/GHSA-4pxv-j86v-mhcw) | 6.10.2 | pypdf: Possible long runtimes for wrong size values in incremental mode |
| PYSEC-2026-3009 | [PYSEC-2026-3009](https://osv.dev/vulnerability/PYSEC-2026-3009); [CVE-2026-54530](https://nvd.nist.gov/vuln/detail/CVE-2026-54530); [GHSA-52x6-gq3r-vpf4](https://github.com/advisories/GHSA-52x6-gq3r-vpf4) | 6.13.0 | pypdf: Possible infinite loop when retrieving fonts for layout-mode text extraction |
| PYSEC-2026-3010 | [PYSEC-2026-3010](https://osv.dev/vulnerability/PYSEC-2026-3010); [CVE-2026-49460](https://nvd.nist.gov/vuln/detail/CVE-2026-49460); [GHSA-5hgr-hg42-57jg](https://github.com/advisories/GHSA-5hgr-hg42-57jg) | 6.12.2 | pypdf: Inefficient decoding of FlateDecode PNG predictor streams |
| PYSEC-2026-3011 | [PYSEC-2026-3011](https://osv.dev/vulnerability/PYSEC-2026-3011); [CVE-2026-41312](https://nvd.nist.gov/vuln/detail/CVE-2026-41312); [GHSA-7gw9-cf7v-778f](https://github.com/advisories/GHSA-7gw9-cf7v-778f) | 6.10.2 | pypdf: Manipulated FlateDecode predictor parameters can exhaust RAM |
| PYSEC-2026-3012 | [PYSEC-2026-3012](https://osv.dev/vulnerability/PYSEC-2026-3012); [GHSA-87mj-5ggw-8qc3](https://github.com/advisories/GHSA-87mj-5ggw-8qc3); [CVE-2026-33699](https://nvd.nist.gov/vuln/detail/CVE-2026-33699) | 6.9.2 | pypdf: Possible infinite loop during recovery attempts in DictionaryObject.read_from_stream |
| PYSEC-2026-3013 | [PYSEC-2026-3013](https://osv.dev/vulnerability/PYSEC-2026-3013); [CVE-2026-27024](https://nvd.nist.gov/vuln/detail/CVE-2026-27024); [GHSA-996q-pr4m-cvgq](https://github.com/advisories/GHSA-996q-pr4m-cvgq) | 6.7.1 | pypdf has a possible infinite loop when processing TreeObject |
| PYSEC-2026-3014 | [PYSEC-2026-3014](https://osv.dev/vulnerability/PYSEC-2026-3014); [GHSA-9m86-7pmv-2852](https://github.com/advisories/GHSA-9m86-7pmv-2852); [CVE-2026-28804](https://nvd.nist.gov/vuln/detail/CVE-2026-28804) | 6.7.5 | pypdf vulnerable to inefficient decoding of ASCIIHexDecode streams |
| PYSEC-2026-3015 | [PYSEC-2026-3015](https://osv.dev/vulnerability/PYSEC-2026-3015); [GHSA-9mvc-8737-8j8h](https://github.com/advisories/GHSA-9mvc-8737-8j8h); [CVE-2026-27026](https://nvd.nist.gov/vuln/detail/CVE-2026-27026) | 6.7.1 | pypdf possibly has long runtimes for malformed FlateDecode streams |
| PYSEC-2026-3016 | [PYSEC-2026-3016](https://osv.dev/vulnerability/PYSEC-2026-3016); [CVE-2026-48155](https://nvd.nist.gov/vuln/detail/CVE-2026-48155); [GHSA-cj93-chg6-vgv8](https://github.com/advisories/GHSA-cj93-chg6-vgv8) | 6.12.0 | pypdf: Possible large memory usage for large offsets for layout mode text |
| PYSEC-2026-3017 | [PYSEC-2026-3017](https://osv.dev/vulnerability/PYSEC-2026-3017); [GHSA-f2v5-7jq9-h8cg](https://github.com/advisories/GHSA-f2v5-7jq9-h8cg); [CVE-2026-28351](https://nvd.nist.gov/vuln/detail/CVE-2026-28351) | 6.7.4 | pypdf: Manipulated RunLengthDecode streams can exhaust RAM |
| PYSEC-2026-3018 | [PYSEC-2026-3018](https://osv.dev/vulnerability/PYSEC-2026-3018); [GHSA-g9xf-7f8q-9mcj](https://github.com/advisories/GHSA-g9xf-7f8q-9mcj); [CVE-2026-54651](https://nvd.nist.gov/vuln/detail/CVE-2026-54651) | 6.13.1 | pypdf: Possible infinite loop when processing threads/articles in writer |
| PYSEC-2026-3019 | [PYSEC-2026-3019](https://osv.dev/vulnerability/PYSEC-2026-3019); [CVE-2026-31826](https://nvd.nist.gov/vuln/detail/CVE-2026-31826); [GHSA-hqmh-ppp3-xvm7](https://github.com/advisories/GHSA-hqmh-ppp3-xvm7) | 6.8.0 | pypdf: manipulated stream length values can exhaust RAM |
| PYSEC-2026-3020 | [PYSEC-2026-3020](https://osv.dev/vulnerability/PYSEC-2026-3020); [CVE-2026-49461](https://nvd.nist.gov/vuln/detail/CVE-2026-49461); [GHSA-j543-4vmf-qm7v](https://github.com/advisories/GHSA-j543-4vmf-qm7v) | 6.12.2 | pypdf: Possible large memory usage for form XObjects during text extraction |
| PYSEC-2026-3021 | [PYSEC-2026-3021](https://osv.dev/vulnerability/PYSEC-2026-3021); [CVE-2026-41168](https://nvd.nist.gov/vuln/detail/CVE-2026-41168); [GHSA-jj6c-8h6c-hppx](https://github.com/advisories/GHSA-jj6c-8h6c-hppx) | 6.10.1 | pypdf has long runtimes for wrong size values in cross-reference and object streams |
| PYSEC-2026-3022 | [PYSEC-2026-3022](https://osv.dev/vulnerability/PYSEC-2026-3022); [GHSA-m2v9-299j-rv96](https://github.com/advisories/GHSA-m2v9-299j-rv96); [CVE-2026-54531](https://nvd.nist.gov/vuln/detail/CVE-2026-54531) | 6.13.0 | pypdf: Possible infinite loop when processing outlines/bookmarks in writer |
| PYSEC-2026-3023 | [PYSEC-2026-3023](https://osv.dev/vulnerability/PYSEC-2026-3023); [GHSA-qpxp-75px-xjcp](https://github.com/advisories/GHSA-qpxp-75px-xjcp); [CVE-2026-33123](https://nvd.nist.gov/vuln/detail/CVE-2026-33123) | 6.9.1 | pypdf has inefficient decoding of array-based streams |
| PYSEC-2026-3024 | [PYSEC-2026-3024](https://osv.dev/vulnerability/PYSEC-2026-3024); [GHSA-wgvp-vg3v-2xq3](https://github.com/advisories/GHSA-wgvp-vg3v-2xq3); [CVE-2026-27025](https://nvd.nist.gov/vuln/detail/CVE-2026-27025) | 6.7.1 | pypdf has possible long runtimes/large memory usage for large /ToUnicode streams |
| PYSEC-2026-3025 | [PYSEC-2026-3025](https://osv.dev/vulnerability/PYSEC-2026-3025); [GHSA-wjqc-6w8f-h24c](https://github.com/advisories/GHSA-wjqc-6w8f-h24c); [CVE-2026-48735](https://nvd.nist.gov/vuln/detail/CVE-2026-48735) | 6.12.1 | pypdf: Manipulated XMP metadata streams can exhaust RAM |
| PYSEC-2026-3026 | [PYSEC-2026-3026](https://osv.dev/vulnerability/PYSEC-2026-3026); [CVE-2026-41314](https://nvd.nist.gov/vuln/detail/CVE-2026-41314); [GHSA-x284-j5p8-9c5p](https://github.com/advisories/GHSA-x284-j5p8-9c5p) | 6.10.2 | pypdf: Manipulated FlateDecode image dimensions can exhaust RAM |
| PYSEC-2026-3027 | [PYSEC-2026-3027](https://osv.dev/vulnerability/PYSEC-2026-3027); [CVE-2026-27888](https://nvd.nist.gov/vuln/detail/CVE-2026-27888); [GHSA-x7hp-r3qg-r3cj](https://github.com/advisories/GHSA-x7hp-r3qg-r3cj) | 6.7.3 | pypdf: Manipulated FlateDecode XFA streams can exhaust RAM |
| PYSEC-2026-3610 | [PYSEC-2026-3610](https://osv.dev/vulnerability/PYSEC-2026-3610); [CVE-2026-59937](https://nvd.nist.gov/vuln/detail/CVE-2026-59937); [GHSA-55h5-xmcq-c37v](https://github.com/advisories/GHSA-55h5-xmcq-c37v) | 6.14.0 | pypdf: Possible long runtimes for repeated malformed cross-reference entries  |
| PYSEC-2026-3611 | [PYSEC-2026-3611](https://osv.dev/vulnerability/PYSEC-2026-3611); [GHSA-5qjq-93h5-hrgp](https://github.com/advisories/GHSA-5qjq-93h5-hrgp); [CVE-2026-59938](https://nvd.nist.gov/vuln/detail/CVE-2026-59938) | 6.14.0 | pypdf: Possible large memory usage for wrong image dimensions |
| PYSEC-2026-3612 | [PYSEC-2026-3612](https://osv.dev/vulnerability/PYSEC-2026-3612); [GHSA-5xf7-4p34-54qr](https://github.com/advisories/GHSA-5xf7-4p34-54qr); [CVE-2026-59936](https://nvd.nist.gov/vuln/detail/CVE-2026-59936) | 6.14.1 | pypdf: Possible infinite loop for not terminated inline images |
| PYSEC-2026-3613 | [PYSEC-2026-3613](https://osv.dev/vulnerability/PYSEC-2026-3613); [CVE-2026-59935](https://nvd.nist.gov/vuln/detail/CVE-2026-59935); [GHSA-g867-7843-wf8q](https://github.com/advisories/GHSA-g867-7843-wf8q) | 6.14.2 | pypdf: Possible infinite loop for not terminated inline images (ASCII85 and ASCIIHex filter) |
| PYSEC-2026-3655 | [PYSEC-2026-3655](https://osv.dev/vulnerability/PYSEC-2026-3655); [CVE-2026-71870](https://nvd.nist.gov/vuln/detail/CVE-2026-71870); [GHSA-fp3f-mc75-235c](https://github.com/advisories/GHSA-fp3f-mc75-235c) | 6.15.0 | pypdf: Possible large memory usage for large /ToUnicode streams |
| PYSEC-2026-3656 | [PYSEC-2026-3656](https://osv.dev/vulnerability/PYSEC-2026-3656); [CVE-2026-71852](https://nvd.nist.gov/vuln/detail/CVE-2026-71852); [GHSA-fwg2-594c-jp42](https://github.com/advisories/GHSA-fwg2-594c-jp42) | 6.15.0 | pypdf: Possible long runtimes/large memory usage for large CID font width ranges |
| PYSEC-2026-3910 | [PYSEC-2026-3910](https://osv.dev/vulnerability/PYSEC-2026-3910); [CVE-2026-84310](https://nvd.nist.gov/vuln/detail/CVE-2026-84310); [GHSA-23w6-3w8w-8484](https://github.com/advisories/GHSA-23w6-3w8w-8484) | 6.16.1 | pypdf: Possible long runtimes/large memory usage when retrieving outlines |
| PYSEC-2026-3911 | [PYSEC-2026-3911](https://osv.dev/vulnerability/PYSEC-2026-3911); [GHSA-763m-79hh-57f2](https://github.com/advisories/GHSA-763m-79hh-57f2); [CVE-2026-84311](https://nvd.nist.gov/vuln/detail/CVE-2026-84311) | 6.16.1 | pypdf: Possible long runtimes/large memory usage when extracting XForm objects |
| PYSEC-2026-3912 | [PYSEC-2026-3912](https://osv.dev/vulnerability/PYSEC-2026-3912); [GHSA-fc8x-2rww-xw9m](https://github.com/advisories/GHSA-fc8x-2rww-xw9m); [CVE-2026-82398](https://nvd.nist.gov/vuln/detail/CVE-2026-82398) | 6.15.0 | pypdf: Inefficient handling of non-whitespace inputs in read_until_whitespace |
| PYSEC-2026-3913 | [PYSEC-2026-3913](https://osv.dev/vulnerability/PYSEC-2026-3913); [CVE-2026-84309](https://nvd.nist.gov/vuln/detail/CVE-2026-84309); [GHSA-jp53-mhqp-8xcg](https://github.com/advisories/GHSA-jp53-mhqp-8xcg) | 6.16.0 | pypdf: Possible infinite loop for TreeObject.insert_child |
| PYSEC-2026-4153 | [PYSEC-2026-4153](https://osv.dev/vulnerability/PYSEC-2026-4153); [GHSA-5jq2-8x83-x246](https://github.com/advisories/GHSA-5jq2-8x83-x246); [CVE-2026-102994](https://nvd.nist.gov/vuln/detail/CVE-2026-102994) | 6.18.0 | pypdf: Possible long runtimes/large memory usage when parsing indirect objects |
| PYSEC-2026-4154 | [PYSEC-2026-4154](https://osv.dev/vulnerability/PYSEC-2026-4154); [CVE-2026-102995](https://nvd.nist.gov/vuln/detail/CVE-2026-102995); [GHSA-fp3h-c4fm-7vvf](https://github.com/advisories/GHSA-fp3h-c4fm-7vvf) | 6.18.1 | pypdf: Possible large memory usage for large /ToUnicode streams (Follow-up 2) |
| PYSEC-2026-4155 | [PYSEC-2026-4155](https://osv.dev/vulnerability/PYSEC-2026-4155); [GHSA-g9cg-prrw-2r8q](https://github.com/advisories/GHSA-g9cg-prrw-2r8q); [CVE-2026-102996](https://nvd.nist.gov/vuln/detail/CVE-2026-102996) | 6.18.1 | pypdf: Possible large memory usage when parsing font data |
| PYSEC-2026-4156 | [PYSEC-2026-4156](https://osv.dev/vulnerability/PYSEC-2026-4156); [GHSA-jw7q-gvrg-4vj3](https://github.com/advisories/GHSA-jw7q-gvrg-4vj3); [CVE-2026-102997](https://nvd.nist.gov/vuln/detail/CVE-2026-102997) | 6.18.1 | pypdf: Possible long runtimes for partially malformed FlateDecode streams (Follow-up) |
| PYSEC-2026-4157 | [PYSEC-2026-4157](https://osv.dev/vulnerability/PYSEC-2026-4157); [CVE-2026-102998](https://nvd.nist.gov/vuln/detail/CVE-2026-102998); [GHSA-php9-fj8v-98fj](https://github.com/advisories/GHSA-php9-fj8v-98fj) | 6.19.0 | pypdf: Possible long runtimes when generating appearance streams |
| PYSEC-2026-4158 | [PYSEC-2026-4158](https://osv.dev/vulnerability/PYSEC-2026-4158); [GHSA-qv6h-rv94-w285](https://github.com/advisories/GHSA-qv6h-rv94-w285); [CVE-2026-102993](https://nvd.nist.gov/vuln/detail/CVE-2026-102993) | 6.17.0 | pypdf: Possible large memory usage when retrieving Roman page labels |
| PYSEC-2026-4159 | [PYSEC-2026-4159](https://osv.dev/vulnerability/PYSEC-2026-4159); [GHSA-v247-6f48-mgcj](https://github.com/advisories/GHSA-v247-6f48-mgcj); [CVE-2026-102999](https://nvd.nist.gov/vuln/detail/CVE-2026-102999) | 6.19.0 | pypdf: Possible long runtimes with large amount of embedded files |
| PYSEC-2026-4160 | [PYSEC-2026-4160](https://osv.dev/vulnerability/PYSEC-2026-4160); [CVE-2026-103000](https://nvd.nist.gov/vuln/detail/CVE-2026-103000); [GHSA-w23x-9jrw-r45c](https://github.com/advisories/GHSA-w23x-9jrw-r45c) | 6.19.0 | pypdf: Possible large memory usage when retrieving alphabetical page labels |

### python-multipart 0.0.20

运行。上传入口 `POST /api/files` 使用 FastAPI 的 Form 和 UploadFile。

| 编号 | 别名与链接 | 工具列出的修复版本 | 描述原文 |
| --- | --- | --- | --- |
| PYSEC-2026-1852 | [PYSEC-2026-1852](https://osv.dev/vulnerability/PYSEC-2026-1852); [CVE-2026-24486](https://nvd.nist.gov/vuln/detail/CVE-2026-24486); [GHSA-wp53-j4wj-2cfg](https://github.com/advisories/GHSA-wp53-j4wj-2cfg) | 0.0.22 | Python-Multipart has Arbitrary File Write via Non-Default Configuration |
| PYSEC-2026-3036 | [PYSEC-2026-3036](https://osv.dev/vulnerability/PYSEC-2026-3036); [CVE-2026-53539](https://nvd.nist.gov/vuln/detail/CVE-2026-53539); [GHSA-5rvq-cxj2-64vf](https://github.com/advisories/GHSA-5rvq-cxj2-64vf) | 0.0.30 | python-multipart: Quadratic-time querystring parsing with semicolon separators causes CPU denial of service |
| PYSEC-2026-3037 | [PYSEC-2026-3037](https://osv.dev/vulnerability/PYSEC-2026-3037); [GHSA-6jv3-5f52-599m](https://github.com/advisories/GHSA-6jv3-5f52-599m); [CVE-2026-53538](https://nvd.nist.gov/vuln/detail/CVE-2026-53538) | 0.0.30 | python-multipart: Semicolon treated as querystring field separator enables parameter smuggling |
| PYSEC-2026-3038 | [PYSEC-2026-3038](https://osv.dev/vulnerability/PYSEC-2026-3038); [CVE-2026-40347](https://nvd.nist.gov/vuln/detail/CVE-2026-40347); [GHSA-mj87-hwqh-73pj](https://github.com/advisories/GHSA-mj87-hwqh-73pj) | 0.0.26 | python-multipart affected by Denial of Service via large multipart preamble or epilogue data |
| PYSEC-2026-3039 | [PYSEC-2026-3039](https://osv.dev/vulnerability/PYSEC-2026-3039); [CVE-2026-42561](https://nvd.nist.gov/vuln/detail/CVE-2026-42561); [GHSA-pp6c-gr5w-3c5g](https://github.com/advisories/GHSA-pp6c-gr5w-3c5g) | 0.0.27 | python-multipart has Denial of Service via unbounded multipart part headers |
| PYSEC-2026-3040 | [PYSEC-2026-3040](https://osv.dev/vulnerability/PYSEC-2026-3040); [CVE-2026-53540](https://nvd.nist.gov/vuln/detail/CVE-2026-53540); [GHSA-v9pg-7xvm-68hf](https://github.com/advisories/GHSA-v9pg-7xvm-68hf) | 0.0.31 | python-multipart: Negative Content-Length in parse_form buffers the entire body in memory |
| PYSEC-2026-3041 | [PYSEC-2026-3041](https://osv.dev/vulnerability/PYSEC-2026-3041); [GHSA-vffw-93wf-4j4q](https://github.com/advisories/GHSA-vffw-93wf-4j4q); [CVE-2026-53537](https://nvd.nist.gov/vuln/detail/CVE-2026-53537) | 0.0.30 | python-multipart: Content-Disposition parameter smuggling via RFC 2231/5987 extended parameters |

### pytest 9.0.1

与运行库写在同一份 requirements.txt。服务代码未 import。安装边界见上一节。

| 编号 | 别名与链接 | 工具列出的修复版本 | 描述原文 |
| --- | --- | --- | --- |
| PYSEC-2026-1845 | [PYSEC-2026-1845](https://osv.dev/vulnerability/PYSEC-2026-1845); [GHSA-6w46-j5rx-g56g](https://github.com/advisories/GHSA-6w46-j5rx-g56g); [CVE-2025-71176](https://nvd.nist.gov/vuln/detail/CVE-2025-71176) | 9.0.3 | pytest has vulnerable tmpdir handling |

### starlette 0.49.3

传递。不在 requirements.txt。由已安装的 fastapi 0.121.0 带入。

| 编号 | 别名与链接 | 工具列出的修复版本 | 描述原文 |
| --- | --- | --- | --- |
| PYSEC-2026-161 | [PYSEC-2026-161](https://osv.dev/vulnerability/PYSEC-2026-161); X41-2026-002（别名，未构造链接）; [CVE-2026-48710](https://nvd.nist.gov/vuln/detail/CVE-2026-48710); [GHSA-86qp-5c8j-p5mr](https://github.com/advisories/GHSA-86qp-5c8j-p5mr) | 1.0.1 | BadHost: Missing Host header validation poisons request.url.path, bypassing path-based security checks |
| PYSEC-2026-2280 | [PYSEC-2026-2280](https://osv.dev/vulnerability/PYSEC-2026-2280); [CVE-2026-48817](https://nvd.nist.gov/vuln/detail/CVE-2026-48817); [GHSA-x746-7m8f-x49c](https://github.com/advisories/GHSA-x746-7m8f-x49c) | 1.1.0 | Starlette is a lightweight ASGI framework/toolkit. In versions 1.0.1 and below, when dispatching a request, HTTPEndpoint selects the handler by lowercasing the HTTP method and looking it up as an attribute with getattr, without restricting the lookup to a known set of HTTP verbs. When an HTTPEndpoint subclass is registered through Route(...) without an explicit methods= argument, the route does not constrain the method and every method reaches the endpoint. If a non-standard HTTP method whose lowercased name matches an attribute on the endpoint subclass reaches the endpoint, that attribute is invoked as if it were a request handler. An attacker can use this to reach methods that were never meant to be HTTP handlers, such as internal helpers, without the authorization checks applied by the intended public handler. An application (including Starlette-based frameworks like FastAPI) is affected if it registers an HTTPEndpoint subclass via Route(...) without explicitly setting methods=, and that subclass includes extra methods named like non-standard HTTP verbs that take one request argument and return a response. This issue has been fixed in version 1.1.0. |
| PYSEC-2026-2281 | [PYSEC-2026-2281](https://osv.dev/vulnerability/PYSEC-2026-2281); [GHSA-wqp7-x3pw-xc5r](https://github.com/advisories/GHSA-wqp7-x3pw-xc5r); [CVE-2026-48818](https://nvd.nist.gov/vuln/detail/CVE-2026-48818) | 1.1.0 | Starlette is a lightweight ASGI framework/toolkit. In versions 1.0.1 and earlier, StaticFiles on Windows is vulnerable to SSRF. An UNC path such as \\attacker.com\share can cause os.path.realpath to initiate an outbound SMB connection before the path is rejected, exposing the service account’s NTLMv2 credentials for offline cracking or relay even though the HTTP response is only a 404. The issue affects default follow_symlink=False deployments, including frameworks built on Starlette such as FastAPI; POSIX systems and follow_symlink=True are unaffected. The issue is fixed in 1.1.0. |
| PYSEC-2026-248 | [PYSEC-2026-248](https://osv.dev/vulnerability/PYSEC-2026-248); [GHSA-jp82-jpqv-5vv3](https://github.com/advisories/GHSA-jp82-jpqv-5vv3); [CVE-2026-54282](https://nvd.nist.gov/vuln/detail/CVE-2026-54282) | 1.3.0 | Starlette is a lightweight ASGI framework/toolkit. Prior to 1.3.0, the HTTP request path is not validated before being used to reconstruct request.url. Because request.url is rebuilt by concatenating {scheme}://{host}{path} and re-parsing the result, a path that does not begin with / (for example @google.com) moves the authority boundary during re-parsing, so request.url.hostname and request.url.netloc become attacker-controlled. Code that reads request.url.hostname (rather than the Host header or scope) can therefore be misled into trusting an attacker-supplied host. This vulnerability is fixed in 1.3.0. |
| PYSEC-2026-249 | [PYSEC-2026-249](https://osv.dev/vulnerability/PYSEC-2026-249); [CVE-2026-54283](https://nvd.nist.gov/vuln/detail/CVE-2026-54283); [GHSA-82w8-qh3p-5jfq](https://github.com/advisories/GHSA-82w8-qh3p-5jfq) | 1.3.1 | Starlette is a lightweight ASGI framework/toolkit. From 0.4.1 until 1.3.1, request.form() accepts max_fields and max_part_size to bound resource consumption while parsing form data. These limits are enforced for multipart/form-data, but silently ignored for application/x-www-form-urlencoded. An unauthenticated attacker can therefore send a urlencoded body with an arbitrarily large number of fields or an arbitrarily large field, even when the application configured limits it believed would apply. This vulnerability is fixed in 1.3.1. |

## 4. 和本应用路径怎么对上

对照只用描述原文和当前代码，没有重放漏洞。

- pypdf：67 条描述都是在处理不可信 PDF 时可能耗很久或占很多内存，涉及大纲、交叉引用、压缩流、图像、字体等。应用路径是隔离子进程里的提取。子进程限制没有被这次调查改动。
- python-multipart：一条写的是非默认配置下的任意文件写入，列出的修复版只有 0.0.22。三条写分号查询串的拒绝服务或参数走私，列出的修复版是 0.0.30。两条写超大 preamble/epilogue 或超大 part header，列出的修复版是 0.0.26 和 0.0.27。一条写负的 Content-Length 会把整个正文放进内存，列出的修复版只有 0.0.31。一条写 Content-Disposition 扩展参数走私，列出的修复版是 0.0.30。上传接口收的是带文件的 multipart。本轮没有改上传类型检查、大小限制或 CSRF。
- pytest：描述是 tmpdir 处理。服务包没有引用 pytest。
- starlette PYSEC-2026-161：描述是缺少 Host 校验会改写 `request.url.path`。修复版列出 1.0.1。
- starlette PYSEC-2026-2280：描述写的是 `HTTPEndpoint` 用 getattr 按方法名分发，并且只在用 `Route(...)` 注册子类、又没有显式 `methods=` 时适用。本仓库服务代码没有定义 HTTPEndpoint 子类。这只说明当前源码看不到那条注册方式，不是把记录销掉。修复版列出 1.1.0。
- starlette PYSEC-2026-2281：描述写明是 Windows 上的 StaticFiles UNC 路径，POSIX 不受影响。本仓库服务代码没有挂 StaticFiles，运行环境是 Linux。修复版列出 1.1.0。
- starlette PYSEC-2026-248：描述是用请求路径重新拼 `request.url` 时，路径若不以 `/` 开头，主机名可能被带偏。修复版列出 1.3.0。
- starlette PYSEC-2026-249：描述写从 0.4.1 直到 1.3.1，`request.form()` 的字段数和单段大小限制对 multipart 生效，对 `application/x-www-form-urlencoded` 被忽略。已安装的 0.49.3 落在这段文字写的区间里。本应用的上传接口带文件，走 multipart。本轮没有另发 urlencoded 大包。修复版列出 1.3.1。

## 5. FastAPI 与 starlette 的约束

来源是当时已安装的包元数据，不是网页，也不是后来的 FastAPI 版本。文件是 `docs/delivery/scans/fastapi-0.121.0.METADATA`，包名 fastapi，版本 0.121.0。核心依赖原文是：

```
Requires-Dist: starlette<0.50.0,>=0.40.0
Requires-Dist: pydantic!=1.8,!=1.8.1,!=2.0.0,!=2.0.1,!=2.1.0,<3.0.0,>=1.7.4
Requires-Dist: typing-extensions>=4.8.0
Requires-Dist: annotated-doc>=0.0.2
```

`python-multipart>=0.0.18` 只出现在 `standard`、`standard-no-fastapi-cloud-cli` 和 `all` 这些 extra 里，不是上面这四条核心依赖。应用仍然用 UploadFile 和 Form，所以 python-multipart 是实际上传依赖。已安装的 starlette 0.49.3 落在 `>=0.40.0,<0.50.0` 里。

审计虚拟环境里用 `importlib.metadata` 再读了一次 fastapi 0.121.0，核心的 starlette 行与这份 METADATA 相同。

扫描给出的 starlette 修复版本只有 1.0.1、1.1.0、1.3.0、1.3.1。没有一条落在 `>=0.40.0,<0.50.0`。因此不存在「保持已安装的 FastAPI 0.121.0，又改到工具列出的 starlette 修复版」这种组合。本轮没有读取更新的 FastAPI 元数据，所以不提出另一个 FastAPI 版本来配 starlette 1。也不把 starlette 强行钉到 1.x。

主版本号本身不作为变更请求的理由。这里不能配到一起，是因为已安装 FastAPI 的元数据写了上界，不是因为数字从 0 变成 1。

## 6. 单一候选组合

状态都是待判。没有安装，没有改 `requirements.txt`，没有关 CSRF、Origin、Cookie、上传限额或解析隔离。

在已读到的 FastAPI 0.121.0 约束内，能写下来且不越界的组合只有现状：fastapi 0.121.0 加 starlette 0.49.3。这组没有消化工具列出的 starlette 记录。starlette 的修复因此继续待判，不能在这次证据里选一个 1.x 版本。

另外三个单包候选彼此独立，也还没有放进上面这组一起安装：

- pypdf：67 条的最低列出修复版里，最高的是 6.21.4，而且有 3 条只列出 6.21.4。没有任何一条的最低列出修复版还是 5.x。若把「更高版本包含更早的修复」当作假设，6.21.4 是工具结果里能对上全部已列编号的一个候选。这个假设不是工具逐条写明的。库仍是 pypdf，解析仍应只在现有子进程里做。5 到 6 本身不构成变更请求；兼容性和隔离是否仍够，要等以后真的升级再测。现在不选为已获准版本。
- python-multipart：7 条各自只列了一个修复版，分别是 0.0.22、0.0.26、0.0.27、0.0.30、0.0.31。其中最高的最低列出修复版是 0.0.31，对应负 Content-Length 那一条。工具没有把 0.0.31 写进另外 6 条的 `fix_versions`。FastAPI 的 extra 下界是 `python-multipart>=0.0.18`，0.0.31 满足这条下界；没有上界。这只说明下界挡不住它，不是调用已经试过。候选 0.0.31，待判。
- pytest：唯一记录只列出 9.0.3。仍是 pytest 9.0 这一线。若以后升级，应同时把 pytest 和 ruff 从生产安装用的 requirements 里拆出去，并交出两份安装清单：一份运行集不含 pytest，一份测试集含 9.0.3。现在不拆、不升。

没有把这四项收成一个「全部升到工具最高修复版」的组合，因为 starlette 1.3.1 与 fastapi 0.121.0 的元数据冲突，而更新的 FastAPI 元数据没有读过。

## 7. 前后差异

调查前和调查后，12 个钉死版本、已安装的 starlette 0.49.3，以及审计环境里的 55 个版本都没有改。没有新增锁文件来驱动安装。差异只是证据从当时的临时目录抄进了仓库：原先 `DEPENDENCY-REVIEW.md` 只有方向，没有编号和原文。

因此没有「升级前 / 升级后」的行为差。取消修复的修前修后轨迹仍以 `docs/delivery/DEVIATIONS.md` 里 DEF-ZHIXU-A-TEST-001 那一节为准，不在这里重测，也不改那次提交。

## 8. 若以后 PM 选定版本，再做的回归和复询

本轮不做这些。选定版本之后，在那个新提交上：

1. 写操作仍同时检查登录会话、Origin 和 CSRF。生产环境的 Secure Cookie 语义不变。别人的资源和 SSE 仍按拥有者拒绝。
2. 上传仍做扩展名和内容类型检查，以及单文件、会话个数和总大小限制。解析失败保持在子进程外失败，不改到主进程提取。
3. PDF 和 DOCX 仍只在非特权、无网、限目录、限资源的子进程里导入。隔离不可用就失败关闭。
4. 会话、SSE 重连、上传、取消后的终态和删除撤回保持现有行为。取消修复 `43b0fc3` 的「等第一条增量、连续取消两次、再发」要在夹具上再跑，夹具通过仍不是真实 Qwen 取消。
5. 若动 starlette 或 FastAPI，安装结果必须落在当时附上的那份元数据区间里。不能为了工具列出的 1.x 关掉这段约束。
6. 用同一套 pip-audit 2.10.1 和 OSV，对升级后的安装集再查一次，交完整 JSON。写明原编号是否消失、有没有新编号。复询没有记录，也不等于安全准出。
7. 中文 PDF 仍要能抽出原有样例里的汉字和数字。真实 Qwen、引用语义、浏览器点击和性能仍另计，不因依赖复询而算通过。

## 9. 本轮明确没做

- 没有升级、降级或新钉任何包。
- 没有关闭校验，没有改库的职责、权限、存储或隔离。
- 没有把主版本变化写成必须提变更请求，也没有批准 6.21.4、0.0.31、9.0.3 或 starlette 1.x。
- 没有重跑 pip-audit，没有为了补严重度再访问漏洞站。
- 没有把 55 包环境或 24 包 `--local` 结果说成完整的生产镜像扫描。生产安装集仍然没有单独的锁。

