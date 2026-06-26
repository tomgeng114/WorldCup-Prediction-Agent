import { DashboardCards } from "@/components/dashboard-cards";
import { Header } from "@/components/header";
import { HistoryTable } from "@/components/history-table";
import { MatchCardPanel } from "@/components/match-card";
import { MiniChart } from "@/components/mini-chart";
import { Shell } from "@/components/shell";
import { getAllMatches, getDashboardSummary, getHistory } from "@/lib/api";
import type { DashboardSummary, HistoryRow, MatchCard } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  let summary: DashboardSummary;
  let matches: MatchCard[];
  let history: HistoryRow[];

  try {
    [summary, matches, history] = await Promise.all([
      getDashboardSummary(),
      getAllMatches(),
      getHistory(),
    ]);
  } catch {
    summary = {
      total_predictions: 0,
      win_draw_loss_hit_rate: 0,
      handicap_hit_rate: 0,
      score_hit_rate: 0,
      goal_diff_hit_rate: 0,
      half_full_hit_rate: 0,
      over_under_hit_rate: 0,
      roi: 0,
      today_red: 0,
      today_black: 0,
      today_hit_rate: 0,
      seven_day_red: 0,
      seven_day_black: 0,
      seven_day_hit_rate: 0,
      thirty_day_red: 0,
      thirty_day_black: 0,
      thirty_day_hit_rate: 0,
      ai_hot_same_count: 0,
      ai_hot_opposite_count: 0,
      ai_hot_sample_size: 0,
      ai_hot_same_rate: 0,
      ai_hot_opposite_rate: 0,
      profit_curve: [
        { date: "第1天", value: 0 },
        { date: "第2天", value: 0 },
      ],
      accuracy_curve: [
        { date: "第1天", value: 0 },
        { date: "第2天", value: 0 },
      ],
    };
    matches = [];
    history = [];
  }

  const profitCurve = summary.profit_curve.map((point, index) => ({
    ...point,
    date: point.date.startsWith("Day") ? `第${index + 1}天` : point.date,
  }));
  const accuracyCurve = summary.accuracy_curve.map((point, index) => ({
    ...point,
    date: point.date.startsWith("Day") ? `第${index + 1}天` : point.date,
  }));

  return (
    <Shell>
      <main className="space-y-6">
        <Header />
        <DashboardCards summary={summary} />

        <section className="grid gap-4 xl:grid-cols-2">
          <MiniChart title="收益曲线" points={profitCurve} colorClass="metric-bar" />
          <MiniChart title="命中率曲线" points={accuracyCurve} colorClass="bg-gradient-to-t from-success to-skyline" />
        </section>

        <section className="space-y-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-xs uppercase tracking-[0.25em] text-slate-400">竞彩赛事</p>
              <h2 className="mt-2 text-2xl font-semibold text-white">AI 赛事预测看板</h2>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-slate-300">
              红单：{summary.today_red} / 黑单：{summary.today_black} / 命中率：{summary.today_hit_rate}%
            </div>
          </div>
          <div className="space-y-4">
            {matches.length ? (
              matches.map((match) => <MatchCardPanel key={match.id} match={match} />)
            ) : (
              <div className="grid-panel rounded-3xl p-8 text-center text-slate-300">
                后端数据暂时不可用。启动 FastAPI 服务后即可加载体彩赛程和预测。
              </div>
            )}
          </div>
        </section>

        <section className="grid gap-4 lg:grid-cols-3">
          {[
            ["近7天红黑单", `${summary.seven_day_red} / ${summary.seven_day_black}`],
            ["近30天红黑单", `${summary.thirty_day_red} / ${summary.thirty_day_black}`],
            ["近30天命中率", `${summary.thirty_day_hit_rate}%`],
          ].map(([label, value]) => (
            <article key={label} className="grid-panel rounded-2xl p-5">
              <p className="text-xs uppercase tracking-[0.25em] text-slate-400">{label}</p>
              <p className="mt-3 text-3xl font-semibold text-white">{value}</p>
            </article>
          ))}
        </section>

        <HistoryTable rows={history} />
      </main>
    </Shell>
  );
}
