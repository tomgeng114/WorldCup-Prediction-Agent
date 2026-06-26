# Phase 8 World Cup Monte Carlo Simulation Report

## Simulation Scope

- Simulations: 10000
- pre_draw_simulation: False
- real_schedule_simulation: True
- Schedule source: https://www.zoho.com/toolkit/fifa-world-cup-2026.html
- Input: 48 teams and `world_cup_strength_score`.
- Fixture policy: parse the published 2026 group stage and knockout path; no fabricated schedule fallback.
- Format: 12 groups of 4, top 2 plus 8 best third-place teams to Round of 32.
- Group stage fixtures parsed: 72
- Knockout fixtures used: 31

## Groups

- Group A: Mexico, South Africa, Korea Republic, Czechia
- Group B: Canada, Bosnia and Herzegovina, Switzerland, Qatar
- Group C: Brazil, Morocco, Scotland, Haiti
- Group D: USA, Paraguay, Australia, Turkiye
- Group E: Germany, Ecuador, Cote d'Ivoire, Curacao
- Group F: Netherlands, Japan, Tunisia, Sweden
- Group G: Belgium, IR Iran, Egypt, New Zealand
- Group H: Spain, Cabo Verde, Saudi Arabia, Uruguay
- Group I: France, Senegal, Iraq, Norway
- Group J: Argentina, Algeria, Austria, Jordan
- Group K: Portugal, Colombia, Uzbekistan, DR Congo
- Group L: England, Croatia, Panama, Ghana

## Top 20 Champion Probability

| Rank | Team | Strength | Champion | Final | Semi Final | Quarter Final | Round of 16 | Round of 32 |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | Spain | 98.28 | 15.81% | 24.35% | 37.9% | 50.72% | 71.52% | 97.91% |
| 2 | France | 97.1 | 13.63% | 21.89% | 34.67% | 50.75% | 72.8% | 93.2% |
| 3 | England | 96.38 | 12.69% | 20.71% | 32.23% | 48.71% | 71.72% | 94.67% |
| 4 | Argentina | 95.27 | 10.8% | 18.62% | 30.33% | 45.64% | 62.93% | 94.04% |
| 5 | Portugal | 90.95 | 5.63% | 11.53% | 21.45% | 37.57% | 61.45% | 91.37% |
| 6 | Netherlands | 90.24 | 4.56% | 9.34% | 18.57% | 35.85% | 56.28% | 90.42% |
| 7 | Germany | 89.41 | 4.02% | 8.67% | 16.86% | 30.28% | 57.94% | 92.44% |
| 8 | Croatia | 88.56 | 3.55% | 7.85% | 15.57% | 28.73% | 54.68% | 87.84% |
| 9 | Brazil | 88.3 | 3.2% | 6.98% | 14.62% | 29.75% | 51.71% | 90.78% |
| 10 | Norway | 87.23 | 2.83% | 6.4% | 13.36% | 26.99% | 49.9% | 80.55% |
| 11 | Morocco | 86.95 | 2.7% | 6.17% | 12.86% | 27.01% | 48.69% | 88.62% |
| 12 | Turkiye | 86.46 | 2.61% | 6.09% | 13.42% | 29.73% | 54.1% | 84.01% |
| 13 | Belgium | 86.38 | 2.57% | 6.45% | 14.25% | 30.98% | 57.62% | 90.5% |
| 14 | Japan | 85.97 | 2.23% | 5.41% | 12.06% | 25.0% | 44.94% | 85.06% |
| 15 | Switzerland | 84.6 | 2.12% | 5.53% | 12.95% | 29.03% | 58.96% | 93.69% |
| 16 | Colombia | 85.68 | 2.1% | 5.1% | 11.57% | 23.82% | 47.23% | 84.38% |
| 17 | Senegal | 84.78 | 1.51% | 3.9% | 9.68% | 22.18% | 44.45% | 75.85% |
| 18 | Mexico | 84.85 | 1.39% | 4.15% | 10.47% | 23.84% | 53.15% | 90.15% |
| 19 | Ecuador | 83.63 | 1.28% | 3.58% | 8.86% | 19.46% | 44.7% | 85.95% |
| 20 | Uruguay | 81.69 | 0.71% | 2.54% | 8.0% | 16.8% | 34.58% | 85.56% |

## Top 20 Final Probability

| Rank | Team | Strength | Final | Champion | Semi Final | Quarter Final | Round of 16 | Round of 32 |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | Spain | 98.28 | 24.35% | 15.81% | 37.9% | 50.72% | 71.52% | 97.91% |
| 2 | France | 97.1 | 21.89% | 13.63% | 34.67% | 50.75% | 72.8% | 93.2% |
| 3 | England | 96.38 | 20.71% | 12.69% | 32.23% | 48.71% | 71.72% | 94.67% |
| 4 | Argentina | 95.27 | 18.62% | 10.8% | 30.33% | 45.64% | 62.93% | 94.04% |
| 5 | Portugal | 90.95 | 11.53% | 5.63% | 21.45% | 37.57% | 61.45% | 91.37% |
| 6 | Netherlands | 90.24 | 9.34% | 4.56% | 18.57% | 35.85% | 56.28% | 90.42% |
| 7 | Germany | 89.41 | 8.67% | 4.02% | 16.86% | 30.28% | 57.94% | 92.44% |
| 8 | Croatia | 88.56 | 7.85% | 3.55% | 15.57% | 28.73% | 54.68% | 87.84% |
| 9 | Brazil | 88.3 | 6.98% | 3.2% | 14.62% | 29.75% | 51.71% | 90.78% |
| 10 | Belgium | 86.38 | 6.45% | 2.57% | 14.25% | 30.98% | 57.62% | 90.5% |
| 11 | Norway | 87.23 | 6.4% | 2.83% | 13.36% | 26.99% | 49.9% | 80.55% |
| 12 | Morocco | 86.95 | 6.17% | 2.7% | 12.86% | 27.01% | 48.69% | 88.62% |
| 13 | Turkiye | 86.46 | 6.09% | 2.61% | 13.42% | 29.73% | 54.1% | 84.01% |
| 14 | Switzerland | 84.6 | 5.53% | 2.12% | 12.95% | 29.03% | 58.96% | 93.69% |
| 15 | Japan | 85.97 | 5.41% | 2.23% | 12.06% | 25.0% | 44.94% | 85.06% |
| 16 | Colombia | 85.68 | 5.1% | 2.1% | 11.57% | 23.82% | 47.23% | 84.38% |
| 17 | Mexico | 84.85 | 4.15% | 1.39% | 10.47% | 23.84% | 53.15% | 90.15% |
| 18 | Senegal | 84.78 | 3.9% | 1.51% | 9.68% | 22.18% | 44.45% | 75.85% |
| 19 | Ecuador | 83.63 | 3.58% | 1.28% | 8.86% | 19.46% | 44.7% | 85.95% |
| 20 | Uruguay | 81.69 | 2.54% | 0.71% | 8.0% | 16.8% | 34.58% | 85.56% |