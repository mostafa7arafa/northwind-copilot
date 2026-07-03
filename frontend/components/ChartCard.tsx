"use client";

import type { ECharts } from "echarts";
import {
  AreaChart,
  BarChart3,
  Download,
  LineChart,
  PieChart,
  ScatterChart,
  Sparkles,
} from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { EChart } from "./EChart";
import { GhostButton, Modal, Panel } from "./primitives";
import { cn } from "@/lib/cn";

type ChartType = "bar" | "line" | "area" | "scatter" | "pie";

const TYPES: { id: ChartType; label: string; Icon: typeof BarChart3 }[] = [
  { id: "bar", label: "Bar", Icon: BarChart3 },
  { id: "line", label: "Line", Icon: LineChart },
  { id: "area", label: "Area", Icon: AreaChart },
  { id: "scatter", label: "Scatter", Icon: ScatterChart },
  { id: "pie", label: "Pie", Icon: PieChart },
];

/** Above this many categories, labelling every tick is unreadable — thin the
 * labels and add zoom instead (e.g. a monthly series spanning 12 years). */
const DENSE_AXIS = 24;

/**
 * Long category labels (employee names, product titles) overlap and get dropped
 * in the narrow panel. Force every tick to render and rotate them when they're
 * long or numerous, and let the grid grow to contain the angled text. Fullscreen
 * has room to spare, but the rotation is harmless there too. Dense axes
 * (> DENSE_AXIS points) get the opposite treatment: auto-thinned labels plus a
 * zoom slider so the series stays explorable.
 */
function tuneAxes(opt: Record<string, any>) {
  const axes: any[] = Array.isArray(opt.xAxis)
    ? opt.xAxis
    : opt.xAxis
    ? [opt.xAxis]
    : [];
  let dense = false;
  for (const axis of axes) {
    if (!axis || axis.type === "value") continue;
    const cats: string[] = axis.data ?? [];
    if (cats.length > DENSE_AXIS) {
      dense = true;
      axis.axisLabel = {
        ...(axis.axisLabel ?? {}),
        rotate: 45,
        hideOverlap: true,
      };
      continue;
    }
    const longish =
      cats.length > 6 || cats.some((c) => String(c).length > 8);
    axis.axisLabel = {
      ...(axis.axisLabel ?? {}),
      interval: 0,
      rotate: longish ? 32 : 0,
      hideOverlap: false,
    };
  }
  if (axes.length) opt.grid = { ...(opt.grid ?? {}), containLabel: true };
  if (dense && !opt.dataZoom) {
    opt.dataZoom = [
      { type: "inside" },
      { type: "slider", height: 16, bottom: 6 },
    ];
    opt.grid = { ...(opt.grid ?? {}), bottom: 48 };
  }
  return opt;
}

/** Fix overlaps in model-drawn options before rendering: a `title` and an
 * unpositioned `legend` both default to the same top corner and collide. */
function sanitize(base: Record<string, any>): Record<string, any> {
  const opt = structuredClone(base);
  const legend = opt.legend;
  if (
    opt.title &&
    legend &&
    typeof legend === "object" &&
    !Array.isArray(legend) &&
    legend.show !== false &&
    legend.top == null &&
    legend.bottom == null
  ) {
    legend.top = 28;
  }
  return opt;
}

/** Reshape the agent's cartesian option into the selected chart type. */
function morph(base: Record<string, any>, type: ChartType): Record<string, any> {
  const opt = structuredClone(base);
  const categories: string[] = opt.xAxis?.data ?? opt.xAxis?.[0]?.data ?? [];
  const series: any[] = Array.isArray(opt.series) ? opt.series : [opt.series].filter(Boolean);

  if (type === "pie") {
    const s = series[0] ?? { data: [] };
    return {
      title: opt.title,
      tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
      legend: { show: false },
      series: [
        {
          type: "pie",
          radius: ["42%", "70%"],
          itemStyle: { borderColor: "#111318", borderWidth: 2 },
          label: { color: "#8a8f9c", fontSize: 11 },
          data: (s.data ?? []).map((v: number, i: number) => ({
            name: categories[i] ?? String(i),
            value: v,
          })),
        },
      ],
    };
  }

  opt.series = series.map((s) => ({
    ...s,
    type: type === "area" ? "line" : type,
    smooth: type === "line" || type === "area",
    areaStyle: type === "area" ? { opacity: 0.18 } : undefined,
    symbolSize: type === "scatter" ? 10 : s.symbolSize,
  }));
  return tuneAxes(opt);
}

/** Non-cartesian options (pie, radar, funnel, …) carry no xAxis; the morph
 * reshaper needs category data from one, so those charts render as drawn. */
function isCartesian(option: Record<string, any>): boolean {
  return option?.xAxis != null;
}

function guessType(option: Record<string, any>): ChartType {
  const t = Array.isArray(option?.series)
    ? option.series[0]?.type
    : option?.series?.type;
  if (t === "line")
    return (Array.isArray(option.series) ? option.series[0] : option.series)
      ?.areaStyle
      ? "area"
      : "line";
  if (t === "scatter" || t === "pie") return t;
  return "bar";
}

/** A chart that morphs between bar / line / area / scatter / pie, with export +
 * fullscreen. Model-drawn non-cartesian charts (pie, radar, funnel) render
 * as-is, without the morph toggle. */
export function ChartCard({
  option,
  inferred,
}: {
  option: Record<string, unknown>;
  inferred: boolean;
}) {
  const cleaned = useMemo(() => sanitize(option as any), [option]);
  const morphable = isCartesian(cleaned);
  const [type, setType] = useState<ChartType>(guessType(cleaned));
  const [full, setFull] = useState(false);
  const inst = useRef<ECharts | null>(null);

  const shaped = useMemo(
    () => (morphable ? morph(cleaned, type) : cleaned),
    [cleaned, type, morphable]
  );

  const downloadPng = () => {
    const url = inst.current?.getDataURL({ pixelRatio: 2, backgroundColor: "#09090b" });
    if (!url) return;
    const a = document.createElement("a");
    a.href = url;
    a.download = "chart.png";
    a.click();
  };

  return (
    <Panel
      eyebrow="Chart"
      title={
        inferred ? (
          <span className="inline-flex items-center gap-1.5 text-ink-dim">
            <Sparkles size={12} className="text-steel" /> auto-derived
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5 text-ink-dim">
            <Sparkles size={12} className="text-electric" /> drawn by model
          </span>
        )
      }
      actions={
        <>
          {morphable && (
          <div className="mr-1 flex items-center gap-0.5 rounded-lg border border-hairline bg-bg p-0.5">
            {TYPES.map(({ id, label, Icon }) => (
              <button
                key={id}
                type="button"
                title={label}
                onClick={() => setType(id)}
                className={cn(
                  "flex h-6 items-center gap-1 rounded-md px-2 text-[11px] transition-colors",
                  type === id
                    ? "bg-surface-2 text-ink"
                    : "text-ink-dim hover:text-ink"
                )}
              >
                <Icon size={12} />
              </button>
            ))}
          </div>
          )}
          <GhostButton title="Download PNG" onClick={downloadPng}>
            <Download size={13} />
          </GhostButton>
          <GhostButton title="Fullscreen" onClick={() => setFull(true)}>
            ⤢
          </GhostButton>
        </>
      }
    >
      <div className="p-2">
        <EChart option={shaped} height={300} onInit={(c) => (inst.current = c)} />
      </div>

      {full && (
        <Modal title="Chart · Esc to close" onClose={() => setFull(false)}>
          <EChart option={shaped} height="100%" />
        </Modal>
      )}
    </Panel>
  );
}
