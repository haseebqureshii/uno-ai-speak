interface ProgressProps {
  value: number;
  max?: number;
  className?: string;
}

export function Progress({ value, max = 100, className = "" }: ProgressProps) {
  const percentage = Math.min(100, Math.max(0, (value / max) * 100));
  return (
    <div className={`h-2 w-full overflow-hidden rounded-full bg-slate-200 ${className}`}>
      <div
        className="h-full rounded-full bg-tutor-500 transition-all"
        style={{ width: `${percentage}%` }}
        aria-valuemin={0}
        aria-valuemax={max}
        aria-valuenow={value}
        role="progressbar"
      />
    </div>
  );
}
