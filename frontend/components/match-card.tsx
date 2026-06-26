import { MatchCard } from "@/lib/types";

const resultMap: Record<string, string> = {
  "Home Win": "主胜",
  Draw: "平局",
  "Away Win": "客胜",
};

const handicapResultMap: Record<string, string> = {
  "Home Win": "让球胜",
  Draw: "让球平",
  "Away Win": "让球负",
};

const valueMap: Record<string, string> = {
  "Win/Win": "胜 / 胜",
  "Draw/Win": "平 / 胜",
  "Lose/Lose": "负 / 负",
  "Draw/Lose": "平 / 负",
  "Draw/Draw": "平 / 平",
  "0-1 goals": "0-1 球",
  "2-3 goals": "2-3 球",
  "4+ goals": "4 球以上",
  "0g": "0 球",
  "1g": "1 球",
  "2g": "2 球",
  "3g": "3 球",
  "4g": "4 球",
  "5g+": "5 球以上",
  "Over 2.5": "大 2.5",
  "Under 2.5": "小 2.5",
  Yes: "是",
  No: "否",
};

function pct(value: number) {
  return `${Math.round(value * 100)}%`;
}

function percent(value: number) {
  return `${(value * 100).toFixed(1)}%`;
}

function cnValue(value: string): string {
  if (value.includes(" / ")) {
    return value
      .split(" / ")
      .map((item) => cnValue(item))
      .join(" / ");
  }
  return valueMap[value] ?? resultMap[value] ?? value;
}

function riskBadgeClass(value: string) {
  const classes: Record<string, string> = {
    success: "border-success/30 bg-success/15 text-success",
    warning: "border-amber-400/30 bg-amber-400/15 text-amber-200",
    danger: "border-danger/30 bg-danger/15 text-danger",
    neutral: "border-white/15 bg-white/10 text-slate-200",
  };
  return classes[value] ?? classes.neutral;
}

function marketValue(match: MatchCard, value: string) {
  return match.prediction.market_type === "HHAD"
    ? handicapResultMap[value] ?? value
    : resultMap[value] ?? value;
}

function oddsTitle(match: MatchCard) {
  if (match.live_odds.source_pool === "HHAD") {
    return `让球胜平负 ${match.live_odds.handicap || ""}`.trim();
  }
  return "胜平负";
}

function rankText(match: MatchCard) {
  if (match.home_team.fifa_rank >= 999 || match.away_team.fifa_rank >= 999) {
    return "数据源：中国体育彩票";
  }
  return `FIFA 排名 #${match.home_team.fifa_rank} vs #${match.away_team.fifa_rank}`;
}

function ProbabilityGrid({
  homeLabel,
  awayLabel,
  probabilities,
}: {
  homeLabel: string;
  awayLabel: string;
  probabilities?: { home: number; draw: number; away: number };
}) {
  const safeProbabilities = probabilities ?? { home: 0, draw: 0, away: 0 };
  return (
    <div className="grid gap-3 md:grid-cols-3">
      {[
        { label: homeLabel, value: pct(safeProbabilities.home) },
        { label: "平局", value: pct(safeProbabilities.draw) },
        { label: awayLabel, value: pct(safeProbabilities.away) },
      ].map((item) => (
        <div key={item.label} className="rounded-2xl border border-white/10 bg-white/5 p-4">
          <p className="text-xs uppercase tracking-[0.25em] text-slate-400">{item.label}</p>
          <p className="mt-3 text-2xl font-semibold text-white">{item.value}</p>
        </div>
      ))}
    </div>
  );
}

