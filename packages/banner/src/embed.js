/**
 * Dependency-free MaintenanceHub banner embed (IIFE) — M18 harden.
 * Compact primary + View additional; Intl times; dismiss revision; XSS-escaped.
 */
(function (global) {
  "use strict";

  var FORBIDDEN = {
    description: 1,
    timeline: 1,
    created_by: 1,
    updated_by: 1,
    raw_payload: 1,
    internal_notes: 1,
    note: 1,
    client_secret: 1,
    access_token: 1,
    password: 1,
  };
  var RANK = { outage: 0, extended: 1, in_progress: 2, verifying: 3, upcoming: 4 };

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function asPresentation(raw, kind, status) {
    if (
      raw === "outage" ||
      raw === "in_progress" ||
      raw === "extended" ||
      raw === "verifying" ||
      raw === "upcoming"
    )
      return raw;
    if (kind === "manual_outage" && (status === "in_progress" || status === "extended"))
      return "outage";
    if (status === "extended") return "extended";
    if (status === "verifying") return "verifying";
    if (status === "in_progress") return "in_progress";
    return "upcoming";
  }

  function logicalKey(m) {
    var eventId = m.event_id || m.id;
    if (m.occurrence_starts_at) return eventId + "|" + m.occurrence_starts_at;
    return eventId + "|" + m.id;
  }

  function normalize(list) {
    var best = {};
    list.forEach(function (m) {
      var key = logicalKey(m);
      var prev = best[key];
      if (!prev) {
        best[key] = m;
        return;
      }
      var pr = RANK[prev.presentation] != null ? RANK[prev.presentation] : 9;
      var nr = RANK[m.presentation] != null ? RANK[m.presentation] : 9;
      if (nr < pr) best[key] = m;
      else if (nr === pr && m.starts_at + "|" + m.id < prev.starts_at + "|" + prev.id) best[key] = m;
    });
    return Object.keys(best)
      .map(function (k) {
        return best[k];
      })
      .sort(function (a, b) {
        var ra = RANK[a.presentation] != null ? RANK[a.presentation] : 9;
        var rb = RANK[b.presentation] != null ? RANK[b.presentation] : 9;
        if (ra !== rb) return ra - rb;
        if (a.starts_at !== b.starts_at) return a.starts_at < b.starts_at ? -1 : 1;
        return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
      });
  }

  function sanitize(raw) {
    if (!Array.isArray(raw)) return [];
    return normalize(
      raw.map(function (item) {
        var src = item && typeof item === "object" ? item : {};
        var clean = {};
        Object.keys(src).forEach(function (k) {
          if (FORBIDDEN[k]) return;
          if (k.indexOf("secret") >= 0 || k.indexOf("password") >= 0) return;
          clean[k] = src[k];
        });
        var kind = String(clean.kind || "");
        var status = String(clean.status || "");
        var presentation = asPresentation(clean.presentation, kind, status);
        return {
          id: String(clean.id || ""),
          event_id: clean.event_id != null ? String(clean.event_id) : undefined,
          kind: kind,
          title: String(clean.title || ""),
          status: status,
          presentation: presentation,
          starts_at: String(clean.starts_at || ""),
          ends_at: String(clean.ends_at || ""),
          expected_impact: clean.expected_impact != null ? clean.expected_impact : null,
          approval_state: String(clean.approval_state || ""),
          revision: clean.revision != null ? String(clean.revision) : undefined,
          dismissible:
            typeof clean.dismissible === "boolean"
              ? clean.dismissible
              : presentation === "upcoming",
          occurrence_starts_at:
            clean.occurrence_starts_at != null ? String(clean.occurrence_starts_at) : null,
          status_path: clean.status_path != null ? String(clean.status_path) : null,
        };
      }),
    );
  }

  function resolveTz(explicit) {
    if (explicit) return explicit;
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone;
    } catch (e) {
      return undefined;
    }
  }

  function formatWindow(start, end, locale, timeZone) {
    try {
      var s = new Date(start);
      var e = new Date(end);
      var opts = { dateStyle: "medium", timeStyle: "short" };
      var tz = resolveTz(timeZone);
      if (tz) opts.timeZone = tz;
      var fmt = new Intl.DateTimeFormat(locale, opts);
      return fmt.format(s) + " → " + fmt.format(e);
    } catch (err) {
      return start + " → " + end;
    }
  }

  function kindLabel(kind) {
    return kind === "manual_outage" ? "Outage" : "Maintenance";
  }

  function presentationLabel(p) {
    if (p === "outage") return "Outage";
    if (p === "in_progress") return "In progress";
    if (p === "extended") return "Extended";
    if (p === "verifying") return "Verifying";
    return "Upcoming";
  }

  function storageKey(prefix, app, env, id) {
    return prefix + ":" + app + ":" + (env || "*") + ":" + id;
  }

  function isDismissed(msg, opts) {
    if (!msg.dismissible) return false;
    try {
      var key = storageKey(
        opts.storageKey || "mh-banner-dismiss",
        opts.applicationKey,
        opts.environmentKey,
        msg.id,
      );
      var stored = localStorage.getItem(key);
      if (!stored) return false;
      return stored === (msg.revision || msg.ends_at + "|" + msg.status);
    } catch (e) {
      return false;
    }
  }

  function dismiss(msg, opts) {
    if (!msg.dismissible) return;
    try {
      var key = storageKey(
        opts.storageKey || "mh-banner-dismiss",
        opts.applicationKey,
        opts.environmentKey,
        msg.id,
      );
      localStorage.setItem(key, msg.revision || msg.ends_at + "|" + msg.status);
    } catch (e) {
      /* ignore */
    }
  }

  function renderItem(m, className, opts, primary) {
    var presentation = asPresentation(m.presentation, m.kind, m.status);
    var outage = presentation === "outage";
    var dismissBtn =
      opts.showDismiss && m.dismissible
        ? '<button type="button" class="' +
          className +
          '__dismiss" data-mh-dismiss="' +
          escapeHtml(m.id) +
          '" aria-label="Dismiss upcoming notice">Dismiss</button>'
        : "";
    var statusHref =
      opts.statusPageBaseUrl && m.status_path
        ? String(opts.statusPageBaseUrl).replace(/\/$/, "") +
          (m.status_path.charAt(0) === "/" ? m.status_path : "/" + m.status_path)
        : null;
    var statusLink = statusHref
      ? '<a class="' +
        className +
        '__status-link" href="' +
        escapeHtml(statusHref) +
        '" rel="noopener noreferrer">Status</a>'
      : "";
    return (
      '<li class="' +
      className +
      "__item " +
      (outage ? className + "__item--outage " : "") +
      className +
      "__item--" +
      presentation +
      (primary ? " " + className + "__item--primary" : "") +
      '">' +
      '<div class="' +
      className +
      '__meta">' +
      '<span class="' +
      className +
      '__kind">' +
      kindLabel(m.kind) +
      "</span>" +
      '<span class="' +
      className +
      '__status">' +
      presentationLabel(presentation) +
      "</span>" +
      statusLink +
      dismissBtn +
      "</div>" +
      '<strong class="' +
      className +
      '__title">' +
      escapeHtml(m.title) +
      "</strong>" +
      '<span class="' +
      className +
      '__window">' +
      escapeHtml(formatWindow(m.starts_at, m.ends_at, opts.locale, opts.timeZone)) +
      "</span>" +
      (m.expected_impact
        ? '<span class="' +
          className +
          '__impact">Impact: ' +
          escapeHtml(m.expected_impact) +
          "</span>"
        : "") +
      "</li>"
    );
  }

  function render(messages, className, opts) {
    className = className || "mh-banner";
    var theme = opts.theme || "light";
    var compact = opts.compact !== false;
    var expanded = !!opts.expanded;
    if (!messages.length) {
      return (
        '<div class="' +
        className +
        " " +
        className +
        '--empty" data-theme="' +
        theme +
        '" role="status" hidden></div>'
      );
    }
    var primary = messages[0];
    var additional = messages.slice(1);
    var showAll = !compact || expanded || !additional.length;
    var visible = showAll ? messages : [primary];
    var items = visible
      .map(function (m, i) {
        return renderItem(m, className, opts, i === 0);
      })
      .join("");
    var toggle =
      compact && additional.length
        ? '<button type="button" class="' +
          className +
          '__more" data-mh-toggle-more aria-expanded="' +
          (showAll ? "true" : "false") +
          '">' +
          (showAll ? "Show less" : "View " + additional.length + " additional") +
          "</button>"
        : "";
    return (
      '<aside class="' +
      className +
      '" data-theme="' +
      theme +
      '" role="region" aria-label="Maintenance and outage communications" aria-live="polite">' +
      '<p class="' +
      className +
      '__heading">MaintenanceHub notices</p>' +
      '<ul class="' +
      className +
      '__list">' +
      items +
      "</ul>" +
      toggle +
      "</aside>"
    );
  }

  function fetchMessages(opts) {
    var base = String(opts.apiBaseUrl || "").replace(/\/$/, "");
    var params = new URLSearchParams({ application_key: opts.applicationKey });
    if (opts.environmentKey) params.set("environment_key", opts.environmentKey);
    if (opts.advanceHours != null) params.set("advance_hours", String(opts.advanceHours));
    var path = opts.internal ? "/api/v1/internal/banner" : "/api/v1/public/banner";
    var headers = { Accept: "application/json" };
    if (opts.accessToken) headers.Authorization = "Bearer " + opts.accessToken;
    return fetch(base + path + "?" + params, { headers }).then(function (res) {
      if (!res.ok) throw new Error("Banner fetch failed: " + res.status);
      return res.json().then(sanitize);
    });
  }

  function mount(opts) {
    var el =
      typeof opts.target === "string" ? document.querySelector(opts.target) : opts.target;
    if (!el) throw new Error("Banner target not found: " + String(opts.target));
    var className = opts.className || "mh-banner";
    var allowDismiss = opts.dismissible !== false;
    var compact = opts.compact !== false;
    var expanded = !!opts.expanded;
    var cache = [];
    var timer;

    function paint(visible) {
      el.innerHTML = render(visible, className, {
        theme: opts.theme || "light",
        showDismiss: allowDismiss,
        timeZone: opts.timeZone,
        locale: opts.locale,
        statusPageBaseUrl: opts.statusPageBaseUrl,
        compact: compact,
        expanded: expanded,
      });
    }

    function onClick(ev) {
      var t = ev.target;
      if (!t || !t.closest) return;
      var more = t.closest("[data-mh-toggle-more]");
      if (more) {
        expanded = !expanded;
        paint(
          allowDismiss
            ? cache.filter(function (m) {
                return !isDismissed(m, opts);
              })
            : cache,
        );
        return;
      }
      var btn = t.closest("[data-mh-dismiss]");
      if (!btn) return;
      var id = btn.getAttribute("data-mh-dismiss");
      var msg = null;
      for (var i = 0; i < cache.length; i++) if (cache[i].id === id) msg = cache[i];
      if (!msg) return;
      dismiss(msg, opts);
      refresh();
    }
    el.addEventListener("click", onClick);

    function refresh() {
      return fetchMessages(opts)
        .then(function (raw) {
          cache = raw;
          var visible = allowDismiss
            ? raw.filter(function (m) {
                return !isDismissed(m, opts);
              })
            : raw;
          paint(visible);
        })
        .catch(function (err) {
          el.innerHTML =
            '<div class="' +
            className +
            " " +
            className +
            '--error" data-theme="' +
            (opts.theme || "light") +
            '" role="alert">Unable to load maintenance notices.</div>';
          if (typeof console !== "undefined" && console.warn) {
            console.warn("[MaintenanceHub banner]", err);
          }
        });
    }

    refresh();
    var interval = opts.pollIntervalMs == null ? 60000 : opts.pollIntervalMs;
    if (interval > 0) timer = setInterval(refresh, interval);

    return {
      refresh: refresh,
      setExpanded: function (v) {
        expanded = !!v;
        paint(
          allowDismiss
            ? cache.filter(function (m) {
                return !isDismissed(m, opts);
              })
            : cache,
        );
      },
      destroy: function () {
        if (timer) clearInterval(timer);
        el.removeEventListener("click", onClick);
        el.innerHTML = "";
      },
    };
  }

  global.MaintenanceHubBanner = {
    mount: mount,
    fetchMessages: fetchMessages,
    sanitize: sanitize,
    version: "0.2.1",
  };
})(typeof window !== "undefined" ? window : globalThis);
