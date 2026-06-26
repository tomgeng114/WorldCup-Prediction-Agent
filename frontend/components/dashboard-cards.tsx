import { DashboardSummary } from "@/lib/types";

type NumericSummaryKey = {
  [Key in keyof DashboardSummary]: DashboardSummary[Key] extends number ? Key : never;
}[keyof DashboardSummary];

const cards: {
  key: NumericSummaryKey;
  label: string;
  suffix: string;
  rateKey?: NumericSummaryKey;
}[] = [
  { key: "total_predictions", label: "总预测场次", suffix: "" },
  { key: "win_draw_loss_hit_rate", label: "胜平负命中率", suffix: "%" },
  { key: "handicap_hit_rate", label: "让球盘命中率", suffix: "%" },
  { key: "score_hit_rate", label: "比分命中率", suffix: "%" },
  { key: "goal_diff_hit_rate", label: "净胜球命中率", suffix: "%" },
  { key: "ai_hot_same_count", label: "AI同体彩热门", suffix: "场", rateKey: "ai_hot_same_rate" },
  { key: "ai_hot_opposite_count", label: "AI反体彩热门", suffix: "场", rateKey: "ai_hot_opposite_rate" },
  { key: "roi", label: "ROI", suffix: "%" },
];

export function DashboardCards({ summary }: { summary: DashboardSummary }) {
  return (
    <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      {cards.map((card) => (
        <article key={card.key} className="grid-panel rounded-2xl p-5">
          <p className="text-xs uppercase tracking-[0.25em] text-slate-400">{card.label}</p>
          <p className="mt-3 text-3xl font-semibold text-white">
            {summary[card.key]}
            {card.suffix}
          </p>
          {card.rateKey ? (
            <p className="mt-2 text-xs text-slate-400">
              样本 {summary.ai_hot_sample_size} 场，占比 {summary[card.rateKey]}%
            </p>
          ) : null}
        </article>
      ))}
    </section>
  );
}
