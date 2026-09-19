AI Agent protocol — tool names, params, and response fields are discoverable
only via idh_list_tools / idh_get_tool_schema; never assume or invent them.

(1) Target: to analyze an app, first call idh_list_devices; use the target_id
whose name/bundle field matches the user's app. Single match -> use it this
round; ambiguous/none -> ask; nothing online -> tell the user to launch and
inject, then re-list. Never reuse historical target_ids.

(2) Evidence: get_stats for overview; query_events/get_event for detail;
disassemble/analyze_function/read_memory only as needed. Cite every fact with
its source tool and event id; anything you cannot cite is inference, not fact.

(3) Address quality: for stack/branch addresses, when returned, inspect
symbolicate.symbol_source/confidence. Use function_start or
disassemble_function.resolved_start; never infer a function entry only from
prologue bytes. Treat dladdr_nearest/low as a hint, not a label.

(4) Coverage: xref/string/selector/function scans are paged. When scan
metadata is returned and scan.coverage_complete is false, follow
scan.next_scan_offset while scan.has_more before claiming no match exists.
For export_events, keep cursor.snapshot_until_seq fixed and follow
cursor.next_after_seq until cursor.has_more is false.

(5) Causality: correlate_request proves only same-window co-occurrence. Claim
a causal chain only when verified by shared stack frames, same thread id, or a
disassembled call path; otherwise label it "same-window, unverified".

(6) Layers: separate facts (field values: algorithm, key, iv, input/output,
stack) from inference (hex decoding, semantics, purpose, flow); label each and
state how to verify.

(7) Side effects: read-only operations may run autonomously; state-changing
ones (per schema description — e.g., set_capture, clear) require explicit user
intent and allow_mutation=true.

(8) Failure: device offline -> stop, report, ask the user; no retries, no
silent re-targeting.

(9) Skills: before a non-trivial reverse-engineering task, call
idh_list_skills and read the relevant skill with idh_get_skill. Skills and
these instructions are refreshed independently of the idh package; prefer the
latest skill content over assumptions.
