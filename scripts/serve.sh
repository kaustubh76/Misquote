#!/usr/bin/env sh
# The API and the worker that drains its queue, in one container.
#
#   scripts/serve.sh          # what Render's startCommand runs
#
# ## Why both processes live here
#
# `render.yaml` used to declare the worker as a second Render service and leave
# it commented out, because background workers need a paid plan. That framing
# was wrong twice over.
#
# A second *service* would not have worked at any price without more plumbing:
# Render services do not share a filesystem, and the queue is `jobs.db` on disk,
# so a worker in another container would poll an empty database while jobs piled
# up in the API's.
#
# And a second service was never what the worker needed. `ops/worker.py` gives
# three reasons it cannot be a thread inside uvicorn — `ranges.quote()` is
# process-global non-reentrant, `fork_map` must fork from a single-threaded
# parent, and the queue must drain without the API extra installed. Every one of
# them is satisfied by a separate **process**. None of them asks for a separate
# host. Two processes in one container, one filesystem, one `MISQUOTE_JOBS_DB`.
#
# ## exec, and what happens when either half dies
#
# The worker goes to the background and uvicorn is `exec`ed, so it inherits this
# shell's pid: Render's SIGTERM reaches the server directly rather than a shell
# that would have to forward it, and a crashed server ends the container so the
# platform restarts it.
#
# The worker gets no such supervision, on purpose. If it dies the API keeps
# serving, `jobs.worker_last_seen` goes stale, and `POST /quote` says so in the
# response — which is a better failure than a restart loop that takes the whole
# service down with it. A hire still answers; it answers that nothing is
# draining.
set -eu

if [ "${MISQUOTE_API_WORKER:-1}" != "0" ]; then
    # `--once` is deliberately not used: this drains forever, and one bad job
    # fails that job rather than the loop (`run_one` finishes every exit path).
    python -m misquote.ops.worker &
    echo "serve.sh: worker started (pid $!), jobs db ${MISQUOTE_JOBS_DB:-data/jobs.db}"
else
    echo "serve.sh: MISQUOTE_API_WORKER=0 — API only, jobs will queue undrained"
fi

exec uvicorn misquote.api.service:app --host 0.0.0.0 --port "${PORT:-8000}"
