# MedPaper Pipeline (Kiro)

一套面向医学与临床研究的 Kiro 工作流。它把“研究想法”推进为经过数据、文献、统计结果、图表、人工复核和期刊规则共同校验的投稿包，而不是只让 AI 一次性写出一篇看似完整的论文。

当前版本：`1.14.0`　｜　流程：25 个阶段　｜　运行环境：Windows + Kiro IDE + R 4.3+

## 1.14.0 变化（外部审阅 8 条 + 3 项决定）

- **冻结后措辞**：改动分为 SAFE / MEANING_CHECK / SCIENCE；会改变含义的措辞由审阅代理或作者逐对判定，"含义变化"才走科学路径。
- **写作材料完整**：写作代理拿到每个结果（临床标签、比较、CI 水平），缺口单列并阻断；引用他人数字必须出现在该文献原文/摘要中，摘要真实比对，无摘要须经核验全文。
- **复现保护数据**：复现只复制（有大小上限），不建链接、不改数据；数据前后校验，变化为 CRITICAL；清理只删本论文的过期沙箱。
- **分析停止规则**：主要/次要结局和既定有效性检验完成即止；附加分析须写明可能改变哪个科学决定；结果变化后旧 GO 决定需重判；不设检索条数下限。
- **缓存与发布**：门禁缓存覆盖检查读取的每个文件；论文只接受打了发布标签 vX.Y.Z 的全局引擎（否则 rc 3）；`wf doctor` 报告未打标签或未推送；论文守卫钩子阻止对引擎的 git 写命令。
- **审阅与版式**：审阅包附"预设与看数据后决定"的事实记录（不进稿件），审阅者检查事后分析未被写成验证性结论；写 Results 前看一次全部表图（一张图）；Word 中表注与表格同页（仅表格末行 keepNext，Word 2013 版式模式）。
- **迁移**：只记一条事件；新门禁 `since = "1.14.0"`；论文文件不改。

## 1.13.0 变化（项目隔离与引擎保护）

- **工作路径与隔离**：论文目录即当前工作区（cwd 或 `MEDPAPER_PROJECT`），不再读 `wf use` 全局标记，拒绝操作其他论文；每篇论文装 PreToolUse 守卫钩子（`install_adapters.py --paper`），禁止读写其他论文/归档/系统临时目录、写引擎、手改 `.wf` 引擎状态文件。
- **引擎保护**：共享引擎有未提交修改时所有论文命令拒绝运行（rc 3，`wf doctor` 显示）；论文级修正走覆盖配置或 `wf engine-fork`（论文内副本，差异留给维护者）。
- **数据不复制**：`wf data add` 原地登记数据源（只读）；复现沙箱在论文 `.wf/repro/sandboxes`，硬链接/原地读取，中断自动清理；超限复制拒绝；`data_not_copied` 门禁。
- **复现只跑一次**：文档、取数、缓存不算分析输入；按声明依赖只重跑受影响脚本；日志只在 `.wf/logs/`，有上限。
- **修改与写作**：冻结后可溯源的展示层修改不回退；多人核对只针对人工编码；正文不写方案偏离；每个写作阶段当场润色（`section_language_clean`），S22 只做统一；Word 不再产生 keepNext/keepLines 黑点（行 `cantSplit` + 表头重复）。
- **误报与小修**：千位分隔符、bib 花括号冒号、"No. 2026J" 等缩写后数字不算句首数字；引号内自造标签未入展示词典时提示；S24 卡片与基线重捕获规则一致（先分类、后重建）。
- **迁移**：只记一条事件；新门禁 `since = "1.13.0"`，已完成阶段沿用锁定门禁集；论文文件不改。

## 1.12.0 变化（精简与修误报）

- **误报修复**：回查已完成阶段不再判 `single_section_written`；R 渲染中 QC 等待 `.rendering` 标记、报“渲染中”而非失败；Excel 锁文件 `~$*` 忽略、被占用的工作簿报 IO 问题，表注说明性常数登记在显示词典 `footnote_constants`；审阅覆盖改为增量（只要求改动文件）；清单 WARN 不再显示为 FAIL；堆叠柱合法；bib 导出与检查共用一条规则；表注改为逐表结构检查。
- **更轻**：删去引言/讨论字数下限；默认推迟目视检查无需记录 DEFER（仍在 S23 结清）；“缺少产出”合并为一行；polish 三条合一；`docx_keep_with_next` 并入 `docx_bundle_ready`，确认句并入 `review_round_approved`，S23/S25 重复的期刊上限、参考文献计数、补充方法检查改为清单行（门禁条目 287→281）；`wf check` 默认只打印失败项+一行摘要，完整清单写 `.wf/logs/`。
- **CLI**：`--words/--why` 中文乱码自动修复，另支持 `--words-file/--words-b64`，写入后回读校验；`wf status` 同时显示引擎版本、状态记录版本与论文锁定版本（只有 `wf migrate --yes` 改锁定）；回退/重进计入 `loops`；`.wf/logs/`（或 `temp/logs/`）为日志目录；`reference_count.py show` 在标题页生成前不报错；`review_round.py status` 输出合法 JSON，等待用户答复时可开 delta 轮；`target_journal.json` 的 `line_numbers` 控制 Word 行号；`--wait` 心跳 ≤30 s。
- **卡片与编排**：每张阶段卡 ≤4000 字符（细节移至 `reference/stage_details/`），SKILL.md 精简并新增“执行经济”；`wf handoff` 输出 ≤60 行的交接包；审阅代理只可写自己的 `report.md`，`close` 默认读取；新增 `medpaper-clinical-writer` 代理与 `tools/manuscript/writer_bundle.py`（只含临床标签、文字化结果、表图文字，无代码/键名/日志）。
- **提前发现**：`first_reader_displays`（单位、分母、句末标点、期刊禁用图内标题；S10/S11 警告、S12 阻断并含缩写/工程用语/流程图单位）；新增展示项须写 `non_redundancy`；S17 起审阅包附草稿 DOCX（可转换时附页面预览）。
- **迁移**：只记事件；新门禁 `since = "1.12.0"`，已完成阶段沿用锁定门禁集。

## 1.11.0 变化（临床表述层）

- **展示词典与工程用语**：S07 必填 `01_protocol/display_dictionary.json`（内部名→临床标签/缩写/定义），表、图内文字、图注与正文只用临床标签，字母代号默认禁止；`reference/clinical_language.toml` 工程词表在 Methods 警告、其余正文/表/图/图注阻断，实现细节进补充方法，论文级例外写 `.wf/language_allowlist.json`（须理由）。
- **表图自明**：表注、图注各自定义所用缩写，正文另留集中列表（仅期刊明确要求时 `central_required`）；流程图为示意图（框+计数+箭头，不要坐标轴），计数须带分析单位，拒绝“行/文件/版本”等处理日志；Word 仅对标题去折叠，保留题注→表→表注、图注↔图的同页设置。
- **呈现规范前移**：S07 写暂定期刊参数 `01_protocol/journal_profile.json`（字号下限、图宽、面板标签大小写、线条图 dpi、数字格式），表图从首次渲染即按其执行，S20 确认或替换（属展示层重渲染）；图内文字终稿尺寸 ≥8 pt；表格不得出现 Undefined/Not fitted/NA/Inf，缺失符号统一；表注按总字数控制，诊断信息进补充表。
- **审阅闭环**：每轮所有编号意见（含 Reader comprehension、Medical presentation）须逐条关闭，`close --report` 校验；首轮即加入“初读临床读者”“工程用语与表图自明”视角；审阅者只拿 `review_round.py start` 生成的自包含材料包与中性说明。
- **修订与冻结**：标签内编号（Online Resource 2、Table S3、面板/条目号）不算事实；`rework.py preview` 先试分类；回退 S19 需用户原话“我确认回退”；轮次范围外的写入在写入时拒绝；冻结分科学层/展示层（图注、表注措辞可在期刊阶段改，事实不变）；最终版新增数字须能追溯到结果 JSON 且 n/N(%) 自洽；正文比例登记分子分母（`analysis.results.proportion`），同句比较须同口径。
- **运行**：复现只受分析输入影响，期间改正文不作废；`--wait` 阻塞等待+心跳，输出只留失败项与一行摘要；进度写入论文 `.wf/progress.md`；门禁按语义角色识别标题（含期刊名称与同义词），meta 分析识别否定句并优先用 `study_design`；控制台中文按读取端代码页输出，不再乱码。
- **迁移**：只记事件；新门禁均 `since = "1.11.0"`，已完成阶段沿用锁定引擎；已按旧规则集中缩写的论文保留其设置直至 `wf migrate`。

