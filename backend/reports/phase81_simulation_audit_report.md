# Phase 8.1 World Cup Simulation Audit

## Audit Scope

- Simulations audited: 10000
- pre_draw_simulation: False
- real_schedule_simulation: True
- Schedule source: https://www.zoho.com/toolkit/fifa-world-cup-2026.html
- Rank anomaly threshold: 8 places
- Policy: audit only; model parameters and simulation logic were not modified.


## Top20 Champion Probability

| Rank | Team | Confed | Strength Rank | Champion Rank | Rank Delta | Strength | Probability |
|---:|---|---|---:|---:|---:|---:|---:|
| 1 | Spain | UEFA | 1 | 1 | 0 | 98.28 | 15.81% |
| 2 | France | UEFA | 2 | 2 | 0 | 97.1 | 13.63% |
| 3 | England | UEFA | 3 | 3 | 0 | 96.38 | 12.69% |
| 4 | Argentina | CONMEBOL | 4 | 4 | 0 | 95.27 | 10.8% |
| 5 | Portugal | UEFA | 5 | 5 | 0 | 90.95 | 5.63% |
| 6 | Netherlands | UEFA | 6 | 6 | 0 | 90.24 | 4.56% |
| 7 | Germany | UEFA | 7 | 7 | 0 | 89.41 | 4.02% |
| 8 | Croatia | UEFA | 8 | 8 | 0 | 88.56 | 3.55% |
| 9 | Brazil | CONMEBOL | 9 | 9 | 0 | 88.3 | 3.2% |
| 10 | Norway | UEFA | 10 | 10 | 0 | 87.23 | 2.83% |
| 11 | Morocco | CAF | 11 | 11 | 0 | 86.95 | 2.7% |
| 12 | Turkiye | UEFA | 12 | 12 | 0 | 86.46 | 2.61% |
| 13 | Belgium | UEFA | 13 | 13 | 0 | 86.38 | 2.57% |
| 14 | Japan | AFC | 14 | 14 | 0 | 85.97 | 2.23% |
| 15 | Switzerland | UEFA | 18 | 15 | 3 | 84.6 | 2.12% |
| 16 | Colombia | CONMEBOL | 15 | 16 | -1 | 85.68 | 2.1% |
| 17 | Senegal | CAF | 17 | 17 | 0 | 84.78 | 1.51% |
| 18 | Mexico | CONCACAF | 16 | 18 | -2 | 84.85 | 1.39% |
| 19 | Ecuador | CONMEBOL | 19 | 19 | 0 | 83.63 | 1.28% |
| 20 | Uruguay | CONMEBOL | 20 | 20 | 0 | 81.69 | 0.71% |

## Top20 Final Probability

| Rank | Team | Confed | Strength Rank | Champion Rank | Rank Delta | Strength | Probability |
|---:|---|---|---:|---:|---:|---:|---:|
| 1 | Spain | UEFA | 1 | 1 | 0 | 98.28 | 24.35% |
| 2 | France | UEFA | 2 | 2 | 0 | 97.1 | 21.89% |
| 3 | England | UEFA | 3 | 3 | 0 | 96.38 | 20.71% |
| 4 | Argentina | CONMEBOL | 4 | 4 | 0 | 95.27 | 18.62% |
| 5 | Portugal | UEFA | 5 | 5 | 0 | 90.95 | 11.53% |
| 6 | Netherlands | UEFA | 6 | 6 | 0 | 90.24 | 9.34% |
| 7 | Germany | UEFA | 7 | 7 | 0 | 89.41 | 8.67% |
| 8 | Croatia | UEFA | 8 | 8 | 0 | 88.56 | 7.85% |
| 9 | Brazil | CONMEBOL | 9 | 9 | 0 | 88.3 | 6.98% |
| 10 | Belgium | UEFA | 13 | 13 | 0 | 86.38 | 6.45% |
| 11 | Norway | UEFA | 10 | 10 | 0 | 87.23 | 6.4% |
| 12 | Morocco | CAF | 11 | 11 | 0 | 86.95 | 6.17% |
| 13 | Turkiye | UEFA | 12 | 12 | 0 | 86.46 | 6.09% |
| 14 | Switzerland | UEFA | 18 | 15 | 3 | 84.6 | 5.53% |
| 15 | Japan | AFC | 14 | 14 | 0 | 85.97 | 5.41% |
| 16 | Colombia | CONMEBOL | 15 | 16 | -1 | 85.68 | 5.1% |
| 17 | Mexico | CONCACAF | 16 | 18 | -2 | 84.85 | 4.15% |
| 18 | Senegal | CAF | 17 | 17 | 0 | 84.78 | 3.9% |
| 19 | Ecuador | CONMEBOL | 19 | 19 | 0 | 83.63 | 3.58% |
| 20 | Uruguay | CONMEBOL | 20 | 20 | 0 | 81.69 | 2.54% |

