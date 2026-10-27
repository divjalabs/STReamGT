#!/usr/bin/env bash
# Smoke-test the LIVE app: the handful of checks that catch "deployed but broken".
#
#   scripts/smoke.sh                      # anonymous checks only
#   SMOKE_EMAIL=you@lab.org SMOKE_PASSWORD=... scripts/smoke.sh   # also checks a logged-in path
#
# Exits non-zero if any check fails. Read-only: it creates nothing and changes nothing.
set -uo pipefail

APP_URL="${APP_URL:-https://d2qy3qqpz2ebmu.cloudfront.net}"
FAILED=0

pass() { printf '  \033[32m✓\033[0m %s\n' "$1"; }
fail() { printf '  \033[31m✗\033[0m %s\n      %s\n' "$1" "$2"; FAILED=$((FAILED+1)); }

# get <path> -> sets CODE, CTYPE, BODY
get() {
  local out
  out=$(curl -s -m 40 -o /tmp/smoke.body -w '%{http_code} %{content_type}' "$APP_URL$1" ${2:+-H "$2"})
  CODE=${out%% *}; CTYPE=${out#* }; BODY=$(head -c 400 /tmp/smoke.body)
}

echo "Smoke test: $APP_URL"

echo "[1] The site loads"
get /
[ "$CODE" = 200 ] && case "$CTYPE" in text/html*) true;; *) false;; esac \
  && pass "GET / -> 200 html" || fail "GET / -> 200 html" "got $CODE $CTYPE"

echo "[2] A deep SPA link still resolves (single-page-app routing)"
get /projects
[ "$CODE" = 200 ] && case "$CTYPE" in text/html*) true;; *) false;; esac \
  && pass "GET /projects -> 200 html" || fail "GET /projects -> 200 html" "got $CODE $CTYPE"

echo "[3] The API answers, and unauthenticated access is refused"
get /api/auth/me
[ "$CODE" = 401 ] && pass "GET /api/auth/me -> 401" || fail "GET /api/auth/me -> 401" "got $CODE $CTYPE"

echo "[4] An unknown API path returns a JSON 404, NOT the web page"
#     Regression guard: CloudFront's SPA fallback used to rewrite API 403/404 to 200 + index.html,
#     which made failed downloads save the site's HTML as a .csv.
get /api/porting/bogus
if [ "$CODE" = 404 ]; then
  case "$CTYPE" in application/json*) pass "GET /api/porting/bogus -> 404 json";;
    *) fail "unknown API path returns JSON" "got 404 but content-type $CTYPE";; esac
else
  fail "unknown API path returns 404 (not the SPA)" "got $CODE $CTYPE — CloudFront is still rewriting API errors"
fi

echo "[5] Pipeline parameter defaults are readable (job submission depends on this)"
#     Regression guard: the slim Lambda image once shipped without pipeline/bin/parameters.json,
#     which made this 500 and blocked every job submission.
get /api/jobs/parameters/defaults
case "$CODE" in
  200) case "$BODY" in *AlleleAcceptanceThreshold*) pass "GET /api/jobs/parameters/defaults -> 200 with parameters";;
         *) fail "parameter defaults look wrong" "200 but body: $BODY";; esac ;;
  401|403) pass "GET /api/jobs/parameters/defaults -> $CODE (auth required; set SMOKE_EMAIL to check fully)" ;;
  *) fail "GET /api/jobs/parameters/defaults" "got $CODE $CTYPE — $BODY" ;;
esac

echo "[6] Deep health: the dependencies a user hits (database, S3, pipeline parameters)"
#     These fail invisibly: /health kept saying ok while every S3 call was rejected and the
#     pipeline parameters file was missing from the image.
get "/api/health?deep=1"
case "$BODY" in
  *'"status":"ok"'*) pass "GET /api/health?deep=1 -> all dependencies ok" ;;
  *'"checks"'*)      fail "a dependency is unhealthy" "$BODY" ;;
  *)                 fail "GET /api/health?deep=1" "got $CODE $CTYPE — $BODY" ;;
esac

if [ -n "${SMOKE_EMAIL:-}" ] && [ -n "${SMOKE_PASSWORD:-}" ]; then
  echo "[7] Logged-in checks"
  TOKEN=$(curl -s -m 40 -X POST "$APP_URL/api/auth/login" \
    -d "username=$SMOKE_EMAIL&password=$SMOKE_PASSWORD" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin).get("access_token",""))' 2>/dev/null)
  if [ -z "$TOKEN" ]; then
    fail "login" "no token returned for $SMOKE_EMAIL"
  else
    pass "login"
    get /api/auth/me "Authorization: Bearer $TOKEN"
    [ "$CODE" = 200 ] && pass "GET /api/auth/me -> 200" || fail "GET /api/auth/me with token" "got $CODE"
    get /api/jobs/parameters/defaults "Authorization: Bearer $TOKEN"
    case "$BODY" in *AlleleAcceptanceThreshold*) pass "parameter defaults readable";;
      *) fail "parameter defaults readable" "got $CODE $CTYPE — $BODY";; esac
    get /api/kits "Authorization: Bearer $TOKEN"
    [ "$CODE" = 200 ] && pass "GET /api/kits -> 200" || fail "GET /api/kits" "got $CODE"
  fi
else
  echo "[7] Logged-in checks skipped (set SMOKE_EMAIL and SMOKE_PASSWORD to include them)"
fi

rm -f /tmp/smoke.body
echo
if [ "$FAILED" -eq 0 ]; then echo "All checks passed."; else echo "$FAILED check(s) failed."; fi
exit $([ "$FAILED" -eq 0 ] && echo 0 || echo 1)