## 1.10.0 变化（13 条流程顺序与规则）

- **先表图后结果**：执行顺序 S10 表 → S11 图 → S09 Results（从最终表图写，`displays_final_for_results`）→ S12 只做交叉核对；阶段编号不变。
- **核验前移**：S08 方法学引用写入即联网核验（`reference_provenance cited_in`）；S04 变量口径对照表逐条确认，S06 随机 10 例回原始记录抽查（`tools/analysis/spotcheck.py`）；S03/S06 方案写明统计报告计划（主要比较数、多重性、效应量与区间），S09 仅报 P 值时提示。
- **声明自动判定**：S01/S03 必填结构化 `study_design`、`data_source`；S21 用 `tools/declarations.py` 判定伦理、知情同意、数据可得性并给出依据，只问无法判断的那一处。
- **软额度三段制**：写作期字数/文献数只警告；S13 只看论证角色覆盖（`06_refs/coverage.json`）；S17 篇幅与 45–60 篇体检（警告），库内每条须被引用或写明未引理由；S20 后按期刊上限硬卡，并按期刊图表上限做主/补充重分配计划。图注长度默认只提示，期刊明确规定才卡；每图规划图内文字与图注（`text_plan`）。
- **讨论引用他人数字**：须与原文引用同句且在已核验库中；`number_allowlist.tsv` 不再适用于 Discussion。
- **审阅与确认**：涉及数字、分组、结论强度的意见不得以“保留”自行关闭，须修改或由作者裁决（`review_round.py author`）；确认只认“我确认这一版”（或 “I confirm this version”）并记录版本哈希；第三方只读包仅在用户明确要求时 `review_round.py export`。
- **迁移**：只记事件；新门禁均 `since = "1.10.0"`，已完成阶段沿用论文锁定引擎；当前停在 S09 且表图未完成的论文自动转到 S10。

## 1.9.1 变化

- **复现进度与复用**：`reproduce.py run --log <论文>/temp/repro.log` 逐行刷新 `[i/N] start|ok|FAIL` 并以 `REPRODUCE DONE rc=N ...` 结尾；脚本、数据、manifest、容差、结果及引擎分析助手哈希均未变时直接 `REUSED`（`--force` 强制重跑）；有变化时默认只重跑受影响脚本（`--full` 全跑）。

## 1.9.0 变化（S01–S25 全程运行反馈 25 条）

- **冻结后按内容分级**：S19 冻结后的修订在 `rework.py check` 时比对事实（数字、引用、表图引用、表格单元格、图的数据来源）。事实不变即“排版修改”：只重跑确定性检查，冻结记录 presentation delta，不回 S19、不新开审阅轮、不重新确认，只向用户汇报修改摘要；事实变化仍回 S19。投稿包确认只绑定上传文件的可见内容，内部 QC/notes/凭据不使其失效。
- **期刊字段驱动**：`main_text_headings`、`keywords.min/max/separator`、`blinded_main_manuscript`、`spelling`、`number_format` 由构建器在 DOCX/表格/R 图中套用；Markdown 源保持工作流规范名。检查对照期刊字段，缺省时才用工作流默认值。
- **派生文件确定性**：xlsx/docx/PDF/TIFF 固定时间戳与元数据；`manifest.json`、`qc_report.json` 可自动续期；漂移一次列全；`rework.py mark --deleted-file`；kind `journal` 更名 `journal-switch`（旧名兼容、batch 时校验），新增 `journal-format`。
- **误报修正**：事实比对忽略 ICD-10/5-minute/(1)–(4) 等词内数字，`author_info.json` 登记的伦理号等行政事实可写入；CRediT 角色名白名单；期刊上限默认 100%（接近上限只警告）。
- **构建与排版**：双盲时补充材料首页与 docProps 去作者信息并检查；表格 `< 0.001`、`n = 162`、`95% CI` 用不换行空格且列宽不低于最长词；论文内 `csl_patch.json` 与 `csl_check.py` 比对官方示例；清单 DOCX（`checklist_docx.py`）固定列宽、无内部路径。
- **一致性前移与其他**：S12 `display_numbering_consistent`（首次引用顺序、表题两处一致、分面板引用）；`baseline_counts()` 输出二分类两类计数；正文列表阻断 `prose_not_lists`；`wf check --quiet/--summary/--reuse`；`preview.py` 渲染 PNG 联系表；论文锁定引擎版本（`wf migrate` 显式迁移）；S25 可用 `final_copy.py` 以“作者终稿副本”合法结束；S23 卡片列出投稿门户待办。
- **迁移**：只写一条 `requirements_changed` 事件，不改论文文件。

## 1.8.1 变化（实测反馈 2 条）

- **Word 三线表**：xlsx 放入正文时不再走 Pandoc 管道表（其内置 Table 样式只画表头下线，且把标题行、脚注行塞进表格）。现直接写 OOXML：表级边框全部为 none，三条线用单元格边框显式绘制（首行上粗线、末表头行下细线、末行下粗线），多行/合并表头的细线在最后一行表头下，无竖线；标题在表上方、脚注在表下方边框之外。
- **每表新页 + 横竖自动**：开启 `word_tables` 时每张表单独分节、另起一页；列数 > 7 或估算宽度超过纵向版心即横向（页面尺寸互换、边距不变），之后回到纵向正文。可在 `artifact_plan.json` 表条目或 `target_journal.json` 的 `tables.<id>.orientation` 写 `portrait|landscape|auto` 覆盖。页码页脚跨节共用、连续编号。Word 审计新增三线、分页、方向和每节页码检查。
- **审阅改为子代理轮次**：S19/S24 不再生成第三方审核 ZIP。每轮 `tools/review_round.py start` → 调用只读 `medpaper-reviewer` 子代理 → 主代理自主采纳能提升稿件的修改（冻结内容走 rework）→ `close` 记录发现/修改/未改原因 → 向用户一次性汇报并只问“是否再审一轮” → `decide`。用户说无需继续审阅即记录批准；科学冻结绑定最后一轮。轮次记录在 `.wf/review_rounds.json`，审阅后任何被覆盖文件变化都需新一轮（可 `--delta`）。
- **在途论文迁移**：只写一条迁移事件，不改论文文件；已有审核 ZIP 或 S24 OK 的论文按旧记录继续有效。

## 1.8.0 变化（实测反馈 27 条 + 借鉴 Codex 1.9–1.11）

