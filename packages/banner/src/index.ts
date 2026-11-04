/**
 * MaintenanceHub banner package stub (M12).
 * Do not embed in production until M12 acceptance criteria are met.
 */
export type BannerMessage = {
  id: string;
  kind: string;
  title: string;
  status: string;
  starts_at: string;
  ends_at: string;
  expected_impact?: string;
  approval_state: string;
};

export function createBannerPlaceholder(): string {
  return "[MaintenanceHub banner stub — not implemented until M12]";
}