## Top20 Semi Final Probability

| Rank | Team | Confed | Strength Rank | Champion Rank | Rank Delta | Strength | Probability |
|---:|---|---|---:|---:|---:|---:|---:|
| 1 | Spain | UEFA | 1 | 1 | 0 | 98.28 | 37.9% |
| 2 | France | UEFA | 2 | 2 | 0 | 97.1 | 34.67% |
| 3 | England | UEFA | 3 | 3 | 0 | 96.38 | 32.23% |
| 4 | Argentina | CONMEBOL | 4 | 4 | 0 | 95.27 | 30.33% |
| 5 | Portugal | UEFA | 5 | 5 | 0 | 90.95 | 21.45% |
| 6 | Netherlands | UEFA | 6 | 6 | 0 | 90.24 | 18.57% |
| 7 | Germany | UEFA | 7 | 7 | 0 | 89.41 | 16.86% |
| 8 | Croatia | UEFA | 8 | 8 | 0 | 88.56 | 15.57% |
| 9 | Brazil | CONMEBOL | 9 | 9 | 0 | 88.3 | 14.62% |
| 10 | Belgium | UEFA | 13 | 13 | 0 | 86.38 | 14.25% |
| 11 | Turkiye | UEFA | 12 | 12 | 0 | 86.46 | 13.42% |
| 12 | Norway | UEFA | 10 | 10 | 0 | 87.23 | 13.36% |
| 13 | Switzerland | UEFA | 18 | 15 | 3 | 84.6 | 12.95% |
| 14 | Morocco | CAF | 11 | 11 | 0 | 86.95 | 12.86% |
| 15 | Japan | AFC | 14 | 14 | 0 | 85.97 | 12.06% |
| 16 | Colombia | CONMEBOL | 15 | 16 | -1 | 85.68 | 11.57% |
| 17 | Mexico | CONCACAF | 16 | 18 | -2 | 84.85 | 10.47% |
| 18 | Senegal | CAF | 17 | 17 | 0 | 84.78 | 9.68% |
| 19 | Ecuador | CONMEBOL | 19 | 19 | 0 | 83.63 | 8.86% |
| 20 | Uruguay | CONMEBOL | 20 | 20 | 0 | 81.69 | 8.0% |

## Top20 Quarter Final Probability