- **Word 构建**：所有 docx 页脚自动 PAGE 页码并审计；参考文献“1. 作者……”（编号 + 句点 + 一个空格，不用 Tab、不悬挂缩进；仅期刊明确要求时 `target_journal.json` 设 `"reference_separator": "tab"`）；数字引用合并为 [1–3]；正文图注只放主图，补充图注随补充文件输出；图注前缀/粗体/分图标签大小写/末尾标点、嵌入图、Word 表、补充材料别名（Online Resource n）均由 `target_journal.json` 控制；补充文件默认另出 PDF（`--pdf`），自动加信息页、清除流水线代码与本地路径、代码等宽小字号。
- **期刊规则结构化**：`limits`（main_text_words、abstract_words、reference_limit、display_items…）取代从指南散文正则抽取；Word 兼容字数（含数字，正文 Introduction–Conclusions）、97% 余量，S23/S25 直接测量最终 docx；S17 起草默认上限（正文 4000、摘要 250）。声明顺序默认 Springer Nature，标题页与正文一致；Discussion 默认无子标题。
- **refs.bib**：标题专有名词/缩写加 `{}`、ISO 期刊缩写（shortjournal）、文章号、页码完整范围、姓氏前缀保护；S13 新增 `bib_format_clean`。分组引用 `[@a; @b]` 在事实保持比较中等价。
- **后台语言与缩写**：检测“independent review / earlier draft / reviewer request”等流水线历史表述；缩写分别在摘要、正文、每个表格内检查首次定义和“定义未用”。
- **修订轮次**：`batch --merge` 并入已封存轮次、`--priority` 挂起当前轮次先做新反馈、`suspend`/`resume --round` 恢复并自动 rebase、`progress` + `resume` 显示中断后的逐条进度；S23 改动冻结/已认证的图表源码在写入（hook）和 `wf run-script` 时立即拦截，`rework.py layout` 开受控版式轮次；相同内容重新冻结无需 `--force`；`08_submission/notes/` 为代理记录目录。
- **审阅与 QA**：`reader-inputs` 生成与哈希绑定的文本副本，`--delta` 增量复审；`submission_qc.py write` 由实测生成 SUBMISSION_CHECKLIST 和 QC 记录，`submission_checklist_measured` 在 S23/S24/S25 同一清单执行。
- **设计与运行**：S03/S06 `design_precedent_recorded`（对照、分母、主要结局的先例或方法学理由）；S01/S21 收集编码者资质；输出强制 UTF-8；`wf check/advance --log`；自测解析全部阶段卡命令（修正 `wf loop --to`、删去 `--project project`）。
- **借鉴 Codex**：最低字数/引用数改为提示不再阻断（不凑数），期刊显式上限仍严格；全文获取失败即停止；pandoc 子进程超时；最终 docx 计数。
- **进行中的论文**：迁移只记录事件（`requirements_added`），不改论文文件。需要：在 `target_journal.json` 补 `limits`；重建 docx（页码、参考文献格式、主图注）；运行 `submission_qc.py write`；S03/S06 尚未完成的补 `Design precedent`。

## 1.7.3 变化

- **取消预先注册与报告清单**：非 Meta 研究不再要求注册，方案不再有 `Reporting guideline` 节；报告清单仅当 S20 在 `target_journal.json` 写入 `journal_requires_checklist`（期刊要求时）才在 S23 填写，否则 gate 按“不需要”通过。Meta 分析保留 PROSPERO 注册建议与 PRISMA。进行中的论文无需操作，迁移时记录事件。

## 1.7.2 变化

- **公开数据库研究的报告清单**：从原文全文补齐 RECORD（13 条扩展项）、STROBE-MR（42 条）、TRIPOD+AI（52 条）；方案可写 `Guideline: STROBE + RECORD`，清单须覆盖两者并集（分块，或合并块中条目加前缀如 `RECORD 7.1`）；S03 卡片给出常见设计→规范对照。

## 1.7.1 变化（采纳外部审阅）

- **全文身份只看首页**：PDF 只在首页/参考文献标题之前的正文中找身份证据，须同时具备本文 DOI 与标题相似度（≥0.8）或第一作者姓氏+年份；目标 DOI 只出现在参考文献中判为“另一篇文章”（mismatch），证据不足为 indeterminate（S15 不通过）。1.7.0 及以前按“DOI 出现在任意位置”接受的记录须重新 `fulltext.py verify --all-retrieved`。
- **报告清单要证据**：清单表改为 `Item | Status | Location | Evidence | Reason`；每条 Reported 须给出 ≥25 字、在所写位置原文中确实存在的引文（忽略空白/大小写/强调符号），同一引文最多复用 3 条。目录中 `CONSORT` 改为 CONSORT 2025（30 项/42 子项），旧版须写 `CONSORT 2010`。
- **复现按声明依赖**：`03_analysis/analysis_manifest.json` 声明脚本顺序与输入输出；`reproduce.py run --affected-only` 只重跑依赖闭包受影响的脚本，其余从上次通过的证明延续。无 manifest 时沿用文件名顺序并警告。
- **作图不重拟合**：`recipe_km`/`recipe_cif` 默认绘制分析脚本用 `curve_table_km()`/`curve_table_cif()` 写入结果 JSON 的曲线表；只有 `refit = TRUE` 且 `analysis_n` 与完整病例数一致时才在图中拟合。sidecar 记录 `population`，qc 校验 N 与 source_results 一致。
- **R 结果全精度**：`write_results()` 与 sidecar 改用 `digits = I(17)`，双精度可无损往返（1/3、π、2^53 在 1.7.0 中会被截为 15 位）。
- **按需环境检查**：`wf doctor` 只把作图核心包与本论文 R 脚本实际用到的包列为必需，其余统计包仅作提示。
- **当前论文提示**：每条 `wf` 命令在 stderr 打印所操作的论文及其来源；全局 `wf use` 标记与之不同、或当前目录属于另一篇论文时给出提示/警告。
- **进行中论文须做**：R 写出的结果需用 `wf run-script` 重跑后再 `reproduce.py run`；S23 之后的论文按新表头补全 Evidence 列；已通过 S15 的 PDF 运行一次 `fulltext.py verify --all-retrieved`。

## 1.7.0 变化

- **局部返修不回卷**：S19/S24 的修改意见默认不再回卷后续阶段。每条反馈 `rework.py batch --plan` 收集（不构建），用户说完后 `rework.py seal --why` 封批一次、只构建一次；已完成阶段保持完成，`wf loop` 在返修期间被拒绝。整体回卷保留为显式兜底：`batch --rewind`（换刊等）。
- **依赖闭包最小重建**：`wfcore/dependencies.py` 依据 artifact_plan、结果 JSON 的 `environment.script`/`source_files`、表格与投稿包 manifest 计算受影响文件；缺少依赖信息时保守全连。`save_medpaper`、`assemble.py`、`build_docx.py` 只允许写闭包内文件，改一张 R 图只重画这一张。`rework build --scope full` 每轮最多 2 次。
- **范围校验与漂移检测**：`rework.py check` 只运行受影响阶段的内容 gate（审批/生命周期 gate 除外，paper 级跳过的阶段不参与）；闭包外任何文件变化即失败；文献缓存等证据刷新不算漂移。改动 `03_analysis/` 必跑 `analysis_reproduces`；gate 回执在返修前后全部作废。
- **S19 后的科学改动**：在 S24 提出的科学改动先回到 S19 重新审批并重新冻结，S20–S23 历史保留；随后 `wf advance` 在 S24 自动续开投稿包返修轮，合并到期刊稿后用 `scientific_freeze.py rebind-variant` 重新绑定。
- **兼容**：修订轮 schema 2；仍读取 schema 1。进行中的旧轮次（schema 1）按原回卷流程完成，迁移时只记录事件，不转换。

