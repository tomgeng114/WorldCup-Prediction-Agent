export function MiniChart({
  title,
  points,
  colorClass,
}: {
  title: string;
  points: { date: string; value: number }[];
  colorClass: string;
}) {
  if (!points.length) {
    return (
      <section className="grid-panel rounded-3xl p-5">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold text-white">{title}</h2>
          <span className="text-xs uppercase tracking-[0.25em] text-slate-400">趋势</span>
        </div>
        <div className="mt-6 flex h-44 items-center justify-center rounded-2xl border border-white/10 bg-white/5 text-sm text-slate-400">
          暂无已结算赛果
        </div>
      </section>
    );
  }

  const max = Math.max(...points.map((point) => point.value), 1);

  return (
    <section className="grid-panel rounded-3xl p-5">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-white">{title}</h2>
        <span className="text-xs uppercase tracking-[0.25em] text-slate-400">趋势</span>
      </div>
      <div className="mt-6 flex h-44 items-end gap-3">
        {points.map((point) => (
          <div key={point.date} className="flex flex-1 flex-col items-center gap-3">
            <div className="flex h-32 w-full items-end rounded-t-2xl bg-white/5 p-2">
              <div
                className={`w-full rounded-xl ${colorClass}`}
                style={{ height: `${Math.max(12, (point.value / max) * 100)}%` }}
              />
            </div>
            <div className="text-center">
              <p className="text-xs text-slate-400">{point.date}</p>
              <p className="text-sm font-medium text-white">{point.value}</p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
