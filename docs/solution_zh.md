# KOLClaw AI 实习生测试说明文档

## 1. 交付概览

本方案选择 **Task 1: KOLClaw 达人主页分析 MVP** 和 **Task 2: 达人库多维度动态知识库设计**。两者可以形成一条完整 MVP 链路：先从达人主页抓取公开信息，再用 LLM 做 structured extraction，最后将结果沉淀到 creator database 中，为后续 brief matching、建联跟进、风险记录和人工判断复用。

本仓库包含一个 1-2 天可完成的最小 demo：

- `FastAPI` 提供 `POST /analyze-profile` 和 `POST /match-brief`
- `Playwright` 抓取公开网页信息
- 当前环境未安装 `Playwright` 时，会 fallback 到标准库 HTTP/HTML extractor，用于简单公开页面的 demo
- `SQLite` 存储达人信息、内容样本、tags、风险记录等
- LLM prompt 使用英文，但要求输出中文内容，并严格保留英文 JSON keys
- 未配置 LLM API 时使用 mock analyzer，保证 demo 可运行
- 对小红书页面增加了轻量 profile-section parsing：优先使用可见主页区域里的 bio 和 stats，`meta_description` 只作为 fallback；同时过滤 footer/legal/navigation 噪声和非笔记链接。

## 2. Task 1: 达人主页分析 MVP

### 2.1 目标

输入一个 `profile_url`，自动抓取页面信息，并输出结构化达人信息 JSON。字段如下：

```json
{
  "platform": "",
  "profile_url": "",
  "nickname": "",
  "bio": "",
  "follower_count": "",
  "content_categories": [],
  "recent_post_titles": [],
  "recent_post_links": [],
  "brand_fit_tags": [],
  "risk_flags": [],
  "summary": ""
}
```

JSON keys 使用英文，字段值以中文为主。例如 `content_categories` 可输出 `["时尚穿搭", "生活方式"]`，`risk_flags` 可输出 `["页面公开信息较少，需要人工复核"]`。

API 默认成功响应直接返回上述达人 JSON，不包裹 `status`、`creator`、`raw_extraction`、`message` 或 `manual_verification_required`。只有当请求传入 `debug=true` 时，才返回包含 `creator`、`raw_extraction` 和 analyzer metadata 的调试包装结构；`raw_extraction` 仅用于排查抓取质量，不作为正式交付输出。调试字段包括 `analysis_source`、`llm_provider`、`llm_model` 和 `api_key_detected`，用于确认当前走的是 real LLM、mock 还是 rule-based fallback。

### 2.2 页面信息抓取方式

MVP 使用 `Playwright` 打开页面并抽取：

- `page.title()` 作为 nickname 的候选来源
- `meta[name="description"]` 作为 bio 的候选来源
- `body.innerText` 作为 raw text
- 页面内前 80 个 `a` 标签，去重后作为 recent post links / titles 候选
- 根据 hostname 判断 platform，例如 `instagram`, `tiktok`, `youtube`, `xiaohongshu`, `douyin`, `bilibili`，无法识别时标记为 `website`

生产环境可继续增强：

- 为 TikTok / Instagram / YouTube / 小红书 / 抖音分别写 platform adapter
- 对 follower count、post count、engagement 等字段做 DOM selector + regex 双重解析
- 保存 HTML snapshot、screenshot、cookies 和抓取日志，便于异常复盘

### 2.3 页面需要 login 时如何处理

如果页面出现 `log in`, `sign in`, `登录` 等文本，系统会认为页面可能需要 login。MVP 的默认策略是：

- 不自动绕过登录
- 返回 `manual_verification_required`
- 保留 raw extraction，提示用户用 `manual_verification=true` 重新运行

生产环境应使用账号池和 session 管理，但必须遵守平台规则。更合理的方式是为运营同事提供一个 operator queue：系统发现需要登录时，将任务挂起，由人工在合规账号环境中完成登录后继续。

### 2.4 遇到 CAPTCHA / 人机验证如何暂停

MVP 会检测 `captcha`, `verify you are human`, `人机验证`, `验证码` 等关键词。若请求设置 `manual_verification=true`：

1. `Playwright` 启动 headed Chromium
2. 页面保持打开
3. 服务端 terminal 输出提示
4. 人工完成 CAPTCHA 或登录
5. terminal 按 Enter
6. 抓取流程 resume，再次读取页面内容

