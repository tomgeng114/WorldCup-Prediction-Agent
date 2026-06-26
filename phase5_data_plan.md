# Phase 5 数据源审计计划

审计日期：2026-06-10

审计范围：Football-Data.co.uk 是否可用于扩展 Value Bet Engine 的历史样本。

本阶段只做数据源审计，不导入数据、不修改数据库、不生成模拟样本。

## 结论摘要

Football-Data.co.uk 的主下载页主要提供欧洲国家联赛历史数据，并明确包含赛果、赛前 1X2 赔率、大小球赔率和亚洲让球赔率字段。但对本阶段要求的国际赛事，公开页面中没有发现欧洲杯、欧国联、美洲杯的独立历史数据文件。

唯一可用于本阶段目标赛事扩展的数据源是 `WorldCup2026.xlsx`，其中包含 `WorldCup2026Qualifiers` 工作表。该表可覆盖世界杯预选赛的一部分，且包含赛果和赛前 1X2 平均/最高赔率，但不包含让球赔率字段。

在 `WorldCup2026Qualifiers` 中按球队归属二次分类后：

- 世界杯欧洲区预选赛：204 场
- 世界杯南美区预选赛：90 场
- 其它赛区或混合预选赛：595 场
- 全部世界杯 2026 预选赛：889 场

当前 Phase 5 按用户指定赛事可扩展样本量预计为 294 场，即欧洲区 204 场 + 南美区 90 场。

如后续扩大到全部世界杯预选赛，可扩展样本量预计为 889 场。

## 审计依据

公开页面：

- Football-Data 主数据页：https://www.football-data.co.uk/data.php
- Football-Data 下载页：https://www.football-data.co.uk/downloadm.php
- Football-Data 字段说明：https://www.football-data.co.uk/notes.txt
- WorldCup2026 文件：https://www.football-data.co.uk/WorldCup2026.xlsx

页面说明要点：

- `data.php` 说明历史数据主要覆盖欧洲联赛。
- `downloadm.php` 的公开下载链接为欧洲国家联赛赛季包，以及 `WorldCup2026.xlsx`。
- `notes.txt` 明确标准 Football-Data 文件包含赛果字段、赛前 1X2 赔率字段、大小球赔率字段和亚洲让球赔率字段。
- `WorldCup2026.xlsx` 实际包含工作表：`WorldCup2026Qualifiers`、`WorldCup2022`、`WorldCup2018`、`WorldCup2014`。

## 赛事逐项审计

| 赛事 | 是否可获取 | 数据覆盖年份 | 比赛数量 | 是否包含赛果 | 是否包含赛前 1X2 赔率 | 是否包含让球赔率 | 下载地址 | 审计结论 |
|---|---:|---:|---:|---:|---:|---:|---|---|
| 欧洲杯 | 否 | 无公开文件 | 0 | 否 | 否 | 否 | 无 | Football-Data.co.uk 公开下载页未发现 Euro / European Championship 历史文件。常见文件名探测如 `Euro2024.xlsx`、`Euro2020.xlsx`、`EuropeanChampionship.xlsx` 均不可用。 |
| 欧国联 | 否 | 无公开文件 | 0 | 否 | 否 | 否 | 无 | 公开下载页未发现 UEFA Nations League / Nations League 文件。常见文件名探测如 `NationsLeague.xlsx`、`UEFANationsLeague.xlsx` 均不可用。 |
| 世界杯欧洲区预选赛 | 是 | 2025-2026 | 204 | 是 | 是 | 否 | https://www.football-data.co.uk/WorldCup2026.xlsx | `WorldCup2026Qualifiers` 可按欧洲球队名单筛出 UEFA 对阵。字段包含 `HG`、`AG`、`H_Max`、`D_Max`、`A_Max`、`H_Avg`、`D_Avg`、`A_Avg`。未发现亚洲让球字段。 |
| 世界杯南美区预选赛 | 是 | 2023-2025 | 90 | 是 | 是 | 否 | https://www.football-data.co.uk/WorldCup2026.xlsx | `WorldCup2026Qualifiers` 可按 CONMEBOL 10 队筛出南美区对阵。字段包含赛果和赛前 1X2 赔率。未发现亚洲让球字段。 |
| 美洲杯 | 否 | 无公开文件 | 0 | 否 | 否 | 否 | 无 | 公开下载页未发现 Copa America 文件。常见文件名探测如 `CopaAmerica.xlsx`、`CopaAmerica2024.xlsx` 均不可用。 |

## WorldCup2026.xlsx 字段检查

`WorldCup2026Qualifiers` 工作表字段：

```text
Date
Home
Away
HG
AG
H_Max
D_Max
A_Max
H_Avg
D_Avg
A_Avg
HS
AS
HST
AST
HF
AF
HC
AC
HY
AY
HR
AR
HxG
AxG
```

字段解释：

- `Date`：比赛日期
- `Home` / `Away`：主队 / 客队
- `HG` / `AG`：全场主队进球 / 客队进球
- `H_Max` / `D_Max` / `A_Max`：主胜 / 平局 / 客胜最高赔率
- `H_Avg` / `D_Avg` / `A_Avg`：主胜 / 平局 / 客胜平均赔率
- `HS` / `AS`、`HST` / `AST`、`HF` / `AF`、`HC` / `AC`、`HY` / `AY`、`HR` / `AR`：比赛技术统计
- `HxG` / `AxG`：主队 / 客队 xG

未发现让球字段，例如：

- `AHh`
- `MaxAHH`
- `MaxAHA`
- `AvgAHH`
- `AvgAHA`
- `B365AHH`
- `B365AHA`

因此，世界杯预选赛数据可用于胜平负 Value Bet 回测，但不能直接用于让球盘回测。

## 样本量估算

### 用户指定赛事可扩展样本

| 分类 | 可用样本 |
|---|---:|
| 欧洲杯 | 0 |
| 欧国联 | 0 |
| 世界杯欧洲区预选赛 | 204 |
| 世界杯南美区预选赛 | 90 |
| 美洲杯 | 0 |
| 合计 | 294 |

### 额外可选样本

| 分类 | 可用样本 |
|---|---:|
| WorldCup2026Qualifiers 全部赛区 | 889 |
| 其中非 UEFA / CONMEBOL 或混合赛区 | 595 |

## 建议

1. Phase 5 第一批可导入目标应只选择 `WorldCup2026Qualifiers` 中的欧洲区和南美区，共 294 场。

2. 由于该数据源没有让球赔率，Phase 5 只能验证胜平负 Value Bet ROI，不能验证让球 Value Bet ROI。

3. 欧洲杯、欧国联、美洲杯需要另找数据源，例如 OddsPortal 动态历史页、Kaggle、FBref、Statbunker、worldfootball.net 或赛事官方数据源。不能用 Football-Data.co.uk 的欧洲联赛数据替代这些赛事。

4. 后续导入前需要建立一张通用国际赛事表，避免继续把所有扩展赛事塞进 `world_cup_matches`。建议字段至少包括：

```text
competition
season
stage
match_date
home_team
away_team
home_score
away_score
result
home_win_odds
draw_odds
away_win_odds
odds_source
has_handicap_odds
```

5. Value Bet 稳定性验证应分赛事单独报告，不应把世界杯、欧洲区预选赛、南美区预选赛混成一个总体 ROI 后直接下结论。

