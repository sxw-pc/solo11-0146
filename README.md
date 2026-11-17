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

## 边界样例

`call_changed.json` 把名额从 2 缩为 1，第二人变候补而非无故缺岗。`skill_expired.json` 撤销第一人的特殊岗位凭证，其已签到但未结算的时数冻结，第二人时数不受影响。`attend_overlap.json` 的场外时间不计入班次；测试还覆盖错站、自签、跨班次重叠、截止后报名、组织取消与志愿者缺岗责任区分。

事件 ID 同内容幂等，异内容拒绝整批；原始 JSON 和 SHA-256 留在 SQLite。`src/volunteer/store.py` 幂等初始化；未来修改表结构应迁移旧证据，不删除报告历史。未实现的方向见 `docs/initial-requirements.md`。
