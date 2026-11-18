# 用 Codex 从一个方向推进到 AI/ML 论文

在这个项目的 Codex 会话中说 **“我的研究方向是【大致方向】，请自主推进到论文草稿。”** 即可。Codex 负责查文献、提案和执行。你保留两个决定：选哪个核心 idea，以及给正式实验多少算力。

## 运行过程

| 阶段 | Codex 自主完成的工作 | 可检查的产物 |
|---|---|---|
| 搜索与读原文 | 扩展检索词、跟踪引用、获取并阅读公开 HTML/PDF，在原文核对方法、结果和局限。 | `search.json`、`sources/`、`literature.json`，含原文指纹与章节摘录 |
| 构思与选题审核 | 每个候选展示最强旧方法直接迁移的结果预期、技术难点、具体机制与代价，并串起 Introduction、Background、Motivation、预实验和推翻条件。构思时新发现的技术近邻也会缓存原文、核对摘录。至少三个候选供选择，整批退回后按反馈重新提案。 | `ideas.json`、`proposals/`、`reviews/idea-*.md` |
| 小规模预实验与算力审核 | 在你选定的 idea 上做短小本地试跑，用实测规模与耗时外推正式工作量、显存与费用，提交预算申请。等待你批准或退回修改。 | `pilots/`、`budgets/`、`reviews/budget-*.md` |
| 实验与调整 | 获批后自动运行、修复、验证。换核心 idea 回到选题审核。下一次运行预计超出剩余额度时，先提交增额申请。 | `rounds/NN/` 的方案、代码、日志与决策，`accounting/` 的资源记录 |
| 确认与写作 | 用冻结程序运行确认数据。原始配对分数必须能重算报告均值。负结果或证据不足可写成有限结论。没有一次有效测量时保留失败记录。 | `confirm.json`、版本化英文草稿、主张与证据对照表 |
| 审查和排版 | 审查可要求修订；选取对应官方作者包编译。控制器核查引用可解析、已审实证主张出现在 PDF。 | `paper.md`、`paper.pdf`、`latex/manuscript.tex`、`latex/references.bib`、审查记录 |

程序负责保存状态、运行实验、核验文件和根据决定切换阶段。阅读、提出新假设、诊断失败和改写方法由 Codex 完成。默认每项研究最多四轮开发实验，每次实验限时 300 秒。每个实验同时报告基线、候选及配对单位；无法按样本分解的指标可按独立种子或整次评测聚合。样本与种子等计量单位应写在计划里。支持保留开发阶段负结果，确认后的数据不能重新当成新方案的盲测。

## 首次使用

在 Linux 或 WSL 的仓库根目录创建 Python 环境并安装 PDF 读取依赖。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install pypdf
```

每个课题的提案、原文、结果和草稿写入本地 `studies/`。仓库的忽略规则也覆盖 `data/` 和 `runs/`。

## 两种启动方式

**在当前聊天中使用**：直接给方向。到审核节点时，自然语言回复即可，例如“选第二个”“都不合适，重新考虑标注成本”或“批准这份算力申请”。Codex 会针对你看到的申请登记回复并继续。[项目研究指令](AGENTS.md)

**在 WSL 终端连续运行**：从项目根目录执行以下命令，把引号里的文字换成你的方向。命令在前台运行并打印研究目录。重新执行同一方向时会定位到原目录并继续。此模式通过已登录的 Codex CLI 分阶段调用模型，使用相应账户额度。

```bash
.venv/bin/python workflow/study.py run "你的 AI/ML 研究方向"
.venv/bin/python workflow/study.py status studies/<研究编号>
.venv/bin/python workflow/study.py resume studies/<研究编号>
```

PowerShell 下在同样的命令前加 `wsl -d Ubuntu -- `。想限定算力时可在首次启动时传 `--rounds 6 --seconds 600`。命令行依次尝试本地 Codex 和 WSL 可访问的 Windows Codex；可用 `RESEARCH_CODEX` 显式选可执行文件。默认审查阶段使用新上下文，模型与执行阶段可能相同；可用 `RESEARCH_REVIEW_MODEL` 指定账户可用的另一审查模型。

### 在命令行回复审核

`run` 和 `resume` 遇到待审会展示申请并退出。使用 `next DIR` 可重看。用屏幕上的实际审核编号和候选 ID 替换以下示例；登记回复后运行 `resume DIR`。

```bash
python3 workflow/study.py choose DIR idea-3 I2
python3 workflow/study.py revise-brief DIR idea-3 --reason "补充原始证据，给出能区分两种解释的对照"
python3 workflow/study.py repropose DIR idea-3 --reason "希望降低标注成本"
python3 workflow/study.py approve-budget DIR budget-1
python3 workflow/study.py revise-budget DIR budget-1 --reason "把费用上限降至 200 元"
```

同一个申请选择一种回复。旧编号不能批准新版本。预实验默认使用本地 CPU，每次最多 60 秒，并受 `--seconds` 限制。选择时可用 `--pilot-gpu 0` 授权一张已经分配的本地卡。CPU 预实验会明确注明正式 GPU 显存是估算值。

申请单展示实测预实验、正式 GPU 型号、预计每卡峰值 GiB、卡数、累计墙钟小时、卡时、币种、单价及总费用。单价按每卡小时计，CPU 任务按主机小时计。控制器在启动开发和确认进程前核对硬件需求、剩余时间及费用，为作业预留额度，结束后按耗时结算。失败运行也记账，中断且无结束记录时保留整笔预留。选定新的核心 idea 后重做预实验；原批准额度仍能覆盖时自动沿用。增额申请显示历史已记成本，新批次取代旧余额。这里核算的是实验进程的配置与预计计算费；云主机空闲费、存储、平台取整和 Codex 调用费用不在本地计量范围内。

**环境。** 使用 Linux/WSL、Python 3.12+、已登录且支持联网搜索的 Codex CLI、pypdf（或 uv）以及带参考文献工具的 TeX Live/latexmk 或 Tectonic。正式实验的其他依赖取决于选题。控制器在本地用户权限下执行生成的实验程序，无人值守运行时建议使用专用工作环境。

## 框架、研究质量与会议模板

- [研究 idea 写作指南](workflow/idea-writing.md)给出从文献提出候选、写 Introduction / Background / Motivation、检验竞争解释以及用结果组织论文的方法，含完整提案示例。构思、写稿和审稿阶段自动加载全文。
- [框架来源与实际复用范围](workflow/frameworks.md)记录了 FARS、ARIS、AutoResearchClaw、SciDER 和 Karpathy autoresearch 对本项目的作用。
- [AI/ML 阅读、查新、实验和写作约定](workflow/research-standard.md)会交给每个研究阶段。模型审查与程序化验算能减少部分错误；学术新颖性、作者披露和投稿适配仍需作者最终判断。
- [六个会议的官方模板](workflow/templates/README.md)已下载到项目中，保留来源、版本及哈希。目标会议可在给方向时一并指定，也可让 Codex 按贡献推荐。届次标明样式版本，投稿窗口另行核实。
- 运行 `.venv/bin/python -m unittest discover -s workflow -p test_flow.py` 可用临时夹具验证失败、修复、转向、确认、审查返修和 PDF 生成。夹具成绩只用于检验软件。
