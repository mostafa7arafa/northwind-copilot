"use client";

import {
  type ColumnDef,
  type SortingState,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ChevronsUpDown, Download } from "lucide-react";
import { useMemo, useState } from "react";
import type { TableData } from "@/lib/types";
import { GhostButton, Panel } from "./primitives";
import { cn } from "@/lib/cn";

type Row = Record<string, string | number | null>;

const isNum = (v: unknown): v is number => typeof v === "number";
const fmt = (v: string | number | null) =>
  isNum(v) ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : v ?? "—";

/** Interactive result grid: sortable, sticky header, numeric right-align, CSV export. */
export function ResultsTable({ data }: { data: TableData }) {
  const [sorting, setSorting] = useState<SortingState>([]);

  const rows = useMemo<Row[]>(
    () => data.rows.map((r) => Object.fromEntries(data.columns.map((c, i) => [c, r[i]]))),
    [data]
  );

  const numericCols = useMemo(
    () =>
      new Set(
        data.columns.filter((_, i) => data.rows.some((r) => isNum(r[i])))
      ),
    [data]
  );

  const columns = useMemo<ColumnDef<Row>[]>(
    () =>
      data.columns.map((c) => ({
        // Use an explicit id + accessorFn rather than accessorKey: aggregate
        // column names like "SUM(od.UnitPrice * ...)" contain dots, which
        // accessorKey interprets as a nested path — yielding undefined ("—").
        id: c,
        accessorFn: (row: Row) => row[c],
        header: c,
      })),
    [data]
  );

  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  const exportCsv = () => {
    const esc = (v: unknown) => {
      const s = v == null ? "" : String(v);
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const csv = [
      data.columns.map(esc).join(","),
      ...data.rows.map((r) => r.map(esc).join(",")),
    ].join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = "results.csv";
    a.click();
  };

  return (
    <Panel
      eyebrow="Results"
      title={
        <span className="tape text-ink-dim">
          {data.rows.length} row{data.rows.length === 1 ? "" : "s"}
          {data.truncated && " · showing first 500"}
        </span>
      }
      actions={
        <GhostButton title="Download CSV" onClick={exportCsv}>
          <Download size={13} /> CSV
        </GhostButton>
      }
    >
      <div className="max-h-[420px] overflow-auto">
        <table className="w-full border-collapse text-[13px]">
          <thead className="sticky top-0 z-10 bg-surface">
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {hg.headers.map((h) => {
                  const sorted = h.column.getIsSorted();
                  const right = numericCols.has(h.column.id);
                  return (
                    <th
                      key={h.id}
                      onClick={h.column.getToggleSortingHandler()}
                      className={cn(
                        "cursor-pointer select-none border-b border-hairline px-3 py-2.5 font-medium text-ink-dim transition-colors hover:text-ink",
                        right ? "text-right" : "text-left"
                      )}
                    >
                      <span className={cn("inline-flex items-center gap-1", right && "flex-row-reverse")}>
                        {flexRender(h.column.columnDef.header, h.getContext())}
                        {sorted === "asc" ? (
                          <ArrowUp size={12} className="text-electric" />
                        ) : sorted === "desc" ? (
                          <ArrowDown size={12} className="text-electric" />
                        ) : (
                          <ChevronsUpDown size={12} className="text-ink-faint" />
                        )}
                      </span>
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id} className="group transition-colors hover:bg-surface-2">
                {row.getVisibleCells().map((cell) => {
                  const right = numericCols.has(cell.column.id);
                  return (
                    <td
                      key={cell.id}
                      className={cn(
                        "border-b border-hairline/60 px-3 py-2 text-ink/90",
                        right ? "tape text-right" : "text-left"
                      )}
                    >
                      {fmt(cell.getValue() as string | number | null)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