| Rank | Team | Confed | Strength Rank | Champion Rank | Rank Delta | Strength | Probability |
|---:|---|---|---:|---:|---:|---:|---:|
| 1 | France | UEFA | 2 | 2 | 0 | 97.1 | 50.75% |
| 2 | Spain | UEFA | 1 | 1 | 0 | 98.28 | 50.72% |
| 3 | England | UEFA | 3 | 3 | 0 | 96.38 | 48.71% |
| 4 | Argentina | CONMEBOL | 4 | 4 | 0 | 95.27 | 45.64% |
| 5 | Portugal | UEFA | 5 | 5 | 0 | 90.95 | 37.57% |
| 6 | Netherlands | UEFA | 6 | 6 | 0 | 90.24 | 35.85% |
| 7 | Belgium | UEFA | 13 | 13 | 0 | 86.38 | 30.98% |
| 8 | Germany | UEFA | 7 | 7 | 0 | 89.41 | 30.28% |
| 9 | Brazil | CONMEBOL | 9 | 9 | 0 | 88.3 | 29.75% |
| 10 | Turkiye | UEFA | 12 | 12 | 0 | 86.46 | 29.73% |
| 11 | Switzerland | UEFA | 18 | 15 | 3 | 84.6 | 29.03% |
| 12 | Croatia | UEFA | 8 | 8 | 0 | 88.56 | 28.73% |
| 13 | Morocco | CAF | 11 | 11 | 0 | 86.95 | 27.01% |
| 14 | Norway | UEFA | 10 | 10 | 0 | 87.23 | 26.99% |
| 15 | Japan | AFC | 14 | 14 | 0 | 85.97 | 25.0% |
| 16 | Mexico | CONCACAF | 16 | 18 | -2 | 84.85 | 23.84% |
| 17 | Colombia | CONMEBOL | 15 | 16 | -1 | 85.68 | 23.82% |
| 18 | Senegal | CAF | 17 | 17 | 0 | 84.78 | 22.18% |
| 19 | Ecuador | CONMEBOL | 19 | 19 | 0 | 83.63 | 19.46% |
| 20 | Canada | CONCACAF | 24 | 22 | 2 | 78.39 | 17.31% |

## Top20 Group Qualification Probability

| Rank | Team | Confed | Strength Rank | Champion Rank | Rank Delta | Strength | Probability |
|---:|---|---|---:|---:|---:|---:|---:|
| 1 | Spain | UEFA | 1 | 1 | 0 | 98.28 | 97.91% |
| 2 | England | UEFA | 3 | 3 | 0 | 96.38 | 94.67% |
| 3 | Argentina | CONMEBOL | 4 | 4 | 0 | 95.27 | 94.04% |
| 4 | Switzerland | UEFA | 18 | 15 | 3 | 84.6 | 93.69% |
| 5 | France | UEFA | 2 | 2 | 0 | 97.1 | 93.2% |
| 6 | Germany | UEFA | 7 | 7 | 0 | 89.41 | 92.44% |
| 7 | Portugal | UEFA | 5 | 5 | 0 | 90.95 | 91.37% |
| 8 | Brazil | CONMEBOL | 9 | 9 | 0 | 88.3 | 90.78% |
| 9 | Belgium | UEFA | 13 | 13 | 0 | 86.38 | 90.5% |
| 10 | Netherlands | UEFA | 6 | 6 | 0 | 90.24 | 90.42% |
| 11 | Mexico | CONCACAF | 16 | 18 | -2 | 84.85 | 90.15% |
| 12 | Morocco | CAF | 11 | 11 | 0 | 86.95 | 88.62% |
| 13 | Croatia | UEFA | 8 | 8 | 0 | 88.56 | 87.84% |
| 14 | Canada | CONCACAF | 24 | 22 | 2 | 78.39 | 87.63% |
| 15 | Ecuador | CONMEBOL | 19 | 19 | 0 | 83.63 | 85.95% |
| 16 | Uruguay | CONMEBOL | 20 | 20 | 0 | 81.69 | 85.56% |
| 17 | Japan | AFC | 14 | 14 | 0 | 85.97 | 85.06% |
| 18 | Colombia | CONMEBOL | 15 | 16 | -1 | 85.68 | 84.38% |
| 19 | Turkiye | UEFA | 12 | 12 | 0 | 86.46 | 84.01% |
| 20 | Norway | UEFA | 10 | 10 | 0 | 87.23 | 80.55% |

## Confederation Champion Probability

| Confederation | Teams | Avg Champion % | Total Champion % | Top Team | Top Team Champion % |
|---|---:|---:|---:|---|---:|
| UEFA | 16 | 4.435% | 70.96% | Spain | 15.81% |
| CONMEBOL | 6 | 3.033% | 18.2% | Argentina | 10.8% |
| AFC | 9 | 0.364% | 3.28% | Japan | 2.23% |
| CAF | 10 | 0.505% | 5.05% | Morocco | 2.7% |
| CONCACAF | 6 | 0.418% | 2.51% | Mexico | 1.39% |
| OFC | 1 | 0.0% | 0.0% | New Zealand | 0.0% |