这个机制足够展示 pause/resume 思路。生产环境应将 browser context、任务状态、cookie 和 operator action 持久化，不应依赖 terminal input。

### 2.5 如何把非结构化信息交给 LLM

抓取结果会先被压缩成 compact raw data：

```json
{
  "platform": "website",
  "profile_url": "https://example.com",
  "title": "...",
  "meta_description": "...",
  "visible_text": "...",
  "recent_post_titles": ["..."],
  "recent_post_links": ["..."],
  "detection_reasons": []
}
```

Prompt 使用英文描述任务，降低格式歧义，但要求模型输出中文内容：

```text
Return ONLY valid JSON. Use exactly the required English keys.
All descriptive values must be written in Chinese.
If a field is unknown, use "" for strings, [] for arrays, or "unknown" for follower_count.
Do not invent facts.
```

LLM 输出后用 `Pydantic` schema 校验，避免字段缺失或类型错误。生产环境还应加入 JSON repair、字段置信度、人工复核状态和 prompt version。

## 3. Task 2: 达人库多维度动态知识库设计

### 3.1 设计目标

达人库不能只是 Excel，需要支持动态更新和多角色协作：

- account / 媒介同事持续新增达人
- 同一个达人可有多个 platform accounts
- 每个达人可积累内容样本、表现数据、brand-fit tags、风险记录
- 每次 brief selection 都要沉淀选中、待定、拒绝及原因
- 建联状态要可追踪
- LLM matching 和人工判断都要可回溯

Demo 使用 `SQLite`，production 建议使用 `PostgreSQL + pgvector` 或 PostgreSQL + external vector database。

### 3.2 核心表结构

#### creators

达人主表。

| Field | Type | Description |
| --- | --- | --- |
| id | integer | primary key |
| nickname | text | 达人名称 |
| bio | text | 达人简介 |
| summary | text | LLM 生成的达人摘要 |
| created_at | timestamp | 创建时间 |
| updated_at | timestamp | 更新时间 |

#### platform_accounts

多平台账号表，一个 creator 可以对应多个账号。

| Field | Type | Description |
| --- | --- | --- |
| id | integer | primary key |
| creator_id | integer | FK to creators |
| platform | text | 平台，如 tiktok / instagram / xiaohongshu |
| profile_url | text | 主页链接，唯一 |
| follower_count | text | 粉丝数，MVP 用 text 保留原始表达 |
| account_status | text | active / unavailable / private |
| raw_json | text | 抓取和 LLM 分析原始 JSON |

#### content_samples

内容样本表。

| Field | Type | Description |
| --- | --- | --- |
| id | integer | primary key |
| creator_id | integer | FK to creators |
| platform_account_id | integer | FK to platform_accounts |
| title | text | 内容标题 |
| content_url | text | 内容链接 |
| category | text | 内容分类 |

#### creator_tags

标签表，用于内容分类和 brand fit。

| Field | Type | Description |
| --- | --- | --- |
| id | integer | primary key |
| creator_id | integer | FK to creators |
| tag_type | text | content_category / brand_fit / audience / style |
| tag_value | text | 标签值 |
| source | text | llm / manual / rule |

#### performance_metrics

表现数据表。

| Field | Type | Description |
| --- | --- | --- |
| id | integer | primary key |
| creator_id | integer | FK to creators |
| platform_account_id | integer | FK to platform_accounts |
| metric_name | text | follower_count / avg_views / engagement_rate |
| metric_value | text | 指标值 |
| metric_period | text | 时间窗口 |
| source | text | scraper / manual / third_party |

#### selection_records

选号记录表，用于记录每次 brief 下的判断。

| Field | Type | Description |
| --- | --- | --- |
| id | integer | primary key |
| creator_id | integer | FK to creators |
| brand_brief | text | brief 内容 |
| decision_status | text | hired / pending / rejected |
| decision_reason | text | 录用、待定或拒绝原因 |
| operator_name | text | 操作人 |
| llm_score | real | LLM 评分 |
| manual_score | real | 人工评分 |

#### outreach_records

建联状态表。

| Field | Type | Description |
| --- | --- | --- |
| id | integer | primary key |
| creator_id | integer | FK to creators |
| channel | text | email / dm / agency / wechat |
| contact_status | text | not_contacted / contacted / replied / negotiating / lost |
| next_action | text | 下一步动作 |
| owner_name | text | 负责人 |
| notes | text | 备注 |

#### risk_records

风险记录表。

