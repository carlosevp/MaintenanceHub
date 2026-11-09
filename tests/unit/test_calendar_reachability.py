from maintenancehub_api.domain.calendar_reachability import assess_public_base_url


def test_missing_base_url():
    r = assess_public_base_url("")
    assert r["configured"] is False
    assert r["microsoft_cloud_reachable"] is False
    assert r["code"] == "missing"


def test_localhost_not_reachable():
    r = assess_public_base_url("http://localhost:8000")
    assert r["code"] == "internal_only"
    assert r["microsoft_cloud_reachable"] is False


def test_openshift_svc_not_reachable():
    r = assess_public_base_url("https://maintenancehub-api.apps.svc")
    assert r["code"] == "internal_only"


def test_http_public_not_https():
    r = assess_public_base_url("http://maintenancehub.example.com")
    assert r["code"] == "not_https"
    assert r["microsoft_cloud_reachable"] is False


def test_https_public_ok():
    r = assess_public_base_url("https://maintenancehub.example.com")
    assert r["code"] == "ok"
    assert r["microsoft_cloud_reachable"] is True
    assert r["subscription_supported"] is True
