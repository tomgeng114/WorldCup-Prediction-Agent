# Phase 7 World Cup Specialist Full Report

## 范围

- 只针对世界杯正赛。
- 不优化五大联赛、不优化预选赛、不以跨赛事 ROI 为主要目标。
- 不生成 mock 数据；首发、伤病、身价、年龄、国家队经验等必须来自 `world_cup_team_profiles`。
- 长期规划规模：48 支球队，104 场比赛。

## 2026 球队画像覆盖率

- 总球队数：48
- 预期球队数：48
- 已完成球队数：0
- 覆盖率：0.0%
- 缺失字段数量：576

### 按大洲统计

| 大洲 | 球队数 | 已完成 | 缺失字段数 |
|---|---:|---:|---:|
| UEFA | 16 | 0 | 192 |
| CONMEBOL | 6 | 0 | 72 |
| AFC | 9 | 0 | 108 |
| CAF | 10 | 0 | 120 |
| CONCACAF | 6 | 0 | 72 |
| OFC | 1 | 0 | 12 |

## 球队实力评分

- `world_cup_strength_score` 输出 0-100。
- 组成：ELO、FIFA Ranking、Squad Value、National Team Experience、World Cup History、Recent Form。
- 缺失组件不参与计算，并记录到缺失字段。

## 冷门预警模型

- `upset_alert_score` 输出 Low / Medium / High。
- 亚洲、非洲、中北美、OFC 以及南美非传统强队会被重点关注。

## 世界杯模拟能力

- 状态：insufficient_data
- 原因：需要 48 支球队画像和完整小组赛赛程后才能进行真实模拟；当前不生成 mock 赛程。
- 当前球队画像：48
- 当前小组赛赛程：0

## 2018/2022 世界杯专项回测

- 回测样本：128
- 胜平负命中率：48.44%
- 平局命中率：0.0%
- 比分命中率：14.06%
- Brier Score：0.6297
- 是否优于当前 55.47%：当前没有 2018/2022 专项画像数据，不能声称专项模型已优于 55.47%。

## 已支持输出

- 48 队世界杯球队画像库
- 世界杯专用预测概率
- 世界杯专用比分模型
- 世界杯专用冷门预警
- 球队画像覆盖率报告
- 世界杯模拟接口，等待完整小组赛赛程后启用真实 Monte Carlo

## 2026 球队缺失字段明细

| 国家 | 大洲 | 强度评分 | 冷门等级 | 缺失字段数 |
|---|---|---:|---|---:|
| Australia | AFC | None | Medium | 12 |
| IR Iran | AFC | None | Medium | 12 |
| Iraq | AFC | None | Medium | 12 |
| Japan | AFC | None | Medium | 12 |
| Jordan | AFC | None | Medium | 12 |
| Korea Republic | AFC | None | Medium | 12 |
| Qatar | AFC | None | Medium | 12 |
| Saudi Arabia | AFC | None | Medium | 12 |
| Uzbekistan | AFC | None | Medium | 12 |
| Algeria | CAF | None | Medium | 12 |
| Cabo Verde | CAF | None | Medium | 12 |
| Cote d'Ivoire | CAF | None | Medium | 12 |
| DR Congo | CAF | None | Medium | 12 |
| Egypt | CAF | None | Medium | 12 |
| Ghana | CAF | None | Medium | 12 |
| Morocco | CAF | None | Medium | 12 |
| Senegal | CAF | None | Medium | 12 |
| South Africa | CAF | None | Medium | 12 |
| Tunisia | CAF | None | Medium | 12 |
| Canada | CONCACAF | None | Medium | 12 |
| Curacao | CONCACAF | None | Medium | 12 |
| Haiti | CONCACAF | None | Medium | 12 |
| Mexico | CONCACAF | None | Medium | 12 |
| Panama | CONCACAF | None | Medium | 12 |
| USA | CONCACAF | None | Medium | 12 |
| Argentina | CONMEBOL | None | Low | 12 |
| Brazil | CONMEBOL | None | Low | 12 |
| Colombia | CONMEBOL | None | Medium | 12 |
| Ecuador | CONMEBOL | None | Medium | 12 |
| Paraguay | CONMEBOL | None | Medium | 12 |
| Uruguay | CONMEBOL | None | Low | 12 |
| New Zealand | OFC | None | Medium | 12 |
| Austria | UEFA | None | Low | 12 |
| Belgium | UEFA | None | Low | 12 |
| Bosnia and Herzegovina | UEFA | None | Low | 12 |
| Croatia | UEFA | None | Low | 12 |
| Czechia | UEFA | None | Low | 12 |
| England | UEFA | None | Low | 12 |
| France | UEFA | None | Low | 12 |
| Germany | UEFA | None | Low | 12 |
| Netherlands | UEFA | None | Low | 12 |
| Norway | UEFA | None | Low | 12 |
| Portugal | UEFA | None | Low | 12 |
| Scotland | UEFA | None | Low | 12 |
| Spain | UEFA | None | Low | 12 |
| Sweden | UEFA | None | Low | 12 |
| Switzerland | UEFA | None | Low | 12 |
| Turkiye | UEFA | None | Low | 12 |