## Overrated Teams

| Team | Confed | Strength Rank | Champion Rank | Rank Delta | Strength | Champion % | Final % | Semi % | Quarter % | Group Qual % |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| - | - | - | - | - | - | - | - | - | - | - |

## Underrated Teams

| Team | Confed | Strength Rank | Champion Rank | Rank Delta | Strength | Champion % | Final % | Semi % | Quarter % | Group Qual % |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| - | - | - | - | - | - | - | - | - | - | - |

## Strength vs Champion Probability Rank Audit

| Team | Confed | Strength Rank | Champion Rank | Rank Delta | Strength | Champion % | Final % | Semi % | Quarter % | Group Qual % |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Spain | UEFA | 1 | 1 | 0 | 98.28 | 15.81% | 24.35% | 37.9% | 50.72% | 97.91% |
| France | UEFA | 2 | 2 | 0 | 97.1 | 13.63% | 21.89% | 34.67% | 50.75% | 93.2% |
| England | UEFA | 3 | 3 | 0 | 96.38 | 12.69% | 20.71% | 32.23% | 48.71% | 94.67% |
| Argentina | CONMEBOL | 4 | 4 | 0 | 95.27 | 10.8% | 18.62% | 30.33% | 45.64% | 94.04% |
| Portugal | UEFA | 5 | 5 | 0 | 90.95 | 5.63% | 11.53% | 21.45% | 37.57% | 91.37% |
| Netherlands | UEFA | 6 | 6 | 0 | 90.24 | 4.56% | 9.34% | 18.57% | 35.85% | 90.42% |
| Germany | UEFA | 7 | 7 | 0 | 89.41 | 4.02% | 8.67% | 16.86% | 30.28% | 92.44% |
| Croatia | UEFA | 8 | 8 | 0 | 88.56 | 3.55% | 7.85% | 15.57% | 28.73% | 87.84% |
| Brazil | CONMEBOL | 9 | 9 | 0 | 88.3 | 3.2% | 6.98% | 14.62% | 29.75% | 90.78% |
| Norway | UEFA | 10 | 10 | 0 | 87.23 | 2.83% | 6.4% | 13.36% | 26.99% | 80.55% |
| Morocco | CAF | 11 | 11 | 0 | 86.95 | 2.7% | 6.17% | 12.86% | 27.01% | 88.62% |
| Turkiye | UEFA | 12 | 12 | 0 | 86.46 | 2.61% | 6.09% | 13.42% | 29.73% | 84.01% |
| Belgium | UEFA | 13 | 13 | 0 | 86.38 | 2.57% | 6.45% | 14.25% | 30.98% | 90.5% |
| Japan | AFC | 14 | 14 | 0 | 85.97 | 2.23% | 5.41% | 12.06% | 25.0% | 85.06% |
| Switzerland | UEFA | 18 | 15 | 3 | 84.6 | 2.12% | 5.53% | 12.95% | 29.03% | 93.69% |
| Colombia | CONMEBOL | 15 | 16 | -1 | 85.68 | 2.1% | 5.1% | 11.57% | 23.82% | 84.38% |
| Senegal | CAF | 17 | 17 | 0 | 84.78 | 1.51% | 3.9% | 9.68% | 22.18% | 75.85% |
| Mexico | CONCACAF | 16 | 18 | -2 | 84.85 | 1.39% | 4.15% | 10.47% | 23.84% | 90.15% |
| Ecuador | CONMEBOL | 19 | 19 | 0 | 83.63 | 1.28% | 3.58% | 8.86% | 19.46% | 85.95% |
| Uruguay | CONMEBOL | 20 | 20 | 0 | 81.69 | 0.71% | 2.54% | 8.0% | 16.8% | 85.56% |
| Austria | UEFA | 21 | 21 | 0 | 81.26 | 0.67% | 2.24% | 6.45% | 14.67% | 74.69% |
| Canada | CONCACAF | 24 | 22 | 2 | 78.39 | 0.59% | 1.76% | 5.95% | 17.31% | 87.63% |
| USA | CONCACAF | 22 | 23 | -1 | 78.74 | 0.46% | 1.62% | 4.61% | 13.43% | 66.99% |
| Korea Republic | AFC | 25 | 24 | 1 | 77.64 | 0.41% | 1.42% | 4.2% | 13.34% | 77.9% |
| Algeria | CAF | 23 | 25 | -2 | 78.48 | 0.35% | 1.16% | 3.36% | 10.0% | 68.28% |
| Australia | AFC | 26 | 26 | 0 | 77.19 | 0.34% | 1.02% | 3.06% | 11.05% | 62.5% |
| IR Iran | AFC | 27 | 27 | 0 | 76.91 | 0.21% | 1.07% | 3.64% | 11.97% | 74.34% |
| Egypt | CAF | 29 | 28 | 1 | 75.35 | 0.2% | 0.84% | 3.03% | 10.19% | 70.94% |
| Cote d'Ivoire | CAF | 28 | 29 | -1 | 76.22 | 0.2% | 0.8% | 2.73% | 9.27% | 72.57% |
| Scotland | UEFA | 30 | 30 | 0 | 75.29 | 0.13% | 0.62% | 2.61% | 8.77% | 67.85% |
| Paraguay | CONMEBOL | 31 | 31 | 0 | 75.08 | 0.11% | 0.61% | 2.39% | 8.22% | 56.75% |
| Czechia | UEFA | 32 | 32 | 0 | 74.28 | 0.11% | 0.48% | 2.28% | 9.48% | 71.24% |
| Uzbekistan | AFC | 34 | 33 | 1 | 70.88 | 0.08% | 0.25% | 0.97% | 3.62% | 48.18% |
| Panama | CONCACAF | 33 | 34 | -1 | 73.93 | 0.07% | 0.4% | 1.68% | 6.19% | 55.78% |
| Tunisia | CAF | 35 | 35 | 0 | 70.73 | 0.04% | 0.11% | 0.92% | 3.99% | 47.6% |
| DR Congo | CAF | 37 | 36 | 1 | 69.07 | 0.03% | 0.12% | 0.59% | 2.6% | 42.27% |
| Sweden | UEFA | 36 | 37 | -1 | 69.19 | 0.02% | 0.04% | 0.5% | 2.82% | 43.47% |
| Bosnia and Herzegovina | UEFA | 42 | 38 | 4 | 62.0 | 0.01% | 0.06% | 0.25% | 1.91% | 51.08% |
| Iraq | AFC | 39 | 39 | 0 | 63.66 | 0.01% | 0.03% | 0.16% | 0.79% | 20.61% |
| Ghana | CAF | 43 | 40 | 3 | 61.67 | 0.01% | 0.03% | 0.11% | 0.8% | 24.89% |
| Cabo Verde | CAF | 40 | 41 | -1 | 62.66 | 0.01% | 0.02% | 0.19% | 1.48% | 40.01% |
| Saudi Arabia | AFC | 44 | 42 | 2 | 60.72 | 0.0% | 0.02% | 0.17% | 0.99% | 34.91% |
| Jordan | AFC | 38 | 43 | -5 | 64.44 | 0.0% | 0.01% | 0.12% | 1.06% | 29.87% |
| South Africa | CAF | 45 | 44 | 1 | 60.15 | 0.0% | 0.01% | 0.12% | 0.82% | 29.84% |
| New Zealand | OFC | 41 | 45 | -4 | 62.16 | 0.0% | 0.0% | 0.16% | 1.26% | 32.92% |
| Haiti | CONCACAF | 46 | 46 | 0 | 58.15 | 0.0% | 0.0% | 0.02% | 0.45% | 20.7% |
| Qatar | AFC | 47 | 47 | 0 | 55.35 | 0.0% | 0.0% | 0.05% | 0.53% | 31.79% |
| Curacao | CONCACAF | 48 | 48 | 0 | 54.61 | 0.0% | 0.0% | 0.0% | 0.15% | 17.41% |