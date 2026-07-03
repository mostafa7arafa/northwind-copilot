"use client";

import type { ECharts } from "echarts";
import {
  AreaChart,
  BarChart3,
  Download,
  LineChart,
  PieChart,
  Sparkles,
} from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { EChart } from "./EChart";
import { GhostButton, Modal, Panel } from "./primitives";
import { cn } from "@/lib/cn";

type ChartType = "bar" | "line" | "area" | "pie";

const TYPES: { id: ChartType; label: string; Icon: typeof BarChart3 }[] = [
  { id: "bar", label: "Bar", Icon: BarChart3 },
  { id: "line", label: "Line", Icon: LineChart },
  { id: "area", label: "Area", Icon: AreaChart },
  { id: "pie", label: "Pie", Icon: PieChart },
];

/**
 * Long category labels (employee names, product titles) overlap and get dropped
 * in the narrow panel. Force every tick to render and rotate them when they're
 * long or numerous, and let the grid grow to contain the angled text. Fullscreen
 * has room to spare, but the rotation is harmless there too.
 */
function tuneAxes(opt: Record<string, any>) {
  const axes: any[] = Array.isArray(opt.xAxis)
    ? opt.xAxis
    : opt.xAxis
    ? [opt.xAxis]
    : [];
  for (const axis of axes) {
    if (!axis || axis.type === "value") continue;
    const cats: string[] = axis.data ?? [];
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
    smooth: type !== "bar",
    areaStyle: type === "area" ? { opacity: 0.18 } : undefined,
  }));
  return tuneAxes(opt);
}

/** A chart that morphs between bar / line / area / pie, with export + fullscreen. */
export function ChartCard({
  option,
  inferred,
}: {
  option: Record<string, unknown>;
  inferred: boolean;
}) {
  const guess: ChartType =
    (option as any)?.series?.[0]?.type === "line" ? "line" : "bar";
  const [type, setType] = useState<ChartType>(guess);
  const [full, setFull] = useState(false);
  const inst = useRef<ECharts | null>(null);

  const shaped = useMemo(() => morph(option as any, type), [option, type]);

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
