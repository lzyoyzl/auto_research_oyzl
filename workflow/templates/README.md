# AI/ML 会议的官方 LaTeX 模板

以下是项目下载并逐文件记录 SHA-256 的官方作者包。目录保留论文示例、样式、参考文献格式及示例需要的资源。用于研究稿排版，实际投稿前按目标届次重新核实规则与开放时间。ACL 使用官方持续维护的模板快照。

| 会议 | 本地模板入口 | 当届指南 |
|---|---|---|
| ICML 2027 | [example_paper.tex](icml/example_paper.tex) | [ICML Author Instructions](https://icml.cc/Conferences/2027/AuthorInstructions) |
| NeurIPS 2026 | [neurips_2026.tex](neurips/neurips_2026.tex)，附 [checklist.tex](neurips/checklist.tex) | [NeurIPS Call for Papers](https://neurips.cc/Conferences/2026/CallForPapers) |
| ACL / ARR | [acl_latex.tex](acl/acl_latex.tex)，官方提交 d5adc823 | [ACL 官方样式](https://github.com/acl-org/acl-style-files/tree/d5adc823ff0f80f98c80405ca0ab66c68e684409) · [ARR 投稿要求](https://aclrollingreview.org/cfp) |
| IJCAI 2027 | [ijcai27.tex](ijcai/ijcai27.tex) | [IJCAI Author’s Kit](https://ijcai.org/authors_kit/) |
| CVPR 2027 | [main.tex](cvpr/main.tex)，含审稿模式、正文子文件和回复模板 | [CVPR Author Guidelines](https://cvpr.thecvf.com/Conferences/2027/AuthorGuidelines) |
| AAAI 2027 | [AnonymousSubmission2027.tex](aaai/AnonymousSubmission2027.tex)，附 [可复现性清单](aaai/ReproducibilityChecklist.tex) | [AAAI Submission Instructions](https://aaai.org/conference/aaai/aaai-27/submission-instructions/) |

在项目根目录运行 `python3 workflow/venues.py acl /目标目录` 即可复制该会议的整套样式。加 `--compile` 可编译官方样稿。目标目录若已有修改过的同名样式，工具会提示换目录。正式研究会把作者包复制到该研究自己的 `latex/`，新稿件使用 `manuscript.tex` 与 `references.bib`。[原始下载地址与校验清单](venues.json)

例如，CVPR 2027 在作者指南中明确要求 LLM Usage Statement，AAAI-27 要求单独上传可复现性清单，ACL/ARR 有针对语言研究的负责研究要求。生成稿件时应根据实际使用情况填写。ICML 2027 官方样稿可以生成 PDF，其原样示例对 `assumption` 有一处 cleveref 格式警告；研究稿输出时控制器会检查未解析的引用。[CVPR 2027 要求](https://cvpr.thecvf.com/Conferences/2027/AuthorGuidelines) · [AAAI-27 要求](https://aaai.org/conference/aaai/aaai-27/submission-instructions/) · [ARR 要求](https://aclrollingreview.org/cfp)
