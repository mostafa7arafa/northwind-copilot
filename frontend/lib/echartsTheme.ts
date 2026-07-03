// A dark ECharts theme tuned to the Trading Desk palette. The agent's chart
// specs deliberately omit colors/fonts so this theme is the single source of
// visual truth for every chart.

export const TRADING_DESK_THEME = {
  color: ["#4f8cff", "#6b8fb8", "#32d583", "#f79009", "#c084fc", "#f04438"],
  backgroundColor: "transparent",
  textStyle: {
    fontFamily:
      "var(--font-jetbrains), ui-monospace, monospace",
    color: "#8a8f9c",
  },
  title: {
    textStyle: { color: "#edeef2", fontWeight: 500, fontSize: 14 },
  },
  legend: {
    textStyle: { color: "#8a8f9c" },
    icon: "roundRect",
    itemWidth: 10,
    itemHeight: 10,
  },
  tooltip: {
    backgroundColor: "rgba(17,19,24,0.96)",
    borderColor: "rgba(255,255,255,0.10)",
    borderWidth: 1,
    padding: [8, 12],
    textStyle: { color: "#edeef2", fontSize: 12 },
    extraCssText: "backdrop-filter: blur(8px); border-radius: 10px;",
  },
  categoryAxis: {
    axisLine: { lineStyle: { color: "rgba(255,255,255,0.14)" } },
    axisTick: { show: false },
    axisLabel: { color: "#8a8f9c", fontSize: 11 },
    splitLine: { show: false },
  },
  valueAxis: {
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { color: "#8a8f9c", fontSize: 11 },
    splitLine: { lineStyle: { color: "rgba(255,255,255,0.06)" } },
  },
  bar: {
    itemStyle: { borderRadius: [4, 4, 0, 0] },
    barMaxWidth: 34,
  },
  line: {
    lineStyle: { width: 2 },
    symbolSize: 6,
    smooth: true,
  },
  // Pie/funnel labels sit ON their colored shapes, so ECharts skips the global
  // textStyle and auto-picks a "contrast" color instead. With a transparent
  // backgroundColor it assumes a LIGHT canvas and renders dark text with a
  // white stroke halo. An explicit label color disables that auto logic.
  pie: {
    label: { color: "#8a8f9c", fontSize: 11 },
    labelLine: { lineStyle: { color: "rgba(255,255,255,0.25)" } },
    itemStyle: { borderColor: "#111318", borderWidth: 2 },
  },
  funnel: {
    label: { color: "#8a8f9c", fontSize: 11 },
  },
};

export const THEME_NAME = "trading-desk";
