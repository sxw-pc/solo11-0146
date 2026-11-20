# 志愿活动履约采集台

离线合成的公益岗位公告、技能凭证和现场签到证据工程。它决定人员派工、可记服务分钟与缺岗责任，不保存真实身份资料或连接公益平台。

## 运行

Python 3.11+，在仓库根目录：

```powershell
python -m pip install . --no-build-isolation --no-deps
$env:PYTHONPATH=(Resolve-Path -LiteralPath src).Path
python -m volunteer demo --db data/demo.sqlite
python -m unittest discover -s tests -v
```

三个子系统可分别采录：

```powershell
python -m volunteer import-call --db data/demo.sqlite --input fixtures/volunteer/call_good.json
python -m volunteer import-skill --db data/demo.sqlite --input fixtures/volunteer/skill_good.json
python -m volunteer import-attendance --db data/demo.sqlite --input fixtures/volunteer/attend_good.json
python -m volunteer report --db data/demo.sqlite --as-of 2026-11-17T12:30:00Z
```

岗位账保存公告版次、名额、截止时点和报名承诺；缩员使后位人员转候补，并归为组织责任。资格账按发行主体、技能、有效期和撤销裁定特殊岗位派工。现场账按站点、班次窗口和主管独立审批结算分钟，同一人跨班重叠时段只计一次。三个决定各自持久化，报告从原始事件按查询时点重算。

## 受益人结果评估

第四个子系统采录三种离线合成原件，供两份签约口径各自评估：

```powershell
python -m volunteer import-beneficiary --db data/demo.sqlite --input fixtures/volunteer/invite_frozen.json
python -m volunteer import-beneficiary --db data/demo.sqlite --input fixtures/volunteer/delivery_dual.json
python -m volunteer import-beneficiary --db data/demo.sqlite --input fixtures/volunteer/survey_complete.json
python -m volunteer import-beneficiary --db data/demo.sqlite --input fixtures/volunteer/contracts_two.json
python -m volunteer report --db data/demo.sqlite --as-of 2026-11-17T18:00:00Z
```

报名与派工前冻结的家庭随机邀请清单（`invite`，`frozen_at` 早于任何报名/到场/交付业务时间，否则拒收）、家庭与志愿者双方签认的实际服务交付单（`delivery`）、独立调查员的结果问卷（`questionnaire`），以及冻结识别假设的评估合同（`contract`）。各原件在 evidence 表留摘要与采录时间，在自有表留业务时间与版本；同一家庭跨表只用冻结随机编号，同版异值或跨表身份冲突一律留争议，不按导入顺序择一。分组只读冻结清单，不从签到、资格或问卷完成情况倒推；多次交付按合同暴露定义 `any_confirmed_delivery` 只计一次暴露。问卷缺失、拒访、跨组接受服务、交付单冲突分别标记，零结果与未观察不混同。

报告同时给出分组人数、实际交付人数、已观察结果人数与假设检查。合同一 `invite_policy` 按冻结原始分组计算意向治疗效应（ITT），不删去未到岗志愿者对应的家庭。合同二 `complier_effect` 仅在随机分组、单调依从且排除直接邀请效应、无跨家庭干扰三项假设签约时冻结并标为不能由本批数据证明、随访完整且第一阶段非零时，按"邀请对结果的差 ÷ 邀请对交付率的差"估计依从家庭效应；任一条件不满足（含资格被视为干预先决条件且存在资格争议）即转待核，绝不以零为分母，也不把仅接受服务者与未接受者的均值差冒充因果效应。凭证撤销使 hours 冻结并呈现资格争议，但不能凭 hours=0 删除家庭双签证实的交付。迟到的交付单按原分组重算并保留旧报告历史，报告给出原始记录、估计分子分母、冲突原因与前后版本。

## 边界样例

`call_changed.json` 把名额从 2 缩为 1，第二人变候补而非无故缺岗。`skill_expired.json` 撤销第一人的特殊岗位凭证，其已签到但未结算的时数冻结，第二人时数不受影响。`attend_overlap.json` 的场外时间不计入班次；测试还覆盖错站、自签、跨班次重叠、截止后报名、组织取消与志愿者缺岗责任区分。

事件 ID 同内容幂等，异内容拒绝整批；原始 JSON 和 SHA-256 留在 SQLite。`src/volunteer/store.py` 幂等初始化；未来修改表结构应迁移旧证据，不删除报告历史。未实现的方向见 `docs/initial-requirements.md`。