## 1.6.0 变化

- **PubMed 实时核验短时复用**：`reference_provenance`（`live = true`）通过后，把本次 gate EFetch 原始 XML 的 SHA-256 记入论文自己的 `.wf/reference_live.json`。24 小时内（`live_reference_age_hours_max`）后续阶段重新解析该 XML 并逐条比对文献库，一致时直接复用；文献库或 XML 变化、超时都会重新联网。S13 与 S25 始终强制实时核验。
- **gate 失败即停与短时复用**：`outputs_exist` 失败后，其余检查标为 `dependent_checks_pending`，不再执行，也不能 `--force`。`wf check` 为纯本地检查（md_sections、md_wordcount、no_ai_boilerplate、supplementary_methods_clean、numbers_have_provenance、manuscript_structure、docx_bundle_ready）写 120 秒回执。紧接着的 `wf advance` 在输入文件、引擎、配置、决定、overrides 完全一致时复用。完整性、审批、冻结和实时检查一律重跑。
- **冻结加固**：S19 完成后若缺少科学冻结，`scientific_freeze_intact` 直接失败。冻结同时覆盖 `03_analysis/results/*.json`，记录 S19 审阅包 ID，并要求 `manuscript_human_reviewed=NO_FURTHER_REVIEW` 的理由中写明该 ID。1.6.0 之前的冻结只校验该决定，原有论文不受影响。
- **换刊归档**：`reset-journal` 与 `open-variant --force` 不再删除旧期刊内容，而是移到 `08_submission/journal_archives/<期刊>-<UTC 时间>/`；`no_orphans` 与 `wf clean` 忽略该目录。
- **R 图来源绑定**：`save_medpaper()` 先写临时文件，全部成功后再改名替换，渲染失败时保留旧图。同时输出 `cairo_pdf` 矢量母版。sidecar 记录 `script`、`script_sha256`、`source_hashes`（来自计划的 `source_results`）和 `render_hashes`。`qc.py` 的 `r_render_provenance` 在脚本、结果或图件变化后判定失败。作图期间 ggplot 警告按错误处理（`warn = 2`）。视觉审阅改为绑定 PNG 的 SHA-256。
- **非 R 图需说明理由**：`figure_engine = R` 时，Python 图须在计划中写 `renderer` 和不少于 20 字的 `renderer_reason`。已批准的 Python 图原样保留，不为改用 R 出图而重拟合模型。
- **P 值与符号校验**：`P<0.001` 必须有结果 JSON 中确实小于 0.001 的 P 值支持（或分析自身写出的同一阈值、或 allowlist 声明）。负号与 `−`（U+2212）视为同一符号，正负号不同即不匹配；显示精度用 Decimal 计算。CONVENTIONS 与 `environment` 排除保持不变。
- **S18 审阅覆盖**：新增 `reader_review_coverage`。审阅报告须内嵌 `reviewed_artifacts` 哈希块，由 `review_round.py start` 生成（1.8.1 前为 `review_package.py reader-inputs`），覆盖正文、表格和全部已渲染的图。报告还须包含 `Reader comprehension` 与 `Medical presentation` 两节，每节不少于 80 字。

## 1.5.0 变化

- **论文在引擎之外**：引擎目录是纯净的母版工作流，只用于维护，任何论文都不能放在其中、在其中被选中或向其中写文件。论文统一放在论文根目录（优先 `MEDPAPER_PAPERS_ROOT`，其次 `~/.medpaper/config.toml` 的 `papers_root`，默认 `<引擎上级目录>/medpaper_papers`）。`wf new <slug>` 在那里创建论文并写入该论文自己的 `.kiro/` 适配文件（以绝对路径调用引擎），之后把这个论文文件夹作为独立的 Kiro 工作区打开。解析顺序：`MEDPAPER_PROJECT` → 当前目录或其上级中已初始化的论文 → `wf use` 选中的论文（用户级标记 `~/.medpaper/active`）。在引擎目录中运行 `wf status` 只显示维护横幅，驱动论文的命令一律拒绝；`wf doctor` 把引擎中的任何论文产物报告为 BROKEN。
- **Python/R 分工**：见 `reference/language_policy.toml`。Python 负责数据获取、清洗、三线表 xlsx、Word 和全部门禁；R 负责作图（默认，`tools/figures/R/medfig.R` 的 `save_medpaper()` 与 `recipes.R` 中的 KM、竞争风险、森林图、ROC、校准、DCA、火山图）以及生存分析、竞争风险、列线图/校准/DCA、多重插补、倾向性评分、复杂抽样、混合模型、Meta 分析和 Table 1 统计。`save_medpaper()` 按目标栏宽精确出图，自动统一外边距，并写出与 Python 相同格式的 QC 记录，`qc.py` 对两种引擎一视同仁。`wf config set figure_engine python` 可改回 matplotlib。
- **分析复现门禁**：S06 运行 `python tools/reproduce.py run`，在沙箱中按 `analysis_manifest.json` 声明的顺序（1.7.1；无声明时按文件名）重跑 `03_analysis/code/` 下的全部顶层脚本，要求结果 JSON 完全一致（仅忽略时间戳）；重跑结果保存在 `.wf/repro/rerun/` 作为证据。`analysis_reproduces` 在 S06、S17、S23、S25 复核，任何分析代码、原始数据或结果的后续修改都会使证明失效。
- **环境回执**：结果 JSON 只能由 `write_results()`（Python `tools/analysis/results.py`，R `tools/R/medresults.R`）写出，自动附带语言与版本、程序包版本、随机种子、脚本及其 SHA-256。回执中的数字不计入数字溯源。
- **报告规范清单**（1.7.3 起按需）：仅当目标期刊要求（或 Meta 分析的 PRISMA）时，S23 生成 `08_submission/reporting_checklist.md`，逐条对应到期刊稿中真实存在的位置；未收录条目清单的规范（`verify = true`）不会被凭空编造。

## 这套工作流解决什么问题

医学论文真正困难的部分不是生成文字，而是让研究问题、数据、统计分析、文献、图表、正文和投稿文件彼此一致，并且符合目标期刊的要求。这个工作流用分阶段推进和自动检查来降低以下常见风险：

- 研究选题已经高度饱和，做完后缺乏发表价值；
- 数据源明明可全量获取，AI 却为省时间、上下文或算力只取前 N 条、抽样或漏翻页；
- 引用、DOI、PMID、期刊名或年份由 AI 凭记忆生成；
- 正文中的数字没有分析结果作为来源，或表图与正文对不上；
- Methods 过长，把敏感性分析、实现细节等全部堆进主文；
- 图注重复 Results，缩写到处重复，表格和图片不像医学期刊文章；
- 作者信息过早介入，打断科学内容的形成；
- Word 文件字体、字号、行距、颜色、标题层级或超链接不符合期刊要求；
- 投稿包缺文件，标题、作者、图表编号、补充材料和声明跨文件不一致；
- AI 生成并不存在或未经用户确认的伦理、基金、利益冲突或作者信息。

工作流的目标是：在保证研究有效性和材料一致性的前提下，优先寻找真实、当前、合规且接受概率较高的 SCIE 期刊。Q3、Q4 和低影响因子期刊完全可以作为合理目标；不会为了影响因子牺牲匹配度和现实接受概率。

## 适合与不适合的情况

