from __future__ import annotations
import ast
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

_MNF_RE = re.compile(r"ModuleNotFoundError: No module named ['\"]([^'\"]+)['\"]")


@dataclass
class SnippetCluster:
    key: str
    count: int
    representative: str


@dataclass
class ReviewResult:
    module_not_found: Counter = field(default_factory=Counter)
    imports_used: Counter = field(default_factory=Counter)
    snippet_clusters: list[SnippetCluster] = field(default_factory=list)


def _normalize_snippet(code: str) -> str:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code.strip()

    class Normalizer(ast.NodeTransformer):
        def visit_Name(self, node):
            return ast.copy_location(ast.Name(id="_N", ctx=node.ctx), node)
        def visit_Constant(self, node):
            return ast.copy_location(ast.Constant(value="_C"), node)
        def visit_arg(self, node):
            node.arg = "_A"
            return node
    Normalizer().visit(tree)
    return ast.dump(tree, annotate_fields=False)


def analyze(workspaces_root: Path) -> ReviewResult:
    result = ReviewResult()
    snippets_by_key: dict[str, list[str]] = defaultdict(list)
    counts_by_key: Counter = Counter()

    for jsonl in workspaces_root.rglob("agent_log/*.jsonl"):
        for line in jsonl.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("type") == "tool_result" and rec.get("is_error"):
                m = _MNF_RE.search(rec.get("error") or "")
                if m:
                    result.module_not_found[m.group(1)] += 1
            if rec.get("type") == "tool_call" and rec.get("tool") == "run_python":
                for mod in rec.get("imports_used", []):
                    result.imports_used[mod] += 1
                code = rec.get("code", "")
                key = _normalize_snippet(code)
                counts_by_key[key] += 1
                snippets_by_key[key].append(code)

    for key, count in counts_by_key.most_common():
        rep = snippets_by_key[key][0]
        result.snippet_clusters.append(SnippetCluster(key=key, count=count, representative=rep))
    return result


def format_report(result: ReviewResult) -> str:
    lines: list[str] = []
    lines.append("=== Whitelist candidates ===")
    if result.module_not_found:
        for mod, n in result.module_not_found.most_common():
            mark = "  >> add" if n >= 3 else ""
            lines.append(f"  ModuleNotFoundError({mod}): {n}{mark}")
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append("Successful import frequencies:")
    if result.imports_used:
        for mod, n in result.imports_used.most_common():
            lines.append(f"  {mod}: {n}")
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append("=== Tool-promotion candidates ===")
    promoted = [c for c in result.snippet_clusters if c.count >= 3]
    if promoted:
        for c in promoted:
            lines.append(f"  [{c.count}x] {c.representative.strip()[:200]}")
    else:
        lines.append("  (no clusters with N>=3)")
    return "\n".join(lines)
