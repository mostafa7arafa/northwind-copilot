"use client";

/** Shimmer placeholders shown while a stage is still working. */

export function SqlSkeleton() {
  return (
    <div className="space-y-2 p-4">
      {[70, 42, 88, 55].map((w, i) => (
        <div key={i} className="skeleton h-3" style={{ width: `${w}%` }} />
      ))}
    </div>
  );
}

export function TableSkeleton() {
  return (
    <div className="space-y-2 p-4">
      <div className="skeleton h-7 w-full" />
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="skeleton h-5" style={{ width: `${95 - i * 6}%` }} />
      ))}
    </div>
  );
}

export function ChartSkeleton() {
  return (
    <div className="flex h-[280px] items-end gap-3 p-6">
      {[40, 68, 52, 84, 60, 74, 46].map((h, i) => (
        <div key={i} className="skeleton flex-1" style={{ height: `${h}%` }} />
      ))}
    </div>
  );
}