适合用于临床队列、回顾性研究、真实世界研究、数据库研究、生存分析、预测模型、组学研究及其他可形成医学论文的项目，也可从已有数据、已有分析或半成品论文继续推进。

它不适合替代研究者的伦理责任、临床判断和最终署名确认；也不能把数据本身不支持的结论“包装”成可发表结果。若关键设计、数据质量或统计有效性存在硬伤，流程会给出 `PIVOT`（调整）或 `STOP`（停止），而不是继续生成投稿文件。

## 核心处理逻辑

整个流程遵循一条依赖链：

```text
研究问题 → 发表可行性 → 方案 → 数据 → 分析结果
        → 图表计划 → Methods/Results → 实际图表 → 一致性校验
        → 参考文献 → Introduction/Discussion → 完整论文
        → 独立审查 → 人工修改 → 期刊选择 → 投稿包
        → 人工最终确认 → 独立投稿审查
```

每个阶段都声明自己的输入、输出和通过条件。只有当前阶段的必需文件存在并通过检查后，流程才会进入下一阶段。这样可以避免论文先写完、最后才发现数据、文献或图表无法支持正文。

用户审阅后提出的修改也不会脱离流程。系统先判断修改由哪个阶段负责，再返回最早受影响阶段：例如 Methods 回到 S08，Results 文字回到 S09，统计结果回到 S05，Discussion 回到 S16。修改首先落到分节 Markdown、分析结果、表格或图片等来源文件，再重新组装依赖项；不会孤立修改 `full_manuscript.md`。

反复改稿有两个固定入口：S19 用于科学内容、分析解释和完整论文的多轮审核；S24 用于已经匹配目标期刊后的 Word、投稿文件和跨文件一致性审核。用户在任何时候提出反馈，系统都会把原话、一次性解释、拆分后的原子修改项、受影响来源和验收标准保存为一个修订轮次，再回到该批修改中最早的负责阶段。新增反馈可并入尚未结束的轮次；只有全部修改项完成、相关门禁重新通过并返回原审核节点后，该轮次才能关闭。轮次数量没有上限。

这种设计不会用“少读、少改、少检查”换取 token。流程在上下文压缩后从磁盘上的修订状态恢复，不需要反复重读整段聊天；只读取受影响的来源文件，重建真正依赖它们的产物，并复用未变化且哈希仍一致的证据。所有受影响的分析、数值溯源、引用、图表、Word 渲染、人工确认和独立审查仍照常执行。token、上下文、时间或计算成本都不能成为遗漏修改项、缩小研究范围或跳过质量门禁的理由。

贯穿全流程的规则包括：

1. 数据获取默认覆盖 S03 已定义的完整研究数据范围。每个来源都要保存源端总数、实际接收数、末页/游标证据及原始文件哈希；不能为省时间、token、下载量或算力自行抽样、只取前 N 条、限制页数或缩短日期范围。
2. 文献搜索工具可以发现候选论文，但正式引用必须重新获取并验证元数据。
3. 正文中的统计数字必须先存在于代码生成的机器可读结果中，不能在写作时心算或补造。
4. 润色只允许修改表达，不允许悄悄改变数字、引文、图表引用或结论强度。
5. 患者级数据、个人信息、凭据和密钥未经明确授权不得上传到外部服务。
6. ImageGen 可参与图片的视觉检查和改进建议，但不能代替由数据和代码生成科研图，也不能绕过数值核对。
7. 工作流不会自行撰写或加入 AI 使用声明；如期刊要求，只把它记录为由用户决定的合规事项。

## 母版、单篇定制与期刊稿分离

`pipeline/`、`tools/`、`reference/` 和 `.kiro/` 是所有论文共用的母版。运行论文时不应修改这些目录；否则某篇研究的特殊需求会改变后续所有项目。每篇论文只在论文根目录下自己的 `<slug>/` 文件夹内写文件。简单数值配置写入该论文的 `.wf/config.toml`：

```powershell
python tools/wf.py config set intro_words_max 600
```

如果研究设计确实需要不同的流程形状，使用论文自己的覆盖文件，而不是改母版：

```powershell
python tools/wf.py override init
# 编辑 <论文目录>/.wf/overrides.toml
python tools/wf.py override validate
python tools/wf.py override show
```

覆盖文件可以增加输出和门禁，也可以在写明充分理由后放宽非完整性门禁或跳过真正不适用的普通阶段。数据完整性、文献/数字溯源、全文身份、视觉欠账、科学稿冻结等门禁，以及 S18、S19、S24、S25 的审阅/审计阶段不能关闭。`wf status` 每次都会显示本篇所有覆盖；阶段完成时还会保存覆盖条目的指纹，事后不能悄悄修改或删除。若研究设计后来真正变化，应先 `wf loop --to <stage>` 回到负责阶段，再修改覆盖。论文自有 Python/R 脚本统一通过 `wf run-script <相对路径.py|.R>` 执行，工作目录固定为本篇论文，并监测母版目录是否被写入。

科学稿与期刊稿也分开。S19 经用户确认无需继续修改后，`scientific_freeze.py capture` 冻结 `07_manuscript/` 的科学内容；S20 选刊后，在 `08_submission/manuscript/` 创建该期刊的副本。字数限制、结构化摘要、参考文献样式、题名页和期刊声明只改这个副本。改投另一期刊时，先返回 S20 并运行 `scientific_freeze.py reset-journal --confirm-journal "<旧期刊>"`，把旧期刊的缓存、题名页、润色记录、cover letter、bundle、基线和审批整体移到 `08_submission/journal_archives/`（归档保留，不参与任何门禁），再从同一冻结稿生成新期刊副本。这样既不会反复改动已经确认的论文，也不会把上一期刊的任何投稿残留带到下一期刊。

## 25 个阶段分别做什么

### 第一部分：确定研究是否值得做

#### S01｜整理研究想法

把自然语言想法整理成结构化研究问题，包括研究设计、人群、暴露或干预、对照、结局、预期创新点、候选数据源和待确认问题。此阶段需要用户提供真实研究意图，但不会询问作者、单位等投稿信息。

输出：结构化研究想法和贯穿项目的研究笔记。

#### S02｜第一次发表可行性判断

使用真实文献检索了解已有研究、研究空白和主题饱和度，并记录检索过程。判断该问题是否值得继续：`GO` 表示继续，`PIVOT` 表示调整问题或设计，`STOP` 表示当前条件下不宜投入更多工作。

输出：可行性报告、检索记录和第一次 go/no-go 决策。

#### S03｜形成初版研究方案

明确研究目的、设计、人群和纳排标准、变量、主要统计计划、样本量或效能考虑、适用的报告规范以及伦理要求；同时预先定义需要获取的完整数据范围、数据从哪里来、精确查询与过滤条件、如何翻完全部页面、如何证明源端总数与实际接收数一致。

输出：初版 protocol 和数据获取计划。

### 第二部分：让数据和方法形成可靠的科学故事

#### S04｜获取并登记数据

保存原始数据，建立变量字典和来源记录，使用代码生成数据集概要和缺失情况。原始数据视为不可随意修改，清洗后的数据与生成过程分开保存。

这一阶段不再以“raw 文件夹里有文件”作为完成标准。`acquisition_manifest.json` 会逐个来源核对：源端总数证据、请求数、接收数、原始载荷计数、是否到达最后一页/空游标、全部原始文件与获取代码的 SHA-256，以及接收记录到分析数据行数的排除/合并关系。获取代码中的 `LIMIT`、`TOP`、`head()`、`sample()`、前 N 条切片和固定页数等常见偷懒旁路会被阻断，且不能用 `--force` 绕过。

