#!/bin/bash
# =====================================================================
# Wardrobe-AI: finish + verify the cloud (Atlas + Cloudinary) setup on
# THIS computer, in one command:
#
#     bash scripts/finish_cloud_setup.sh [email-of-an-account-to-check]
#
# What it does (nothing is deleted, no password is changed):
#   1. runs the backend unit tests (offline, no real data touched)
#   2. account_doctor --all --fix : normalises stored email casing and
#      creates the unique indexes (one account per email, no duplicate
#      migrated items) - reports anything needing a human decision
#   3. starts a TEMPORARY backend on port 5055 (your usual 5001 backend
#      is not touched), then runs the end-to-end cloud check: two
#      independent logins to one test account, duplicate-registration
#      refusal, a real upload to Cloudinary + Atlas, the upload visible
#      from the second session, recommendations, cleanup
#   4. confirms the given account exists (read-only probe) and
#      prints its cloud wardrobe status
#   5. pushes the committed code to GitHub so the other laptop can
#      `git pull` it
#
# Everything is also written to cloud_setup_report.txt (gitignored,
# contains no secrets) so the result can be checked afterwards.
# =====================================================================

cd "$(dirname "$0")/.." || exit 1
REPORT="cloud_setup_report.txt"
PROBE_EMAIL="${1:-}"
PORT=5055

exec > >(tee "$REPORT") 2>&1
echo "Wardrobe-AI cloud setup check - $(date)"
echo "Computer: $(hostname)"

if [ -f ai_env/bin/activate ]; then
  source ai_env/bin/activate
else
  echo "ai_env not found - activate your virtualenv first"; exit 1
fi

pip install -q certifi dnspython cloudinary >/dev/null 2>&1

step() { echo; echo "=================================================="; echo "$1"; echo "=================================================="; }
FAILED=0

step "1. Unit tests"
python -m unittest discover -s backend/tests -t . 2>&1 | tail -25
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1

step "2. Account check + safe repair (Atlas)"
python -m backend.account_doctor --all --fix || FAILED=1

step "3. End-to-end cloud check (temporary backend on port $PORT)"
SEND_LOGIN_EMAIL=false SEND_WELCOME_EMAIL=false python - <<EOF > backend_e2e.log 2>&1 &
import backend.app as a
a.INDEX_PROBLEMS = a.ensure_indexes()
a.app.run(port=$PORT, debug=False, use_reloader=False)
EOF
BACKEND_PID=$!
for i in $(seq 1 90); do
  curl -s "http://localhost:$PORT/api/health" >/dev/null 2>&1 && break
  sleep 2
done
python -m backend.cloud_e2e_check --base-url "http://localhost:$PORT" ${PROBE_EMAIL:+--probe-email "$PROBE_EMAIL"} || FAILED=1
kill $BACKEND_PID 2>/dev/null
echo "(backend log: backend_e2e.log)"
grep -iE "error|traceback|failed" backend_e2e.log | grep -v "GET /api/health" | tail -15

step "4. Cloud wardrobe status for ${PROBE_EMAIL:-(no account given)}"
[ -n "$PROBE_EMAIL" ] && python -m backend.migrate_to_atlas --only-email "$PROBE_EMAIL" --verify-only
[ -n "$PROBE_EMAIL" ] && python -m backend.account_doctor --email "$PROBE_EMAIL"

step "5. Publish code to GitHub"
git status --short | grep -v '^??' | head -5
git push origin main && echo "PUSHED" || { echo "PUSH FAILED"; FAILED=1; }

echo
if [ $FAILED -eq 0 ]; then echo "RESULT: ALL CHECKS PASSED"; else echo "RESULT: SOME CHECKS FAILED (see above)"; fi
