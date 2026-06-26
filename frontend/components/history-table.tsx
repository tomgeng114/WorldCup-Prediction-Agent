import { HistoryRow } from "@/lib/types";

const teamNameMap: Record<string, string> = {
  Argentina: "阿根廷",
  Japan: "日本",
  France: "法国",
  "United States": "美国",
  Brazil: "巴西",
  Germany: "德国",
  Spain: "西班牙",
  Mexico: "墨西哥",
};

const resultMap: Record<string, string> = {
  "Home Win": "主胜",
  Draw: "平局",
  "Away Win": "客胜",
  Pending: "待定",
};

function cnTeam(name: string) {
  return teamNameMap[name] ?? name;
}

function cnResult(result: string) {
  return resultMap[result] ?? result;
}

function cnMarketResult(result: string, marketType: string) {
  if (marketType !== "HHAD") {
    return cnResult(result);
  }
  return {
    "Home Win": "让胜",
    Draw: "让平",
    "Away Win": "让负",
  }[result] ?? result;
}

export function HistoryTable({ rows }: { rows: HistoryRow[] }) {
  return (
    <section className="grid-panel overflow-hidden rounded-3xl">
      <div className="border-b border-white/10 px-5 py-4">
        <h2 className="text-xl font-semibold text-white">历史回测</h2>
        <p className="mt-1 text-sm text-slate-400">支持按日期、赛事、球队、预测结果和实际结果扩展筛选。</p>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-white/5 text-slate-400">
            <tr>
              <th className="px-5 py-3 font-medium">日期</th>
              <th className="px-5 py-3 font-medium">比赛</th>
              <th className="px-5 py-3 font-medium">预测结果</th>
              <th className="px-5 py-3 font-medium">实际结果</th>
              <th className="px-5 py-3 font-medium">让球预测</th>
              <th className="px-5 py-3 font-medium">让球实际</th>
              <th className="px-5 py-3 font-medium">让一球预测</th>
              <th className="px-5 py-3 font-medium">让一球实际</th>
              <th className="px-5 py-3 font-medium">预测比分</th>
              <th className="px-5 py-3 font-medium">实际比分</th>
              <th className="px-5 py-3 font-medium">胜平负命中</th>
              <th className="px-5 py-3 font-medium">比分命中</th>
              <th className="px-5 py-3 font-medium">ROI</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.match_id} className="border-t border-white/5 text-slate-200">
                <td className="px-5 py-3">{new Date(row.date).toLocaleDateString("zh-CN")}</td>
                <td className="px-5 py-3">
                  {cnTeam(row.home_team)} vs {cnTeam(row.away_team)}
                </td>
                <td className="px-5 py-3">{cnResult(row.predicted_result)}</td>
                <td className="px-5 py-3">{cnResult(row.actual_result)}</td>
                <td className="px-5 py-3">
                  {row.market_type === "HHAD" ? `${cnMarketResult(row.predicted_market_result, row.market_type)} ${row.handicap}` : "-"}
                </td>
                <td className="px-5 py-3">
                  {row.market_type === "HHAD" ? cnMarketResult(row.actual_market_result, row.market_type) : "-"}
                </td>
                <td className="px-5 py-3">{cnMarketResult(row.one_goal_handicap_result, "HHAD")} -1</td>
                <td className="px-5 py-3">{cnMarketResult(row.one_goal_handicap_actual_result, "HHAD")}</td>
                <td className="px-5 py-3">
                  {(row.predicted_scores?.length ? row.predicted_scores : [row.predicted_score]).join(" / ")}
                </td>
                <td className="px-5 py-3">{row.actual_score}</td>
                <td className={`px-5 py-3 ${row.hit_result ? "text-success" : "text-danger"}`}>
                  {row.hit_result ? "红单" : "黑单"}
                </td>
                <td className={`px-5 py-3 ${row.hit_score ? "text-success" : "text-danger"}`}>
                  {row.hit_score ? "红单" : "黑单"}
                </td>
                <td className={`px-5 py-3 ${row.roi >= 0 ? "text-success" : "text-danger"}`}>
                  {row.roi.toFixed(1)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