允许两种不等于“偷懒抽样”的情况：一是协议在看数据前就规定、并经用户明确同意的科学抽样设计，此时仍须获取该设计样本的全部记录；二是只用于测试连通性或字段的小型 pilot，但 pilot 不得用于分析，且 S04 结束前必须继续完成全量获取。若外部来源确实限制访问，AI 必须先向用户说明范围和偏倚，只有用户明确授权后才能用完整的“可访问子集”继续。

输出：原始/衍生数据、获取代码、全量获取清单、codebook、provenance 和数据集概要。

#### S05｜方法调研与探索性分析

结合同类研究的方法进行检索，运行分析代码，检查数据能够回答什么问题、哪些结果稳定、哪些地方需要调整。此时不急于制作正式图片，避免在分析尚未收敛时浪费排版工作。

输出：分析代码、机器可读结果、分析日志、方法调研和关键发现笔记。

#### S06｜冻结最终方案并再次判断可发表性

根据真实数据和分析结果修订方案，说明相对初版的偏离及理由，并进行第二次 go/no-go 判断。只有分析已经收敛且研究仍具现实发表价值，才进入写作和正式制图。

输出：最终 protocol、方案差异记录和第二次决策。

### 第三部分：先规划正文需要的证据，再写作

#### S07｜规划表格、图片和图注

参考同类型医学论文，确定主表、补充表、主图、补充图及补充文件的合理数量和作用。图注只负责解释设计、分组、符号、统计标记和阅读方法，不复述 Results 中的结果。

输出：图表计划、同类文章基准、表题和图注草稿。

#### S08｜撰写 Methods

采用医学 SCI 论文常见而灵活的骨架：研究设计与场景、研究对象及纳排标准、暴露/干预和变量、结局、数据来源与质量控制、统计分析、伦理。只保留理解和复现研究所必需的内容，通常以 Statistical analysis 结束。

若敏感性分析、亚组定义、算法参数、复杂实验步骤或实现细节会让主文过长，则写入独立的“补充方法”，主文只做简洁说明并指向补充材料。补充方法只保留叙述性方法内容，不嵌入表格，也不保留 Markdown 的 `---`、`***`、`___` 等长横线；所有补充表移至 S10 生成的独立三线表工作簿。具体小标题会随研究设计调整，不强迫所有研究套用同一模板。

输出：Methods；必要时另有 supplementary Methods。

#### S09｜撰写 Results

只根据已经运行并保存的分析结果写作，按科学问题组织叙述，引用已经规划的表和图。所有数字必须能回溯到结果文件，不在文字中临时计算。

输出：Results 初稿。

### 第四部分：生成并核对读者真正看到的表和图

#### S10｜制作医学期刊表格

从分析结果生成读者可读的三线表。主表与补充表分别组织，检查数值来源、表题、脚注、缩写、格式和可读性，并进行实际视觉检查。

输出：XLSX 表格、生成脚本和表格清单。

#### S11｜制作医学期刊图片

由分析代码生成 PNG/TIFF 等科研图片，检查尺寸、分辨率、字体、线条、颜色、面板标识和图注对应关系。先做确定性的技术检查，再看渲染后的实际图片；发现问题则修改代码并重新生成。

输出：图片、生成代码、质量检查报告和最终图注。

#### S12｜正文、数字、表格和图片对账

逐项确认 Methods 和 Results 中的分析、数值、表图编号与实际产物一致，确保没有未引用的图表、错误的编号或跨文件数值冲突。

输出：一致性核对记录。

### 第五部分：建立可信文献基础并完成正文

#### S13｜建立已验证参考文献库

通常建立约 45–60 篇与研究直接相关的文献库。每条正式文献必须由内置 `tools/pubmed/verify.py` 发起一次新的 PubMed EFetch，并把原始 XML、XML 的 SHA-256、解析后记录指纹和当时的 `library.json` 哈希绑定在一起。门禁会重新解析 XML 并逐项复算 PMID、DOI、题名、作者、期刊、年份和摘要；S13 会另行实时访问 PubMed 核对，Introduction、Discussion、全文组装、人工审阅、Word 打包和最终审计等后续关口也会再次实时核验，防止先过关后篡改。`verified: true` 只是状态字段，单独存在没有任何证明力。BibTeX、RIS 和内部文献库也必须一致。

引用真实性门禁属于不可豁免门禁：即使使用 `wf advance --force` 也不能通过。任何临时脚本、手写 JSON、伪造 DOI，或者为了消除 Pandoc 警告而直接修改 `library.json`、`verified.json`、`refs.bib`、`refs.ris`，都会因缺失或不匹配的原始证据、文件哈希或实时 PubMed 结果而失败。正确处理方式只能是检索真实论文并替换引用，或者删除没有真实来源支持的引用。

输出：已验证文献库、BibTeX 和 RIS 文件。

#### S14｜撰写 Introduction

从临床或科学背景推进到当前知识缺口，再落到本研究目的。引用只来自已验证文献库，避免泛泛堆砌背景或夸大创新性。

输出：Introduction。

#### S15｜深读支撑 Discussion 的核心论文

在合法开放获取或用户授权的路径下，选取约 5 篇最关键论文进行全文阅读和结构化笔记。仅有搜索摘要而未获得全文时，不假装已经深读。

输出：核心论文深读索引和笔记。

#### S16｜撰写 Discussion

解释主要发现，与核心文献比较，讨论可能机制、临床或研究意义、优势和局限，并给出与数据相称的结论。避免重复 Results，也避免把关联写成因果。

输出：Discussion。

### 第六部分：组装全文并先做一次独立审查

#### S17｜自动选题目并组装完整论文

根据研究问题和实际结果自动选择最准确、最具可读性的题目，不要求用户先从多个题目中选择。随后生成摘要和 3–6 个关键词，并按医学论文顺序组装 `full_manuscript.md`。

关键词位于摘要之后，只使用逗号分隔，不使用 `/`、`;`、`&` 等混杂符号。完整稿包含明确的 References 标题，并在末尾保留简洁 Figure legends。每个表注、图注各自定义所用缩写（表图自明），正文另保留一份集中的 Abbreviations 列表；仅当期刊明确要求时才只保留集中列表。

输出：题目、摘要、关键词、声明/缩写区和完整论文 Markdown。

#### S18｜独立子代理审查可发表性

冻结完整论文、补充方法和表格，交给一个只读的独立子代理审查。它不参与改稿，只判断研究是否已具备在合法当前 SCIE 期刊发表的基本条件，并区分致命设计问题与可修正的表达或报告问题。

审查结果为：`READY`（可进入人工审核）、`REVISE`（修正后有发表可能）或 `NOT_READY`（仍有实质性障碍）。判断标准包含科学有效性、报告完整性、方法长度、表格与补充材料一致性、结论强度及现实期刊层级。

输出：独立可发表性审查报告。

#### S19｜用户审核科学内容

把完整论文、补充方法、全部表格和独立审查报告一次性交给用户。用户可修改内容；若修改涉及分析，必须回到分析来源并重新生成依赖项，不能只在正文中改数字。

这是主要的反复改稿节点。用户可以连续提出多批意见，不必每次重新输入 `$medpaper`。流程会为每批意见建立持久化修订轮次，逐项记录验收条件，并按最早受影响阶段返工；回到 S19 后逐项核验、关闭该轮，再把新版本交给用户继续审核。上下文即使被压缩，也从修订状态文件继续，不会靠残缺的聊天记忆猜测。

