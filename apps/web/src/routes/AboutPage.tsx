import { Link } from "react-router-dom";

export function AboutPage() {
  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div className="mh-panel p-6">
        <h1 className="font-display text-3xl font-semibold">About MaintenanceHub</h1>
        <p className="mt-3 text-ink-700">
          MaintenanceHub is an internal <strong>maintenance and outage communication</strong>{" "}
          platform. It is <strong>not</strong> a monitoring product — status is published by people,
          not probes or telemetry.
        </p>
        <h2 className="mt-6 font-display text-xl font-semibold">Platform health</h2>
        <p className="mt-2 text-sm text-ink-600">
          <code>/healthz</code> and <code>/readyz</code> exist only for MaintenanceHub pod
          liveness/readiness. They do not reflect the health of applications in the catalog.
        </p>
        <h2 className="mt-6 font-display text-xl font-semibold">Unsupported / incomplete</h2>
        <ul className="mt-2 list-inside list-disc space-y-1 text-sm text-ink-700">
          <li>Application/infra uptime monitoring, synthetics, auto-status from telemetry</li>
          <li>Direct Microsoft Teams APIs or webhooks (use email / Power Automate bridge)</li>
          <li>ServiceNow push/webhooks (poll adapter only; push interface stubbed)</li>
          <li>Digest notification worker (subscription digest_mode is schema-ready)</li>
          <li>Live OIDC token exchange / LDAP bind until IdP endpoints are configured</li>
        </ul>
        <p className="mt-4 text-sm text-ink-600">
          Full list: repository file <code>docs/LIMITATIONS.md</code>.
        </p>
        <Link to="/" className="mh-btn mt-6 inline-flex">
          Back to dashboard
        </Link>
      </div>
    </div>
  );
}
