import { Activity, BarChart3, Shield, Trophy } from "lucide-react";

export function Header() {
  return (
    <section className="overflow-hidden rounded-3xl border border-skyline/20 bg-hero p-6 shadow-glow">
      <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
        <div className="max-w-3xl space-y-4">
          <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs uppercase tracking-[0.3em] text-skyline">
            <Trophy className="h-4 w-4" />
            World Cup AI Predictor Pro
          </div>
          <h1 className="text-4xl font-semibold text-white sm:text-5xl">
            专业足球赛事 AI 预测与量化回测工作台
          </h1>
          <p className="max-w-2xl text-sm leading-6 text-slate-300 sm:text-base">
            集成赛程、赔率、胜平负概率、比分预测、半全场、大小球、冷门预警和红黑单统计，面向专业足球数据分析场景。
          </p>
        </div>
        <div className="grid w-full max-w-xl grid-cols-2 gap-3">
          {[
            { icon: Shield, label: "胜平负预测", value: "AI 加权模型" },
            { icon: Activity, label: "赔率监控", value: "体彩数据源" },
            { icon: BarChart3, label: "历史回测", value: "命中率 + ROI" },
            { icon: Trophy, label: "赛事范围", value: "世界杯 + 主流赛事" },
          ].map((item) => (
            <div key={item.label} className="grid-panel rounded-2xl p-4">
              <item.icon className="mb-3 h-5 w-5 text-accent" />
              <p className="text-xs uppercase tracking-[0.25em] text-slate-400">{item.label}</p>
              <p className="mt-2 text-lg font-semibold text-white">{item.value}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