1.8.1 起 S19 是子代理审阅轮次：每轮由只读 `medpaper-reviewer` 子代理审阅当前全文、表格（哈希绑定的文本副本）和图片，主代理自行采纳能提升质量的修改，然后一次性告诉用户发现了什么、改了哪些文件、哪些没改及原因，只问一个问题：是否再审一轮。不再生成审核 ZIP，也不逐条征求同意。

只有用户明确表示“无需继续审阅”，才记录 `NO_FURTHER_REVIEW`（绑定轮次编号）并进入 S20；轮次结束后若被审文件又变化，必须再审一轮，且不能用 `--force` 绕过。沉默、致谢、仅说“继续”都不算审核结束。

只有用户明确确认科学版本可以继续后，才开始选择期刊。此时仍不询问作者、单位、ORCID、基金或通讯信息。

输出：人工审核记录和确认。

### 第七部分：匹配期刊并制作投稿文件

#### S20｜选择现实可投的 SCIE 期刊

依据用户确认后的论文，查找近期发表过相近主题、设计和研究规模的期刊。候选期刊必须当前被 SCIE 收录、具有当前 JCR 分区，并且没有有效的预警、退稿诚信风险或重大出版质量问题。

工作流给出候选列表和退稿后的备选顺序，优先考虑研究匹配度和接受概率，而不是机械追求高影响因子。用户最终选择期刊后，流程保存官方投稿指南并冻结 Word 格式规则。

输出：期刊候选、目标期刊信息、官方指南摘要和 DOCX 样式配置。

#### S21｜最后才收集作者与行政信息

在科学内容和目标期刊都确定后，一次性向用户询问作者顺序、单位、ORCID、通讯作者、基金、利益冲突、伦理/知情同意、数据可用性、贡献声明等。缺失信息不会由 AI 猜测。

若期刊要求 title page 报告参考文献数量，流程会按完整正文中实际出现的、去重后的 citekey 自动计算并校准；不会把用于调研的 45–60 篇候选文献库总数误写成正文引用数。期刊未要求时，不会自行添加这一字段。

输出：作者信息、title page 和期刊所需声明。

#### S22｜按目标期刊进行事实不变的润色

调整英文、摘要结构、允许的小标题、拼写体系和篇幅，使其更符合目标期刊和医学论文表达。润色前后自动比较数字、引文和表图引用；任何科学事实变化都必须撤销或回到来源修正。

输出：润色后的全文和变更检查记录。

#### S23｜生成并检查投稿包

仅根据目标期刊明确要求生成需要上传的文件。正文、title page、cover letter、补充方法和其他叙述性材料均生成 Word 文件，不会只把正文转成 DOCX 而把其余内容留成 Markdown。

Word 样式优先采用官方投稿指南；若指南没有规定，默认使用 Times New Roman、12 pt、双倍行距、黑色文字。净化器会从所有 WordprocessingML 部件移除 `pageBreakBefore`、`outlineLvl` 和段落边框，`keepNext`/`keepLines`/`pageBreakBefore` 也从每个段落、表格单元格、题注、表注、图注和样式上全部移除（Word 会在带这些属性的段落前显示小黑方块；交付的 Word 不允许出现任何黑点，`docx_bundle_ready` 发现即失败）。版面靠结构保持：每张表单独成节、行不跨页（`cantSplit`）、表头跨页重复、表注紧随表格；每幅嵌入图另起一页、保持可读尺寸（至少占可用页高的 55%，或其原始尺寸），图注过长时续排到下一页而不是把图缩小；标题统一映射为基于正文样式的 `SectionHeading`，因而没有标题前小黑点、折叠三角形或可折叠大纲。文件同时移除超链接，统一同级标题字号，并拒绝字符 `↓` 和 Word 手动换行符。

正文必须有 References 标题，并且只能有一个 Figure legends 区标题；每幅图也只能出现一个对应图注标题，图注正文不得再次以 `Figure N` 开头。补充方法 DOCX 不允许包含表格或 Markdown 长横线残留，补充表只存在于单独的三线表工作簿中。如期刊要求，也可另交单独图注文件，但同一文件内仍不得重复标题。

所有 Word 文件都要经过结构检查和渲染后的视觉检查。若 title page 包含参考文献数量，Markdown 源文件和生成后的 DOCX 都必须与正文实际引用数量一致。图片、表格、补充材料、清单和 manifest 按目标期刊要求加入投稿包。

输出：完整投稿目录、DOCX 文件、图表、清单、manifest 和质量检查记录。

#### S24｜用户最终修改并确认投稿包

用户检查并可直接修改投稿包中的内容和格式。流程不会把“文件已交付”或之前对论文的确认当作对最终投稿包的确认，也不会盲目重建并覆盖用户编辑过的 DOCX。

投稿包中的内容修改必须同步回 Markdown、分析、表格或图片来源，并从对应阶段重新生成 Word。纯 Word 排版修改可以留在 S24，但系统会比较 S23 保存的可见文字哈希：只有文字完全不变时才视为纯排版；在 Word 中直接增删文字会阻止冻结和终审。

这里同样允许不限次数的反馈。涉及科学内容时仍自动返回真正的来源阶段；只涉及期刊格式时留在 S24。每轮修改都必须完成受影响文件重建、结构检查和视觉检查，再重新交给用户确认，不会因为前一轮已经确认过就跳过本轮验证。

修改完成后，重新检查改变的文件。流程会明确询问：

> 投稿包已按您的修改重新校验。是否确认 OK，并调用一个独立子代理，以普通读者和期刊编辑的视角终审当前冻结版本？

只有用户明确回答 OK、确认或可以，才冻结这一版投稿包。

输出：人工修改记录、明确确认和不可混淆的冻结版本。

#### S25｜独立子代理以读者、编辑和合规视角做最终审查

把用户确认并冻结的投稿包、目标期刊信息和官方投稿指南交给一个只读独立子代理。它先把自己当作没有后台信息的普通科学读者，找出看不懂的段落、术语、逻辑跳跃、图表或图注；再以期刊编辑视角检查错别字、语法、标点、残留模板、重复或遗漏文字、术语与格式不一致等低级错误；最后核对必需文件、文件名和格式、字数与参考文献限制、作者和声明、图表及补充材料编号、跨文件标题/数值/版本是否一致，以及仍需在投稿系统中人工完成的事项。

每条问题必须指出具体文件及页码、标题、段落、表格单元格或图版位置，并区分必须修改、轻微错误和纯偏好。独立子代理只报告，不直接编辑用户确认过的冻结文件。

只有审查得到 `PASS` 才完成流程；如为 `REVISE`，修改后回到 S24，让用户再次查看和确认新的冻结版本，避免在用户确认后暗中改变投稿包。

输出：独立投稿审查报告和最终 PASS/REVISE 结论。

## 在 Kiro 中如何启动

### 一次性安装

```powershell
Set-Location F:\workspace\medpaper_pipeline
python bootstrap.py
```

`bootstrap.py` 会建 `.venv`、装固定版本依赖、接线 Kiro 适配层（steering + 两个 hook + skill，同时装到用户级），然后跑 doctor 和回归测试。装完**重启 Kiro 或重载窗口**，让它读到 `.kiro/`。

设置检索需要的环境变量：

```powershell
[Environment]::SetEnvironmentVariable("NCBI_API_KEY", "<你的 key>", "User")
[Environment]::SetEnvironmentVariable("NCBI_API_EMAIL", "you@example.org", "User")
```

`NCBI_API_KEY` 把 PubMed 限速从 3 req/s 提到 10 req/s；`NCBI_API_EMAIL` 是 Unpaywall 抓全文的必需项。

### 日常使用

