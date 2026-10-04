#!/usr/bin/env python3
"""Turn a research subagent's transcript into replay fixtures: one file per web call.

A skill that reads the web cannot be replayed against the web — the pages change. What can be
replayed is exactly what that run received. This script takes a subagent transcript (.jsonl) and
writes every WebSearch and WebFetch result to its own file, in call order:

    python3 trading-plan/evals/scripts/extract_tool_results.py <transcript.jsonl> <out-dir>

    <out-dir>/01-websearch.txt
    <out-dir>/02-webfetch.txt
    ...

Each file is a short header — `query:` for a search; `url:` and `prompt:` for a fetch — a blank
line, and the tool result **verbatim**: 404s, empty pages and pages about the wrong company
included, because those are part of what the run had to work with. Nothing is redacted or
summarised; a human reviews the output before it is committed.

Calls are paired by `tool_use.id` with `tool_result.tool_use_id`. A result's content is either a
string or a list of `{type: text, text}` blocks; both are handled.

Refuses to write into a non-empty directory, so a re-run cannot silently mix two extractions.
Standard library only.
"""
import json
import os
import sys

WEB_TOOLS = {"WebSearch": "websearch", "WebFetch": "webfetch"}


def result_text(content):
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(parts)


def header(name, tool_input):
    if name == "WebSearch":
        lines = [f"query: {tool_input.get('query', '')}"]
        for key in ("allowed_domains", "blocked_domains"):
            if tool_input.get(key):
                lines.append(f"{key}: {', '.join(tool_input[key])}")
    else:
        lines = [f"url: {tool_input.get('url', '')}",
                 f"prompt: {tool_input.get('prompt', '')}"]
    return "\n".join(lines)


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__.split("\n\n")[2])
    transcript, out_dir = sys.argv[1], sys.argv[2]
    if os.path.isdir(out_dir) and os.listdir(out_dir):
        sys.exit(f"{out_dir} is not empty — refusing to mix two extractions")

    uses, results, order = {}, {}, []
    with open(transcript) as fh:
        for line in fh:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            for block in event.get("message", {}).get("content") or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use" and block.get("name") in WEB_TOOLS:
                    uses[block["id"]] = (block["name"], block.get("input", {}))
                    order.append(block["id"])
                elif block.get("type") == "tool_result":
                    results[block["tool_use_id"]] = block

    unpaired = [i for i in order if i not in results]
    if unpaired:
        sys.exit(f"{len(unpaired)} web call(s) without a result — transcript truncated?")

    os.makedirs(out_dir, exist_ok=True)
    for n, use_id in enumerate(order, 1):
        name, tool_input = uses[use_id]
        result = results[use_id]
        head = header(name, tool_input)
        if result.get("is_error"):
            head += "\nerror: true"
        path = os.path.join(out_dir, f"{n:02d}-{WEB_TOOLS[name]}.txt")
        with open(path, "w") as out:
            out.write(head + "\n\n" + result_text(result.get("content")) + "\n")

    print(f"wrote {len(order)} file(s) to {out_dir}")


if __name__ == "__main__":
    main()
