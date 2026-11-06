/**
 * Dependency-free MaintenanceHub banner embed (IIFE).
 * Serves browsers that cannot use ES modules / npm.
 * Same public DTO + dismiss / theme behavior as @maintenancehub/banner.
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

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function asPresentation(raw, kind, status) {
    if (
      raw === "outage" ||
      raw === "in_progress" ||
      raw === "extended" ||
      raw === "verifying" ||
      raw === "upcoming"
    ) {
      return raw;
    }
    if (kind === "manual_outage" && (status === "in_progress" || status === "extended")) {
      return "outage";
    }
    if (status === "extended") return "extended";
    if (status === "verifying") return "verifying";
    if (status === "in_progress") return "in_progress";
    return "upcoming";
  }

  function sanitize(raw) {
    if (!Array.isArray(raw)) return [];
    return raw.map(function (item) {
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
      };
    });
  }

  function formatWindow(start, end) {
    try {
      return new Date(start).toLocaleString() + " → " + new Date(end).toLocaleString();
    } catch (e) {
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
      var rev = msg.revision || msg.ends_at + "|" + msg.status;
      return stored === rev;
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

  function render(messages, className, theme, showDismiss) {
    className = className || "mh-banner";
    theme = theme || "light";
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
    var items = messages
      .map(function (m) {
        var presentation = asPresentation(m.presentation, m.kind, m.status);
        var outage = presentation === "outage" || m.kind === "manual_outage";
        var dismissBtn =
          showDismiss && m.dismissible
            ? '<button type="button" class="' +
              className +
              '__dismiss" data-mh-dismiss="' +
              escapeHtml(m.id) +
              '" aria-label="Dismiss upcoming notice">Dismiss</button>'
            : "";
        return (
          '<li class="' +
          className +
          "__item " +
          (outage ? className + "__item--outage " : "") +
          className +
          "__item--" +
          presentation +
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
          escapeHtml(formatWindow(m.starts_at, m.ends_at)) +
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
      })
      .join("");
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
      "</ul></aside>"
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
    var theme = opts.theme || "light";
    var allowDismiss = opts.dismissible !== false;
    var cache = [];
    var timer;

    function onClick(ev) {
      var t = ev.target;
      if (!t || !t.closest) return;
      var btn = t.closest("[data-mh-dismiss]");
      if (!btn) return;
      var id = btn.getAttribute("data-mh-dismiss");
      var msg = null;
      for (var i = 0; i < cache.length; i++) {
        if (cache[i].id === id) msg = cache[i];
      }
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
          el.innerHTML = render(visible, className, theme, allowDismiss);
        })
        .catch(function (err) {
          el.innerHTML =
            '<div class="' +
            className +
            " " +
            className +
            '--error" data-theme="' +
            theme +
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
    version: "0.2.0",
  };
})(typeof window !== "undefined" ? window : globalThis);