引擎目录只用于维护。新建论文后，把论文文件夹作为工作区在 Kiro 里打开：

```powershell
python tools/wf.py new sarcopenia-mortality   # 建 <论文根目录>/sarcopenia-mortality/ 并选中
python tools/wf.py papers                     # 列出所有论文及各自阶段
python tools/wf.py use other-paper            # 切换（用户级标记）
```

把研究思路文件放进该论文的 `00_input/`，在该论文工作区的 Kiro 对话里说：

```text
启动 medpaper 流水线，我的研究思路在 #00_input/idea.md
```

用 `#File` 附加文件，或直接拖进对话框。

`/` 输入 `medpaper` 能找到 skill，因为它同时装在用户级 `~/.kiro/skills/`，任意工作区都可见。用户级那份携带引擎绝对路径，所以在别的工作区激活时也知道 `tools/wf.py` 在哪。引擎搬位置后重跑 `python tools/install_adapters.py --global`。

同一对话里启动一次后，后续直接说"修改 Methods……""这版 Word 的标题格式不对"即可。磁盘上的阶段状态和活动修订轮次负责约束后续操作，不必每条消息重复触发。

### 两个 hook

| Hook | 触发 | 作用 |
|---|---|---|
| `medpaper-status` | SessionStart | 自动打印当前阶段、门禁状态、上次交接笔记 |
| `medpaper-skill-guard` | PreToolUse | 拒绝激活会替代阶段的技能（`write-paper`、`orchestrate`、`make-figures` 等） |

第二个很关键：steering 规则会在上下文压缩时被摘要掉，hook 不会。被 BLOCKED 的技能是真的激活不了。

```powershell
python tools/hooks/skill_guard.py --audit                # 59 个已装技能按档位列出
python tools/hooks/skill_guard.py --explain write-paper   # 看某条判定和理由
```

判定是数据不是散文，改 `reference/skill_policy.toml` 即可。

### 从任意目录调用

引擎目录之外用绝对路径，驱动会自动定位你所在的论文：

```powershell
python "F:/workspace/medpaper_pipeline/tools/wf.py" status
```

嫌长可以加个 PowerShell 函数（`notepad $PROFILE`）：

```powershell
function wf { python "F:/workspace/medpaper_pipeline/tools/wf.py" @args }
```

之后 `wf status`、`wf new my-paper`、`wf papers` 直接用。所有提示里的命令会跟随你的调用方式自动切换长短形式。

## 新项目与已有项目如何处理

- 新研究：`wf new <slug>` 后把研究想法和用户提供的材料放到该论文的 `00_input/`，由 S01 开始。
- 已有数据：先登记数据来源、变量说明和已有分析，再从仍未满足的最早阶段开始。
- 已有论文：工作流会识别哪些证据链和检查缺失，不会仅因已有 Word 文件就跳过数字、文献和图表校验。
- 中断后恢复：状态保存在项目磁盘中，重新运行 `wf.py status` 即可看到当前阶段、缺失文件和下一步。

常用命令：

```powershell
python tools\wf.py status
python tools\wf.py check
python tools\wf.py advance --note "本阶段完成了什么、做了什么决定、还有什么问题"
python tools\wf.py doctor
python tools\wf.py tree -v
.venv\Scripts\python.exe tools\selftest.py
```

日常使用时，研究者通常只需要在 Kiro 对话中描述任务和回答关键问题；这些命令主要用于安装、排错或人工检查流程状态。

## 主要文件放在哪里

阶段卡片中的 `project/` 是逻辑名称，指当前论文文件夹（在论文工作区根目录下显示时会自动去掉该前缀），不是引擎中的目录。

```text
project/00_input/       用户提供的研究想法、原始材料和后期作者信息
project/01_protocol/    可行性判断、研究方案、图表计划
project/02_data/        原始数据、衍生数据、变量字典和来源记录
project/03_analysis/    分析代码、机器可读结果、分析日志
project/04_tables/      主表和补充表
project/05_figures/     制图代码、图片、图注和质量检查
project/06_refs/        文献库、检索缓存、全文登记和深读笔记
project/07_manuscript/  各部分草稿、完整论文和审查记录
project/08_submission/  期刊选择、指南快照、Word 文件和最终投稿包
```

运行中的研究数据和生成结果永远不在引擎仓库中；每篇论文在论文根目录下单独存放（需要版本管理时在论文文件夹内单独 `git init`）。

## 文献、隐私与合规边界

- 学术全文只通过开放获取或用户明确授权的机构访问路径获取；不使用非法下载源。
- 文献发现插件只能提供候选项，不能直接成为正式参考文献的唯一依据。
- 正式引用必须通过新鲜 PubMed EFetch 原始 XML、内容哈希、当前文献库哈希，以及从 S13 到最终审计的重复独立实时复核；不能把 `verified` 布尔值、编译成功或门禁变绿当作文献真实的证据。
- 未经用户明确授权，不把患者级数据、私密文件、浏览器 cookie、API 密钥或个人联系信息发送到外部插件或服务。
- 作者身份、基金、伦理审批、利益冲突和数据可用性均由用户提供，工作流不自行推断。
- 本工具辅助研究组织、分析、写作和质量检查，不代替研究者、统计师、伦理机构、期刊编辑或法律/临床专业意见。

## 安装时的可选配置

PubMed/NCBI 检索可使用环境变量提高请求额度：

```powershell
$env:NCBI_API_KEY = "<你的 NCBI API key>"
$env:NCBI_API_EMAIL = "you@example.org"
```

不要把真实密钥或私人联系信息写入仓库。未配置 API key 时仍可使用公开访问速率。

## 代码结构

```text
.kiro/skills/medpaper-pipeline/SKILL.md    技能本体，也是用户级副本的源
.kiro/steering/medpaper-pipeline.md        inclusion: always，每个会话都在
.kiro/hooks/medpaper-status.json           SessionStart → wf status --brief
.kiro/hooks/medpaper-skill-guard.json      PreToolUse → 拦截会替代阶段的技能
pipeline/pipeline.toml                     阶段、输出和检查的唯一机器配置
pipeline/stages/                           25 个阶段的执行卡片
tools/wf.py、tools/wfcore/                  状态机和质量门（含 refproof / dataproof 防伪证据层）
tools/pubmed/                              文献元数据、引用和全文来源管理
tools/data_manifest.py                     数据全量获取清单，阻断静默抽样与截断
tools/tables/、tools/figures/               表格、图片生成与质量检查
tools/text/、tools/manuscript/              事实不变润色和确定性 Word 构建
tools/rework.py                            修改意见收集、封批、范围校验（默认不回卷）
tools/hooks/skill_guard.py                 技能仲裁执行器
tools/install_adapters.py                  接线 Kiro steering / hooks / skill
tools/figures/R/                           R 作图：medfig.R（save_medpaper、主题、配色）与 recipes.R
tools/R/medresults.R、tools/analysis/       R / Python 结果写出器（带环境回执）
tools/reproduce.py                         S06 沙箱重跑与复现证明
reference/                                 表图与 Methods 规范、图表原型、技能与能力仲裁策略
reference/language_policy.toml             Python/R 分工与必需 R 包
reference/reporting_guidelines.toml        报告规范条目清单
<论文根目录>/<slug>/                        每篇论文（独立 Kiro 工作区），状态在 .wf/
```

更具体的安装与故障排查见 `docs/INSTALL-KIRO.md`。机器读取的正式流程定义位于 `pipeline/pipeline.toml`；本 README 是给研究者和使用者阅读的说明，不作为流程引擎的配置文件。