export function MatchCardPanel({ match }: { match: MatchCard }) {
  const truePick = match.prediction.result_pick ?? match.prediction.result;
  const marketPick = match.prediction.market_pick ?? truePick;
  const marketProbabilities = match.prediction.market_probabilities ?? match.prediction.probabilities;
  const riskClass = riskBadgeClass(match.prediction.risk_badge_class);

  return (
    <article className="grid-panel rounded-3xl p-5">
      <div className="flex flex-col gap-4 border-b border-white/10 pb-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.25em] text-slate-400">
            {match.competition} / {match.stage}
          </p>
          <h3 className="mt-2 text-2xl font-semibold text-white">
            {match.home_team.name} vs {match.away_team.name}
          </h3>
          <p className="mt-2 text-sm text-slate-300">
            {new Date(match.kickoff_time).toLocaleString("zh-CN")} / {match.venue}
          </p>
          <p className="mt-1 text-sm text-slate-400">
            {match.home_team.group_name !== "-" ? `${match.home_team.group_name} 组 / ` : ""}
            {rankText(match)}
          </p>
        </div>
        <div className="rounded-2xl border border-accent/30 bg-accent/10 px-4 py-3 text-right">
          <p className="text-xs uppercase tracking-[0.25em] text-accent">AI 真实赛果主推</p>
          <p className="mt-1 text-xl font-semibold text-white">{cnValue(truePick)}</p>
          <p className="mt-1 text-sm text-slate-300">
            单一最高比分 {match.prediction.score}（{percent(match.prediction.score_probability)}）
          </p>
        </div>
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-[1.2fr_0.8fr]">
        <div className="space-y-4">
          <div className="rounded-2xl border border-white/10 bg-black/10 p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <p className="text-xs uppercase tracking-[0.25em] text-slate-400">真实赛果预测</p>
              <span className="rounded-full bg-accent/15 px-3 py-1 text-sm font-medium text-accent">
                {cnValue(truePick)}
              </span>
            </div>
            <ProbabilityGrid
              homeLabel={match.home_team.name}
              awayLabel={match.away_team.name}
              probabilities={match.prediction.probabilities}
            />
          </div>

          <div className="rounded-2xl border border-skyline/20 bg-skyline/10 p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <p className="text-xs uppercase tracking-[0.25em] text-skyline">
                竞彩盘口预测：{oddsTitle(match)}
              </p>
              <span className="rounded-full bg-skyline/15 px-3 py-1 text-sm font-medium text-skyline">
                {marketValue(match, marketPick)}
              </span>
            </div>
            <ProbabilityGrid
              homeLabel={match.prediction.market_type === "HHAD" ? "让球胜" : "主胜"}
              awayLabel={match.prediction.market_type === "HHAD" ? "让球负" : "客胜"}
              probabilities={marketProbabilities}
            />
            {match.prediction.market_type === "HHAD" ? (
              <p className="mt-3 text-xs leading-5 text-slate-400">
                注：这里是竞彩让球盘口概率，不能等同于真实比分胜平负概率。
              </p>
            ) : null}
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            {[
              ["Top3 单一比分", match.prediction.top_scores.map((item) => `${item.score} ${percent(item.probability)}`).join(" / ")],
              ["标准让一球（-1）", handicapResultMap[match.prediction.one_goal_handicap_pick] ?? match.prediction.one_goal_handicap_pick],
              ["半全场", cnValue(match.prediction.half_full_time)],
              ["总进球推荐", cnValue(match.prediction.total_goals_band)],
              ["大小球", cnValue(match.prediction.over_under_pick)],
              ["双方进球", cnValue(match.prediction.both_teams_to_score)],
              ["信心指数", `${match.prediction.confidence.toFixed(1)} / 100`],
            ].map(([label, value]) => (
              <div key={label} className="rounded-2xl border border-white/10 bg-black/10 p-4">
                <p className="text-xs uppercase tracking-[0.25em] text-slate-400">{label}</p>
                <p className="mt-2 text-base font-medium text-white">{value}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="space-y-4">
          <div className="rounded-2xl border border-white/10 bg-black/15 p-4">
            <p className="text-xs uppercase tracking-[0.25em] text-slate-400">体彩赔率：{oddsTitle(match)}</p>
            <div className="mt-3 grid grid-cols-3 gap-2 text-center">
              <div className="rounded-xl bg-white/5 p-3">
                <p className="text-xs text-slate-400">{match.live_odds.source_pool === "HHAD" ? "让球胜" : "主胜"}</p>
                <p className="text-lg font-semibold text-white">{match.live_odds.home}</p>
              </div>
              <div className="rounded-xl bg-white/5 p-3">
                <p className="text-xs text-slate-400">{match.live_odds.source_pool === "HHAD" ? "让球平" : "平局"}</p>
                <p className="text-lg font-semibold text-white">{match.live_odds.draw}</p>
              </div>
              <div className="rounded-xl bg-white/5 p-3">
                <p className="text-xs text-slate-400">{match.live_odds.source_pool === "HHAD" ? "让球负" : "客胜"}</p>
                <p className="text-lg font-semibold text-white">{match.live_odds.away}</p>
              </div>
            </div>
          </div>

          <div className="rounded-2xl border border-danger/20 bg-danger/10 p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs uppercase tracking-[0.25em] text-danger">冷门预警</p>
                <p className="mt-2 text-2xl font-semibold text-white">{match.prediction.upset_probability}%</p>
              </div>
              <div className={`rounded-full border px-3 py-1 text-sm font-semibold ${riskClass}`}>
                {match.prediction.risk_action}
              </div>
            </div>
            <p className="mt-2 text-sm font-medium text-white">
              {match.prediction.risk_level}：{match.prediction.risk_advice}
            </p>
            <p className="mt-2 text-sm leading-6 text-slate-300">{match.prediction.explanation}</p>
          </div>

          <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
            <p className="text-xs uppercase tracking-[0.25em] text-slate-400">总进球概率</p>
            <div className="mt-3 grid grid-cols-3 gap-2 text-center sm:grid-cols-6">
              {Object.entries(match.prediction.total_goals_probabilities).map(([label, value]) => (
                <div key={label} className="rounded-xl bg-black/15 p-2">
                  <p className="text-xs text-slate-400">{cnValue(label)}</p>
                  <p className="mt-1 text-sm font-semibold text-white">{percent(value)}</p>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-2xl border border-skyline/20 bg-skyline/10 p-4">
            <p className="text-xs uppercase tracking-[0.25em] text-skyline">AI 赛前分析</p>
            <p className="mt-2 text-sm leading-6 text-slate-200">{match.prediction.report_preview}</p>
          </div>
        </div>
      </div>
    </article>
  );
}
