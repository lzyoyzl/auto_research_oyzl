"""Contracts for Codex. Both the current chat and the CLI use the same stages."""
import json
import shlex
from approvals import WAITING, budget_path, pending_text, pilot_dir, proposal_path, round_path, totals
from venues import VENUES
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROMPTS = json.loads((HERE / "upstream/prompts.json").read_text())
UPSTREAM = {"read": "knowledge_extract", "ideas": "hypothesis_gen",
            "decide": "research_decision", "review": "peer_review"}


def task(run, state):
    phase = state["phase"]
    if phase in WAITING:
        return pending_text(run, state)
    number = state["round"]
    rd = round_path(state)
    revision = f"writing/v{state['version']:02}"
    contracts = {
        "discover": """使用联网搜索，扩展检索词、沿引用找到原始论文。按任务现象和解决它的操作分别检索；
寻找可能使用同一机制的邻近领域及能直接移植的强方法。写 search.json，格式
{"queries":["实际搜索词"],"sources":[{"id":"P1","title":"...","url":"可公开获取论文全文的 HTML 或 PDF 网址"}]}。
给出至少三篇不同原始论文，优先可访问的出版社或作者全文；可多给备选链接。控制器会下载并提取原文。""",
        "read": """阅读 sources/ID/text.txt 的方法和实验或局限章节。摘要页面只作线索。
读到关键图、表或定理时，记下它能区分的解释、控制条件和仍未回答的问题。记录作者实际改动了哪一步、
使用的信息和开销，以及什么条件限制这项方法的直接迁移。
如需补充可通过 python workflow/study.py source RUN ID FULLTEXT_URL 添加原文，可用 --file LOCAL_PDF。
写 literature.json，格式 {"searches":["检索词"], "papers":[{"id":"P1","title":"...",
"section":"原文章节或页码","excerpt":"可在缓存中核验的简短原文片段","method":"方法或理论设定",
"data":"数据与划分或适用条件","comparison":"基线、指标或比较对象","finding":"...",
"limitation":"..."}]}。每篇原文摘录不超过 25 个词。""",
        "ideas": """自主提出至少三个不同机制的候选，复查最接近的工作，按新意证据、可证伪性、现有算力和可获取数据排序。
写候选文件，格式 {"reason":"向用户推荐首选及其相对于其他候选的理由","venue":"icml/neurips/acl/ijcai/cvpr/aaai 中一个小写名称",
"venue_reason":"研究问题和预期贡献与该会议读者的关联","ideas":[{"id":"I1","title":"...",
"novelty_assessment":"截至检索日期，哪些部分已有先例，是否找到做过同一核心机制并验证同一问题的原文；证据不足处写明",
"closest_difference":"引用最近邻论文 ID 和章节，比较其方法、设置、验证结论与本题的重合及剩余差异","sources":["P1"],
"introduction":"具体问题、受影响的场景和拟检验的研究问题",
"background":"理解该问题所需的技术前提、已有方法及其适用条件，标注文献 ID",
"motivation":"由哪项已知观察推导出什么待验证假设，为何值得尝试，什么观察能区分它与替代解释",
"evidence_gap":"引用支持具体前提的原文图、表或章节，并指出现有证据不能确定的关键环节",
"technical_neighbor":{"url":"最能削弱该技术主张的原文全文 URL；可用初读来源的原 URL，也可给新发现的原文",
"section":"方法、结果或局限的具体章节、图表或定理","excerpt":"可在该全文核验的短原文，最多 25 词",
"transfer_baseline":"把该工作的最强做法移植到本设置，说明怎样给予同样的数据、监督与资源，以及它仍可能解决不了什么"},
"technical_obstacle":"在明确假设和约束下，指出必须解决的瓶颈，并给出旧方案与拟议机制会作出不同选择的具体情形",
"prediction":"如果假设成立，哪种条件下哪个指标应改善，何种边界条件下收益应消失",
"competing_explanation":"指出能产生相同表象的竞争解释及只改变关键因素的公平对照",
"mechanism":"从输入到输出写出可执行的关键操作或推导，说明固定量、可改变的变量，以及主张成立的条件",
"cost_boundary":"说明代价来自何处、哪些成本需实测，以及何时近似、结论或部署条件会失效",
"design_argument":"从可改变的变量到实际使用目标的关键关系、推导依据和适用假设",
"design_check":"用参考解、独立观测、反例或正负对照校验关键操作，并区分实现失败与主张失效",
"pilot":"先查瓶颈覆盖率或可改善空间，再给能区分新机制和直接迁移方案的最低成本检验",
"falsifier":"什么结果会推翻设想"}]}。按优先顺序排列；交给用户选定或整批退回。
先写出把已有方法直接移植后可以交付的最强方案，再提出仍需要研究的操作、证明或识别设计。
若两者在所声称的条件下始终等价，合并或重构候选。明确区分原文结果、条件推导和未测预测。
提交前按下方《研究 idea 写作指南》倒读每个候选。把初次读者应记住的研究问题写进 introduction；
如果两种解释都能预测同一结果，改写 competing_explanation 和 pilot，让结果能改变判断。
整批退回后提出不同机制。若反馈要求修订论证，读取上一版和反馈，补证据、修正推导，重新送审。""",
        "pilot": """使用用户选定的 idea，在预实验目录写 plan.json（idea_id、workload）和 pilot.py。
从选定提案找最薄弱的前提，说明哪两种观察会让下一步决策不同；测量无力时报告样本或资源限制。
读取 selected_proposal 中获选候选的核心机制、直接迁移对照和适用边界。优先测实际可改善空间，
或用小规模精确解、反例或正对照检验关键操作；说明该诊断能支持的结论范围。
使用小样本或少量训练步，最小化本地资源；默认 CPU，只有用户已授权的本地 GPU 可用于此预实验。
禁止使用付费 API、远程任务和隐藏后台进程。程序由控制器运行，最后一行输出 JSON，包含正整数 n；
若使用 GPU，输出框架实测 peak_vram_gib_per_card，无法测量时填 null。保留规模、配置和结果。
失败时参考同一选题前次 pilot.log 修复。不要自行启动实验或录入人工批准。""",
        "budget": """根据刚完成的预实验拟定正式实验申请，写入指定路径。JSON 字段：
idea_id, pilot_ref（当前状态提供的原始结果路径）, gpu_model, cards（整数）, vram_gib_per_card,
wall_hours（后续所有正式轮次、确认及余量的累计墙钟小时）, currency（三字母币种）,
hourly_rate（GPU 每卡每小时或 CPU 每主机小时）, pricing_basis, estimate_basis。
说明 GPU 型号和来源、显存、卡数、单价来源、外推公式、种子、消融、确认和误差范围。
CPU 预实验不能声称实测了 GPU 显存：写明估计依据和不确定性。只在本地确实免费时填零；
未确认的商业报价应给出有来源的保守估计和计价假设。卡时和费用由控制器计算。
若预算退回按反馈重估。若上限不足，列出原额度、已记消耗及申请的后续额度。""",
        "plan": f"""读取上轮决策和累计证据，为 {state['idea']} 写 {rd}/plan.json 及独立的 {rd}/experiment.py。
沿用获选提案的关键对照，说明哪个中间量和最终指标分别检验哪一步。若为测量或理论贡献，使用适用的诊断或反例。
复用项目内 ARIS experiment-plan 的主张、替代解释和成功判据。计划 JSON 字段为 idea_id,
hypothesis, change, dataset（可追溯来源、固定版本和获取方式）, metric, higher_is_better（布尔）,
min_gain（非负数，0 表示须严格改进）, dev_split, confirm_split（彼此独立的划分/种子），以及
compute（gpu_model、cards、vram_gib_per_card、seconds、currency、hourly_rate；
seconds 是每个 split 的最长墙钟秒数）。在获批资源上设计能回答问题的实验，保持已选机制。
程序支持 --split dev 和 --split confirm，在当前轮目录运行，输出最后一行为包含 baseline,
candidate 和 n 的 JSON 对象。同时写 dev-scores.json 或 confirm-scores.json，数组中每行含唯一字符串
unit、数值 baseline、candidate；控制器复算均值与 n。指标若不可按样本分解，可按种子/整次评测配对；
在计划中说明计量单位、真实样本规模及聚合规则，并保留逐预测原始文件。配置、依赖和复跑命令保存在本轮目录。
在确认前只用 dev；确认必须运行冻结的同一程序。控制器负责执行，按 compute 时限和审批余额检查。
以方向决定模型、数据与评价；纯技术修复、科学修订、换想法都在新轮次留记录。""",
        "decide": f"""阅读 {rd}/dev.json 和真实日志，判断是实现错误、数据问题、反证还是信号足够。
写 {rd}/decision.json，字段 action, idea_id, diagnosis, next_test；action 选 refine（同一想法）,
pivot（切换至候选列表内不同 idea）, confirm（达标后用冻结方法验证）, write（写有限或负结果）。
把开发结果与提案的条件预测对照。说明哪项证据改变了判断、哪些竞争解释仍成立、下一轮用什么观测区分它们。还有可区分的实验且预算充足时主动继续。
缺失运行成绩时不能将其解释成反证。""",
        "confirm": "控制器会用同一轮冻结的方法运行确认实验；直接执行 advance。",
        "write": f"""阅读所有历史、原文和实验日志；若已有写作审查意见，逐项修订。在 {revision}/draft.md
写完整英文 AI/ML 论文草稿，包含标题、摘要、引言、相关工作、方法、结果、讨论、局限、参考文献和复现说明，
用原文链接标注引用，区分探索与独立确认，报告失败和负结果。另写 {revision}/claims.json，
格式 [{{"claim":"正文中原样出现的一条实证主张","evidence":["rounds/01/dev.json"]}}]。
每条实证主张指向实际测量记录；交叉核对数值、方向、样本数及区间。
按下方指南把获选提案的预测改写成证据允许的结论。用读者的问题串起主图，解释反例、零结果和适用范围。""",
        "review": f"""审查 {revision}/draft.md、claims.json、原始文献和运行证据，逐条检查引文支持、
数据划分、统计解释、负结果与结论强度。写 {revision}/review.json，格式
{{"verdict":"ready 或 revise","checks":["核验了哪条主张及其依据"],"issues":["须修改的问题"]}}。
从结论倒查引言，核对人群、指标、对照和边界。提出最强竞争解释，定位能区分它的证据。
若现有证据只能支持更窄的主张，指出原句、缺少的证据与可成立的改写。
有实质问题时给 revise 和具体修改项；ready 必须已解决所有实质问题。""",
        "typeset": """依据已审稿的英文 draft.md 和 claims.json，将相同内容排成 latex/manuscript.tex 和
latex/references.bib。依照 latex/ 下官方匿名投稿示例启用对应样式，保留应有的检查清单、影响、
局限或使用模型的说明；匿名表格、链接与补充材料按届次核验。引用元数据逐项核对。保留所有限定与负结果。
claims.json 中的主张须以相同措辞出现在 PDF 正文中，控制器会对排版后的 PDF 验算。
只输出这两个完整文件，主文档使用 references.bib；先确保它们可编译。""",
        "done": "论文草稿已完成，向用户交付 paper.pdf、LaTeX、paper.md、证据位置、限制和运行记录。",
        "blocked": "当前研究已保留记录。说明具体阻塞和已有证据，恢复前先处理阻塞原因。",
    }
    guide = ""
    if phase in UPSTREAM:
        template = PROMPTS[UPSTREAM[phase]]
        guide = ("\nAutoResearchClaw 方法参考；输出格式、篇幅与研究领域均以本地约定为准。\n"
                 + template["system"] + "\n" + template["user"])
    if phase in {"ideas", "write", "review"}:
        guide += "\n" + (HERE / "idea-writing.md").read_text(encoding="utf-8")
    if phase in {"ideas", "pilot", "plan", "decide", "write", "review"}:
        guide += "\n" + (HERE / "method-design.md").read_text(encoding="utf-8")
    contract = contracts[phase].replace("source RUN ID", f"source {shlex.quote(str(run))} ID")
    details = {k: state.get(k) for k in ("idea", "selected_proposal", "selected_design", "idea_feedback", "pilot_ref", "pilot_gpu",
                                        "timeout", "budget_reason", "needed")}
    if state.get("grant"):
        details["approved"] = state["grant"]["limits"]
        details["used"] = totals(run, state["grant"]["id"])
    if phase == "ideas":
        details["output"] = proposal_path(state)
    elif phase == "pilot":
        details["output_dir"] = pilot_dir(state)
    elif phase == "budget":
        details["output"] = budget_path(state)
    contract += "\n本次约束：" + json.dumps(details, ensure_ascii=False)
    if state.get("selected_design") and phase not in {"discover", "read", "ideas"}:
        contract += "\n读取 selected_design 的冻结正文，以用户实际选定的这版方法为准。"
    venue = state.get("venue")
    venue_note = (f"\n目标会议 {venue}，官方说明 {VENUES[venue]['source']}，模板入口 {VENUES[venue]['entry']}"
                  if venue else "")
    return (f"研究方向：{state['direction']}\n研究目录：{run}{venue_note}\n当前阶段：{phase}，"
            f"轮次 {number}/{state['max_rounds']}\n读 state.json 及已完成产物，再执行本阶段。"
            f"文件路径相对研究目录，代码命令在项目根执行。\n{contract}{guide}\n"
            + (HERE / "research-standard.md").read_text())
