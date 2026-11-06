/**
 * Pure helpers for Impact Analysis preview session stability (M14 harden).
 * Keeps request sequencing / selection fingerprints testable without React.
 */

export type ImpactSeed = {
  target_type: string;
  target_id: string;
  environment_id?: string | null;
};

export type ExclusionRow = ImpactSeed & { reason?: string };

export type ConfirmReady = {
  revisionToken: string;
  exclusions: ExclusionRow[];
  manualAdditions: ImpactSeed[];
  includeDownstream: ImpactSeed[];
  selectionFingerprint: string;
};

export function impactSeedKey(s: ImpactSeed): string {
  return `${s.target_type}:${s.target_id}:${s.environment_id ?? ""}`;
}

export function selectionFingerprint(
  exclusions: ExclusionRow[],
  manuals: ImpactSeed[],
  includeDownstream: ImpactSeed[],
): string {
  const ex = exclusions
    .map((e) => `${impactSeedKey(e)}:${e.reason ?? ""}`)
    .sort()
    .join(",");
  const man = manuals.map(impactSeedKey).sort().join(",");
  const inc = includeDownstream.map(impactSeedKey).sort().join(",");
  return `ex=${ex}|man=${man}|inc=${inc}`;
}

export function seedsFingerprint(seeds: ImpactSeed[]): string {
  return seeds.map(impactSeedKey).sort().join("|");
}

/** Bound concurrent preview calls: only the latest request id may commit. */
export function createPreviewRequestGate() {
  let latest = 0;
  return {
    next(): number {
      latest += 1;
      return latest;
    },
    isCurrent(id: number): boolean {
      return id === latest;
    },
    get current(): number {
      return latest;
    },
  };
}