| Field | Type | Description |
| --- | --- | --- |
| id | integer | primary key |
| creator_id | integer | FK to creators |
| risk_type | text | profile_analysis / content / brand_safety |
| severity | text | low / medium / high |
| description | text | 风险描述 |
| source | text | llm / manual / rule |

### 3.3 表关系

- `creators 1:N platform_accounts`
- `creators 1:N content_samples`
- `creators 1:N creator_tags`
- `creators 1:N performance_metrics`
- `creators 1:N selection_records`
- `creators 1:N outreach_records`
- `creators 1:N risk_records`
- `platform_accounts 1:N content_samples`
- `platform_accounts 1:N performance_metrics`

这样设计的核心原因是：达人是主实体，平台账号、内容、表现、建联、风险和选号记录都是围绕达人持续增长的数据资产。

### 3.4 如何支持 LLM brief matching

MVP 中 `POST /match-brief` 使用 rule-based matching：对 `brand_brief`、summary、bio、content categories、brand fit tags 做 token overlap，并对 risk flags 做扣分。

生产环境可以升级为三阶段：

1. **Recall**：用 tags、category、platform、follower range、risk severity 做 SQL filter
2. **Semantic matching**：对 creator summary、content samples、manual notes 生成 embedding，用 vector search 找候选
3. **LLM scoring**：只对 Top N 候选调用强模型，输出 fit score、reason、risk explanation 和 recommended action

这样能控制成本，也能避免对全量达人重复调用强模型。

### 3.5 如何沉淀人工判断

媒介同事的判断应作为一等数据，而不是备注散落在 Excel 中：

- `selection_records.decision_status` 记录 hired / pending / rejected
- `selection_records.decision_reason` 记录拒绝或录用原因
- `selection_records.manual_score` 记录人工评分
- `creator_tags.source = manual` 保存人工标签
- `risk_records.source = manual` 保存人工发现的风险
- `outreach_records` 保存建联状态和下一步动作

后续可以把这些人工判断用于 prompt context、few-shot examples、规则优化和模型评估。

## 4. Bonus: 10 RMB 内的模型路由和成本优化

一次完整 KOLClaw 执行不应该所有环节都调用强模型。推荐模型路由如下：

- **规则层**：URL 去重、platform 识别、登录/CAPTCHA 检测、字段清洗、明显风险关键词、重复达人判断，全部用 rule-based 处理。
- **小模型层**：主页 raw text 的初步分类、tag extraction、summary compression、低风险 brief matching 初筛，用小模型或便宜模型处理。
- **强模型层**：只用于 Top N 候选的最终 fit reasoning、复杂风险判断、多维 tradeoff explanation。
- **Token reduction**：只传 title、meta description、核心 visible text、recent links，不传完整 HTML；长文本先 compression，再进入 matching。
- **Cache**：以 `profile_url + page_hash + prompt_version` 做缓存。页面未变化时不重复分析。
- **Batching**：多个内容样本可批量分类，多个达人可批量做 tag normalization。
- **Deduplication**：同一达人跨平台或同 URL 重复提交时，复用已有 creator profile 和 embedding。
- **Human-in-the-loop**：低置信度结果进入人工复核，避免用强模型反复尝试解决数据缺失问题。

实际预算控制策略是：80% 以上请求走规则和小模型；只有最终候选和高价值 brief 使用强模型。这样比全链路强模型调用更稳定，也更容易压到 10 RMB 以内。

## 5. 最适合参与的产品线

我认为自己最适合参与 **KOLClaw** 方向。原因是这个方向同时需要 scraping、LLM structured extraction、creator database、brief matching 和 human-in-the-loop workflow，既有工程实现难度，也有明确的业务闭环。相比单纯做内容生成，KOLClaw 更需要把非结构化数据转成可复用的数据资产，并让 account 和媒介同事在真实工作流中持续沉淀判断，这正是本 demo 重点展示的能力。

## 6. Demo 使用说明

运行 API：

```bash
uvicorn app.main:app --reload
```

分析主页：

```bash
curl -X POST http://127.0.0.1:8000/analyze-profile \
  -H "Content-Type: application/json" \
  -d '{"profile_url":"https://example.com","brand_brief":"适合年轻女性的轻运动服饰品牌"}'
```

匹配 brief：

```bash
curl -X POST http://127.0.0.1:8000/match-brief \
  -H "Content-Type: application/json" \
  -d '{"brand_brief":"寻找运动健康和生活方式达人","limit":5}'
```
