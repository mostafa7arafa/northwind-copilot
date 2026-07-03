"use client";

import * as echarts from "echarts";
import { useEffect, useRef } from "react";
import { THEME_NAME, TRADING_DESK_THEME } from "@/lib/echartsTheme";

let registered = false;

/** A themed, auto-resizing ECharts canvas driven by an `option` object. */
export function EChart({
  option,
  height = 320,
  onInit,
}: {
  option: Record<string, unknown>;
  height?: number | string;
  onInit?: (chart: echarts.ECharts) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!registered) {
      echarts.registerTheme(THEME_NAME, TRADING_DESK_THEME);
      registered = true;
    }
    if (!ref.current) return;
    chart.current = echarts.init(ref.current, THEME_NAME, { renderer: "canvas" });
    onInit?.(chart.current);
    const ro = new ResizeObserver(() => chart.current?.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      chart.current?.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    chart.current?.setOption(option, true);
    chart.current?.resize();
  }, [option]);

  return <div ref={ref} style={{ width: "100%", height }} />;
}
