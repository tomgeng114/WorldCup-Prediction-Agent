# Phase 7.1 World Cup Data Coverage Report

## 范围

- 停止新模型、新回测、新 ROI 模块。
- 只采集 2026 世界杯 48 支球队真实数据。
- 禁止 mock、随机、赛后泄露数据。

## 输出文件

- CSV：E:\Tom\WorldCupAI2026\backend\data\world_cup_team_profiles.csv
- Coverage JSON：E:\Tom\WorldCupAI2026\backend\reports\coverage_report.json

## 覆盖率

- 总球队数：48
- 已完成球队数：0
- 球队完整覆盖率：0.0%
- 字段覆盖率：53.94%
- 90% 目标是否达到：False

## 数据源状态

- Transfermarkt 参赛队/身价/年龄/FIFA Ranking 行数：211
- Football-Data 近两年评级可用球队数：203
- ELO、coach、caps 本轮未找到稳定机器可读来源，保持缺失。

## 缺失字段明细

| 国家 | 大洲 | 已采字段数 | 缺失字段 |
|---|---|---:|---|
| Canada | CONCACAF | 4 | elo_rating, total_caps, average_caps, coach, recent_two_year_rating |
| Mexico | CONCACAF | 4 | elo_rating, total_caps, average_caps, coach, recent_two_year_rating |
| USA | CONCACAF | 4 | elo_rating, total_caps, average_caps, coach, recent_two_year_rating |
| Spain | UEFA | 5 | elo_rating, total_caps, average_caps, coach |
| Argentina | CONMEBOL | 5 | elo_rating, total_caps, average_caps, coach |
| France | UEFA | 5 | elo_rating, total_caps, average_caps, coach |
| England | UEFA | 5 | elo_rating, total_caps, average_caps, coach |
| Brazil | CONMEBOL | 5 | elo_rating, total_caps, average_caps, coach |
| Portugal | UEFA | 5 | elo_rating, total_caps, average_caps, coach |
| Netherlands | UEFA | 5 | elo_rating, total_caps, average_caps, coach |
| Belgium | UEFA | 5 | elo_rating, total_caps, average_caps, coach |
| Germany | UEFA | 5 | elo_rating, total_caps, average_caps, coach |
| Croatia | UEFA | 5 | elo_rating, total_caps, average_caps, coach |
| Morocco | CAF | 5 | elo_rating, total_caps, average_caps, coach |
| Colombia | CONMEBOL | 5 | elo_rating, total_caps, average_caps, coach |
| Uruguay | CONMEBOL | 5 | elo_rating, total_caps, average_caps, coach |
| Switzerland | UEFA | 5 | elo_rating, total_caps, average_caps, coach |
| Japan | AFC | 5 | elo_rating, total_caps, average_caps, coach |
| Senegal | CAF | 5 | elo_rating, total_caps, average_caps, coach |
| IR Iran | AFC | 5 | elo_rating, total_caps, average_caps, coach |
| Korea Republic | AFC | 5 | elo_rating, total_caps, average_caps, coach |
| Ecuador | CONMEBOL | 5 | elo_rating, total_caps, average_caps, coach |
| Austria | UEFA | 5 | elo_rating, total_caps, average_caps, coach |
| Australia | AFC | 5 | elo_rating, total_caps, average_caps, coach |
| Norway | UEFA | 5 | elo_rating, total_caps, average_caps, coach |
| Panama | CONCACAF | 5 | elo_rating, total_caps, average_caps, coach |
| Egypt | CAF | 5 | elo_rating, total_caps, average_caps, coach |
| Algeria | CAF | 5 | elo_rating, total_caps, average_caps, coach |
| Scotland | UEFA | 5 | elo_rating, total_caps, average_caps, coach |
| Paraguay | CONMEBOL | 5 | elo_rating, total_caps, average_caps, coach |
| Tunisia | CAF | 5 | elo_rating, total_caps, average_caps, coach |
| Cote d'Ivoire | CAF | 5 | elo_rating, total_caps, average_caps, coach |
| Uzbekistan | AFC | 5 | elo_rating, total_caps, average_caps, coach |
| Qatar | AFC | 5 | elo_rating, total_caps, average_caps, coach |
| Saudi Arabia | AFC | 5 | elo_rating, total_caps, average_caps, coach |
| South Africa | CAF | 5 | elo_rating, total_caps, average_caps, coach |
| Jordan | AFC | 5 | elo_rating, total_caps, average_caps, coach |
| Cabo Verde | CAF | 5 | elo_rating, total_caps, average_caps, coach |
| Ghana | CAF | 5 | elo_rating, total_caps, average_caps, coach |
| Curacao | CONCACAF | 5 | elo_rating, total_caps, average_caps, coach |
| Haiti | CONCACAF | 5 | elo_rating, total_caps, average_caps, coach |
| New Zealand | OFC | 5 | elo_rating, total_caps, average_caps, coach |
| Czechia | UEFA | 4 | elo_rating, total_caps, average_caps, coach, recent_two_year_rating |
| Bosnia and Herzegovina | UEFA | 4 | fifa_ranking, elo_rating, total_caps, average_caps, coach |
| Turkiye | UEFA | 4 | elo_rating, total_caps, average_caps, coach, recent_two_year_rating |
| Sweden | UEFA | 5 | elo_rating, total_caps, average_caps, coach |
| DR Congo | CAF | 4 | elo_rating, total_caps, average_caps, coach, recent_two_year_rating |
| Iraq | AFC | 5 | elo_rating, total_caps, average_caps, coach |