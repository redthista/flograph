"""Dataiku Action

Make something happen in a Dataiku DSS project — after a **Dataiku Upload**,
or on its own. No data flows through; wire it on an order edge downstream of
whatever should trigger it. Emits `ok` (did it succeed) and a one-row
`report` table (outcome, timing, URL) for a dashboard or a **Notify**.

**Operation**:

  • **run scenario** — fire a scenario by id; optionally wait for it and fail
    the node if the run doesn't end SUCCESS
  • **build** — build a dataset or a managed folder (`NON_RECURSIVE_FORCED_BUILD`
    by default; `RECURSIVE_BUILD` walks upstream)
  • **set variables** — write one project variable (standard or local); the
    value is the JSON in **Value** or, if that's blank, whatever is wired into
    the `trigger` input

Leave **API key** blank to fall back to `$DKU_API_KEY`. Uses the external
`dataikuapi` client. **On failure** = *warn* turns a failed run into `ok =
False` + a log line instead of stopping the flow.
"""
NODE = {
    "label": "Dataiku Action",
    "category": "Connect",
    "version": "1.0",
    "inputs": [("trigger", "any", {"optional": True})],
    "outputs": [("ok", "bool"), ("report", "dataframe")],
}
PARAMS = [
    {"name": "host", "type": "string", "label": "DSS URL",
     "default": "", "placeholder": "https://dss-host:11200"},
    {"name": "api_key", "type": "password", "label": "API key",
     "default": "", "placeholder": "blank = $DKU_API_KEY / ${env:DKU_API_KEY}"},
    {"name": "project_key", "type": "string", "label": "Project key",
     "default": "", "placeholder": "e.g. WORKFORCE_LOADING"},

    {"name": "operation", "type": "choice", "label": "Operation",
     "options": ["run scenario", "build", "set variables"],
     "default": "run scenario"},

    {"name": "scenario_id", "type": "string", "label": "Scenario id",
     "default": "",
     "visible_when": {"operation": ["run scenario"]}},
    {"name": "params_json", "type": "text", "label": "Scenario params (JSON)",
     "default": "", "placeholder": "{\"projectVariables\": {\"day\": \"2026-09-01\"}}",
     "visible_when": {"operation": ["run scenario"]}},

    {"name": "object_type", "type": "choice", "label": "Build",
     "options": ["dataset", "managed folder"], "default": "dataset",
     "visible_when": {"operation": ["build"]}},
    {"name": "object_id", "type": "string", "label": "Name / id",
     "default": "",
     "visible_when": {"operation": ["build"]}},
    {"name": "build_mode", "type": "choice", "label": "Build mode",
     "options": ["NON_RECURSIVE_FORCED_BUILD", "RECURSIVE_BUILD",
                 "RECURSIVE_FORCED_BUILD", "RECURSIVE_MISSING_ONLY_BUILD"],
     "default": "NON_RECURSIVE_FORCED_BUILD",
     "visible_when": {"operation": ["build"]}},

    {"name": "var_key", "type": "string", "label": "Variable name",
     "default": "",
     "visible_when": {"operation": ["set variables"]}},
    {"name": "var_scope", "type": "choice", "label": "Scope",
     "options": ["standard", "local"], "default": "standard",
     "visible_when": {"operation": ["set variables"]}},
    {"name": "var_value", "type": "text", "label": "Value (JSON)",
     "default": "", "placeholder": "\"2026-09-01\"  or  {\"a\": 1}",
     "visible_when": {"operation": ["set variables"]}},

    {"name": "wait", "type": "bool", "label": "Wait for completion",
     "default": True,
     "visible_when": {"operation": ["run scenario", "build"]}},
    {"name": "on_failure", "type": "choice", "label": "On failure",
     "options": ["fail", "warn"], "default": "fail"},
    {"name": "insecure_tls", "type": "bool", "label": "Disable TLS verification",
     "default": False},
]


def run(ctx, trigger=None):
    import json
    import time

    from flograph.nodes.connect import _dataiku

    p = ctx.params
    op = p.get("operation", "run scenario")
    wait = bool(p.get("wait", True))
    warn = p.get("on_failure", "fail") == "warn"
    client, project = _dataiku.connect(p)
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    t0 = time.time()

    def done(ok, **cols):
        report = _dataiku.report_frame(
            operation=op, ok=ok, started=started,
            duration_s=round(time.time() - t0, 1), **cols)
        return {"ok": bool(ok), "report": report}

    try:
        if op == "run scenario":
            sid = (p.get("scenario_id") or "").strip()
            if not sid:
                raise ValueError("no scenario — set 'Scenario id'")
            params = None
            raw = (p.get("params_json") or "").strip()
            if raw:
                params = json.loads(raw)
            scenario = project.get_scenario(sid)
            ctx.log(f"running scenario {sid}"
                    + (" (waiting)" if wait else ""))
            if wait:
                run_obj = scenario.run_and_wait(params=params, no_fail=True)
                outcome = run_obj.outcome
                return done(outcome == "SUCCESS", scenario=sid,
                            outcome=outcome, run_id=run_obj.id)
            scenario.run(params or {})
            return done(True, scenario=sid, outcome="STARTED")

        if op == "build":
            oid = (p.get("object_id") or "").strip()
            if not oid:
                raise ValueError("no object — set 'Name / id'")
            otype = ("MANAGED_FOLDER" if p.get("object_type") == "managed folder"
                     else "DATASET")
            builder = project.new_job(p.get("build_mode",
                                            "NON_RECURSIVE_FORCED_BUILD"))
            builder.with_output(oid, object_type=otype)
            ctx.log(f"building {otype.lower()} {oid}"
                    + (" (waiting)" if wait else ""))
            if wait:
                job = builder.start_and_wait(no_fail=True)
                state = (job.get_status().get("baseStatus") or {}).get("state")
                return done(state == "DONE", object=oid, state=state,
                            job_id=job.id)
            job = builder.start()
            return done(True, object=oid, state="RUNNING", job_id=job.id)

        if op == "set variables":
            key = (p.get("var_key") or "").strip()
            if not key:
                raise ValueError("no variable — set 'Variable name'")
            raw = (p.get("var_value") or "").strip()
            if raw:
                value = json.loads(raw)
            elif trigger is not None:
                value = trigger
            else:
                raise ValueError("no value — set 'Value (JSON)' or wire one "
                                 "into the trigger input")
            scope = p.get("var_scope", "standard")
            project.update_variables({key: value}, type=scope)
            ctx.log(f"set {scope} variable {key} = {value!r}")
            return done(True, variable=key, scope=scope)

        raise ValueError(f"unknown operation {op!r}")

    except ValueError:
        raise  # config errors always stop the node
    except Exception as exc:  # noqa: BLE001 — DSS / network failure
        if not warn:
            raise
        ctx.log(f"action failed ({exc}) — continuing (on failure = warn)")
        return done(False, error=str(exc)[:300])
