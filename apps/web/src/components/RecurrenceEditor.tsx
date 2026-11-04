import { useEffect, useState } from "react";
import { api } from "@/api/client";

export type RecurrenceValue = {
  freq: string;
  interval: number;
  byweekday: string[];
  bymonthday: number | null;
  until: string;
  count: number | null;
  rrule: string;
};

const WEEKDAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"] as const;

type Props = {
  enabled: boolean;
  onEnabledChange: (v: boolean) => void;
  value: RecurrenceValue;
  onChange: (v: RecurrenceValue) => void;
  startsAt: string;
  endsAt: string;
  timezone: string;
};

export function RecurrenceEditor({
  enabled,
  onEnabledChange,
  value,
  onChange,
  startsAt,
  endsAt,
  timezone,
}: Props) {
  const [summary, setSummary] = useState<string>("");
  const [preview, setPreview] = useState<
    Array<{ starts_at: string; ends_at: string; original_starts_at: string }>
  >([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled || !startsAt || !endsAt) {
      setPreview([]);
      setSummary("");
      return;
    }
    let cancelled = false;
    const t = setTimeout(() => {
      void (async () => {
        try {
          const recurrence: Record<string, unknown> = {
            freq: value.freq,
            interval: value.interval,
          };
          if (value.freq === "CUSTOM" && value.rrule) {
            recurrence.rrule = value.rrule;
          }
          if (value.freq === "WEEKLY" && value.byweekday.length) {
            recurrence.byweekday = value.byweekday;
          }
          if (value.freq === "MONTHLY" && value.bymonthday != null) {
            recurrence.bymonthday = value.bymonthday;
          }
          if (value.until) recurrence.until = new Date(value.until).toISOString();
          if (value.count) recurrence.count = value.count;
          const res = await api.previewRecurrence({
            starts_at: new Date(startsAt).toISOString(),
            ends_at: new Date(endsAt).toISOString(),
            timezone,
            recurrence,
            count: 10,
          });
          if (!cancelled) {
            setSummary(res.summary);
            setPreview(res.occurrences);
            setError(null);
          }
        } catch (err) {
          if (!cancelled) {
            setError(err instanceof Error ? err.message : "Preview failed");
            setPreview([]);
          }
        }
      })();
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [enabled, value, startsAt, endsAt, timezone]);

  function toggleDay(day: string) {
    const set = new Set(value.byweekday);
    if (set.has(day)) set.delete(day);
    else set.add(day);
    onChange({ ...value, byweekday: Array.from(set) });
  }

  return (
    <div className="space-y-3 rounded-md border border-ink-200 bg-ink-50/60 p-4">
      <label className="flex items-center gap-2 text-sm font-semibold text-ink-800">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => onEnabledChange(e.target.checked)}
        />
        Recurring maintenance
      </label>
      {!enabled ? (
        <p className="text-xs text-ink-500">One-time window only.</p>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="mh-label">Frequency</label>
              <select
                className="mh-input"
                value={value.freq}
                onChange={(e) => onChange({ ...value, freq: e.target.value })}
              >
                <option value="WEEKLY">Weekly</option>
                <option value="MONTHLY">Monthly</option>
                <option value="DAILY">Daily</option>
                <option value="CUSTOM">Custom RRULE</option>
              </select>
            </div>
            <div>
              <label className="mh-label">Interval</label>
              <input
                type="number"
                min={1}
                className="mh-input"
                value={value.interval}
                onChange={(e) => onChange({ ...value, interval: Number(e.target.value) || 1 })}
              />
            </div>
          </div>

          {value.freq === "WEEKLY" && (
            <div>
              <p className="mh-label">Weekdays</p>
              <div className="mt-1 flex flex-wrap gap-2">
                {WEEKDAYS.map((d) => (
                  <button
                    key={d}
                    type="button"
                    className={
                      value.byweekday.includes(d)
                        ? "rounded-md bg-ink-900 px-2 py-1 text-xs font-bold text-white"
                        : "rounded-md bg-white px-2 py-1 text-xs font-bold text-ink-700 ring-1 ring-ink-200"
                    }
                    aria-pressed={value.byweekday.includes(d)}
                    onClick={() => toggleDay(d)}
                  >
                    {d}
                  </button>
                ))}
              </div>
            </div>
          )}

          {value.freq === "MONTHLY" && (
            <div>
              <label className="mh-label">Day of month</label>
              <input
                type="number"
                min={1}
                max={31}
                className="mh-input"
                value={value.bymonthday ?? 1}
                onChange={(e) =>
                  onChange({ ...value, bymonthday: Number(e.target.value) || 1 })
                }
              />
            </div>
          )}

          {value.freq === "CUSTOM" && (
            <div>
              <label className="mh-label">RRULE</label>
              <input
                className="mh-input font-mono text-xs"
                placeholder="FREQ=WEEKLY;BYDAY=MO,WE;INTERVAL=1"
                value={value.rrule}
                onChange={(e) => onChange({ ...value, rrule: e.target.value })}
              />
            </div>
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="mh-label">Until (optional)</label>
              <input
                type="datetime-local"
                className="mh-input"
                value={value.until}
                onChange={(e) => onChange({ ...value, until: e.target.value })}
              />
            </div>
            <div>
              <label className="mh-label">Count (optional)</label>
              <input
                type="number"
                min={1}
                className="mh-input"
                value={value.count ?? ""}
                onChange={(e) =>
                  onChange({
                    ...value,
                    count: e.target.value ? Number(e.target.value) : null,
                  })
                }
              />
            </div>
          </div>

          {summary && (
            <p className="text-sm font-medium text-ink-800" aria-live="polite">
              {summary}
            </p>
          )}
          {error && (
            <p className="text-sm text-danger" role="alert">
              {error}
            </p>
          )}
          {preview.length > 0 && (
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">
                Next {preview.length} occurrences
              </p>
              <ol className="mt-2 max-h-40 list-decimal space-y-1 overflow-y-auto pl-5 text-xs text-ink-700">
                {preview.map((o) => (
                  <li key={o.original_starts_at}>
                    {new Date(o.starts_at).toLocaleString()} →{" "}
                    {new Date(o.ends_at).toLocaleString()}
                  </li>
                ))}
              </ol>
            </div>
          )}
        </>
      )}
    </div>
  );
}

export function defaultRecurrence(): RecurrenceValue {
  return {
    freq: "WEEKLY",
    interval: 1,
    byweekday: ["SU"],
    bymonthday: 1,
    until: "",
    count: null,
    rrule: "",
  };
}
