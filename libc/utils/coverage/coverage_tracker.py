#!/usr/bin/env python3
#
# ====- Track continuous code coverage history -----------------*- python -*--==#
#
# Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
# See https://llvm.org/LICENSE.txt for license information.
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#
# ==-------------------------------------------------------------------------==#

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

MAX_HISTORY_DAYS = 365


def read_history(path: str) -> List[Dict[str, Any]]:
    """Reads existing history from a JSON file, or returns an empty list."""
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception:
            return []
    return []


def write_history(path: str, history: List[Dict[str, Any]], max_days: int = MAX_HISTORY_DAYS) -> None:
    """Saves history to JSON, keeping up to max_days daily entries."""
    capped = history[-max_days:] if len(history) > max_days else history
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(capped, f, indent=2)


def extract_coverage_metrics(cov_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extracts global and directory metrics from llvm-cov export JSON."""
    if "data" not in cov_data or not cov_data["data"]:
        return None

    directories: Dict[str, Dict[str, Any]] = {}
    total_lines_cov, total_lines_tot = 0, 0
    total_func_cov, total_func_tot = 0, 0
    total_mcdc_cov, total_mcdc_tot = 0, 0
    total_decisions_tot, total_decisions_full = 0, 0

    for item in cov_data["data"][0].get("files", []):
        fpath = item.get("filename", "")
        if "src/" not in fpath or "/test/" in fpath or "/utils/" in fpath:
            continue

        idx = fpath.find("src/")
        if idx == -1:
            continue
        rel_path = fpath[idx:]

        summary = item.get("summary", {})
        lines_summary = summary.get("lines", {})
        func_summary = summary.get("functions", {})
        mcdc_summary = summary.get("mcdc", {})

        line_tot = lines_summary.get("count", 0)
        line_cov = lines_summary.get("covered", 0)
        func_tot = func_summary.get("count", 0)
        func_cov = func_summary.get("covered", 0)
        mcdc_tot = mcdc_summary.get("count", 0)
        mcdc_cov = mcdc_summary.get("covered", 0)

        if line_tot == 0:
            continue

        mcdc_records = item.get("mcdc_records", [])
        file_decisions_full = sum(
            1 for rec in mcdc_records if len(rec) >= 10 and isinstance(rec[9], list) and all(rec[9])
        )

        total_lines_cov += line_cov
        total_lines_tot += line_tot
        total_func_cov += func_cov
        total_func_tot += func_tot
        total_mcdc_cov += mcdc_cov
        total_mcdc_tot += mcdc_tot
        total_decisions_tot += len(mcdc_records)
        total_decisions_full += file_decisions_full

        parts = rel_path.split("/")
        directory = parts[1] if len(parts) >= 2 else "core"

        if directory not in directories:
            directories[directory] = {"lines_cov": 0, "lines_tot": 0, "mcdc_cov": 0, "mcdc_tot": 0}

        directories[directory]["lines_cov"] += line_cov
        directories[directory]["lines_tot"] += line_tot
        directories[directory]["mcdc_cov"] += mcdc_cov
        directories[directory]["mcdc_tot"] += mcdc_tot

    if total_lines_tot == 0:
        return None

    formatted_directories = {}
    for name, stats in directories.items():
        s_line_pct = round(stats["lines_cov"] / stats["lines_tot"] * 100.0, 2) if stats["lines_tot"] > 0 else 0.0
        s_mcdc_pct = round(stats["mcdc_cov"] / stats["mcdc_tot"] * 100.0, 2) if stats["mcdc_tot"] > 0 else 0.0
        formatted_directories[name] = {
            "lines_cov": stats["lines_cov"],
            "lines_tot": stats["lines_tot"],
            "line_pct": s_line_pct,
            "mcdc_cov": stats["mcdc_cov"],
            "mcdc_tot": stats["mcdc_tot"],
            "mcdc_pct": s_mcdc_pct,
        }

    return {
        "global": {
            "lines_cov": total_lines_cov,
            "lines_tot": total_lines_tot,
            "line_pct": round(total_lines_cov / total_lines_tot * 100.0, 2),
            "func_cov": total_func_cov,
            "func_tot": total_func_tot,
            "func_pct": round(total_func_cov / total_func_tot * 100.0, 2) if total_func_tot > 0 else 0.0,
            "mcdc_cov": total_mcdc_cov,
            "mcdc_tot": total_mcdc_tot,
            "mcdc_pct": round(total_mcdc_cov / total_mcdc_tot * 100.0, 2) if total_mcdc_tot > 0 else 0.0,
            "decisions_tot": total_decisions_tot,
            "decisions_full": total_decisions_full,
            "decisions_pct": (
                round(total_decisions_full / total_decisions_tot * 100.0, 2) if total_decisions_tot > 0 else 0.0
            ),
        },
        "directories": formatted_directories,
    }


def add_daily_run(history: List[Dict[str, Any]], current_metrics: Dict[str, Any], commit_sha: str) -> List[Dict[str, Any]]:
    """Appends today's run to history, or updates today's existing entry in place."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    new_entry = {
        "date": today,
        "timestamp": timestamp,
        "commit": commit_sha[:8] if commit_sha else "unknown",
        "global": current_metrics["global"],
        "directories": current_metrics["directories"],
    }

    for i, entry in enumerate(history):
        if entry.get("date") == today:
            history[i] = new_entry
            return history

    history.append(new_entry)
    return history


def get_change(history: List[Dict[str, Any]], days_ago: int = 1) -> Dict[str, float]:
    """Calculates coverage change between latest run and N days ago."""
    if len(history) < 2:
        return {"line_change": 0.0, "mcdc_change": 0.0}

    today_stats = history[-1]["global"]
    idx = max(0, len(history) - 1 - days_ago)
    past_stats = history[idx]["global"]

    return {
        "line_change": round(today_stats.get("line_pct", 0.0) - past_stats.get("line_pct", 0.0), 2),
        "mcdc_change": round(today_stats.get("mcdc_pct", 0.0) - past_stats.get("mcdc_pct", 0.0), 2),
    }


def get_directory_changes(history: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    """Calculates per-directory daily changes."""
    if len(history) < 2:
        return {}

    today_dirs = history[-1].get("directories", {})
    yesterday_dirs = history[-2].get("directories", {})

    changes = {}
    for name, today_data in today_dirs.items():
        yesterday_data = yesterday_dirs.get(name, {})
        line_delta = round(today_data.get("line_pct", 0.0) - yesterday_data.get("line_pct", 0.0), 2)
        mcdc_delta = round(today_data.get("mcdc_pct", 0.0) - yesterday_data.get("mcdc_pct", 0.0), 2)
        changes[name] = {"line_change": line_delta, "mcdc_change": mcdc_delta}

    return changes


def format_delta(delta: float) -> str:
    """Formats numeric delta into a clean string."""
    if delta > 0:
        return f"+{delta:.2f}%"
    elif delta < 0:
        return f"{delta:.2f}%"
    return "+0.00%"


def generate_issue_markdown(history: List[Dict[str, Any]], commit_sha: str) -> str:
    """Generates clean markdown for the pinned tracking issue."""
    if not history:
        return "No coverage history available."

    latest = history[-1]
    g = latest.get("global", {})
    directories = latest.get("directories", {})
    daily_delta = get_change(history, days_ago=1)
    weekly_delta = get_change(history, days_ago=7)
    directory_changes = get_directory_changes(history)

    commit_display = latest.get("commit", commit_sha[:8] if commit_sha else "main")
    timestamp_display = latest.get("timestamp", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))

    md = [
        "# LLVM-libc Continuous Code Coverage Tracking\n\n",
        f"Last Updated: {timestamp_display} | Commit: `{commit_display}`\n\n",
        "## Global Metrics Summary\n\n",
        "| Metric | Covered | Total | Coverage % | 24h Change | 7d Change |\n",
        "| :--- | :--- | :--- | :--- | :--- | :--- |\n",
        f"| Line Coverage | {g.get('lines_cov', 0):,} | {g.get('lines_tot', 0):,} | **{g.get('line_pct', 0.0):.2f}%** | {format_delta(daily_delta['line_change'])} | {format_delta(weekly_delta['line_change'])} |\n",
        f"| Function Coverage | {g.get('func_cov', 0):,} | {g.get('func_tot', 0):,} | **{g.get('func_pct', 0.0):.2f}%** | - | - |\n",
        f"| MC/DC Conditions | {g.get('mcdc_cov', 0):,} | {g.get('mcdc_tot', 0):,} | **{g.get('mcdc_pct', 0.0):.2f}%** | {format_delta(daily_delta['mcdc_change'])} | {format_delta(weekly_delta['mcdc_change'])} |\n",
        f"| MC/DC Decisions (Full) | {g.get('decisions_full', 0):,} | {g.get('decisions_tot', 0):,} | **{g.get('decisions_pct', 0.0):.2f}%** | - | - |\n\n",
        "## Directory Breakdown\n\n",
        "| Directory | Lines (Cov / Tot) | Line % | 24h Change | MC/DC (Cov / Tot) | MC/DC % | 24h Change |\n",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n",
    ]

    for name in sorted(directories.keys()):
        data = directories[name]
        d_changes = directory_changes.get(name, {"line_change": 0.0, "mcdc_change": 0.0})
        mcdc_tot = data.get("mcdc_tot", 0)
        mcdc_str = f"{data.get('mcdc_cov', 0):,} / {mcdc_tot:,}" if mcdc_tot > 0 else "-"
        mcdc_pct_str = f"**{data.get('mcdc_pct', 0.0):.2f}%**" if mcdc_tot > 0 else "-"
        mcdc_delta_str = format_delta(d_changes["mcdc_change"]) if mcdc_tot > 0 else "-"

        md.append(
            f"| `{name}/` | {data.get('lines_cov', 0):,} / {data.get('lines_tot', 0):,} | "
            f"**{data.get('line_pct', 0.0):.2f}%** | {format_delta(d_changes['line_change'])} | "
            f"{mcdc_str} | {mcdc_pct_str} | {mcdc_delta_str} |\n"
        )

    md.extend([
        "\n## Links\n\n",
        "- [Standard Coverage Report (HTML)](coverage/)\n",
        "- [MC/DC Coverage Report (HTML)](mcdc/)\n",
        "- [Historical Dataset (JSON)](data/history.json)\n",
    ])

    return "".join(md)


def generate_dashboard_html(history: List[Dict[str, Any]]) -> str:
    """Generates minimal static HTML table."""
    latest = history[-1] if history else {}
    g = latest.get("global", {})
    directories = latest.get("directories", {})

    date_str = latest.get("date", "N/A")
    commit_str = latest.get("commit", "N/A")
    timestamp_str = latest.get("timestamp", "N/A")

    dir_rows = []
    for name in sorted(directories.keys()):
        stats = directories[name]
        mcdc_str = f"{stats.get('mcdc_pct', 0.0):.2f}%" if stats.get("mcdc_tot", 0) > 0 else "-"
        dir_rows.append(
            f"      <tr><td><code>{name}/</code></td><td>{stats.get('lines_cov', 0):,}</td>"
            f"<td>{stats.get('lines_tot', 0):,}</td><td><strong>{stats.get('line_pct', 0.0):.2f}%</strong></td>"
            f"<td>{mcdc_str}</td></tr>"
        )

    history_rows = []
    for entry in reversed(history[-14:]):
        eg = entry.get("global", {})
        history_rows.append(
            f"      <tr><td>{entry.get('date', 'N/A')}</td><td><code>{entry.get('commit', 'N/A')}</code></td>"
            f"<td>{eg.get('line_pct', 0.0):.2f}%</td><td>{eg.get('mcdc_pct', 0.0):.2f}%</td></tr>"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>LLVM-libc Coverage Dashboard</title>
  <style>
    body {{ font-family: sans-serif; margin: 20px; line-height: 1.4; color: #333; }}
    table {{ border-collapse: collapse; width: 100%; margin: 10px 0 20px 0; }}
    th, td {{ border: 1px solid #ccc; padding: 5px 10px; text-align: left; font-size: 13px; }}
    th {{ background-color: #f2f2f2; }}
    code {{ font-family: monospace; }}
    a {{ color: #0366d6; text-decoration: none; margin-right: 12px; }}
    a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <h1>LLVM-libc Code Coverage Dashboard</h1>
  <p>Snapshot: {date_str} ({timestamp_str}) | Commit: <code>{commit_str}</code> | Total Runs: {len(history)}</p>

  <p>
    <a href="coverage/">[Standard Coverage Report]</a>
    <a href="mcdc/">[MC/DC Coverage Report]</a>
    <a href="data/history.json">[History Dataset (JSON)]</a>
  </p>

  <h2>Global Summary</h2>
  <table>
    <thead><tr><th>Metric</th><th>Covered</th><th>Total</th><th>Coverage %</th></tr></thead>
    <tbody>
      <tr><td>Line Coverage</td><td>{g.get('lines_cov', 0):,}</td><td>{g.get('lines_tot', 0):,}</td><td><strong>{g.get('line_pct', 0.0):.2f}%</strong></td></tr>
      <tr><td>Function Coverage</td><td>{g.get('func_cov', 0):,}</td><td>{g.get('func_tot', 0):,}</td><td><strong>{g.get('func_pct', 0.0):.2f}%</strong></td></tr>
      <tr><td>MC/DC Conditions</td><td>{g.get('mcdc_cov', 0):,}</td><td>{g.get('mcdc_tot', 0):,}</td><td><strong>{g.get('mcdc_pct', 0.0):.2f}%</strong></td></tr>
      <tr><td>MC/DC Decisions (Full)</td><td>{g.get('decisions_full', 0):,}</td><td>{g.get('decisions_tot', 0):,}</td><td><strong>{g.get('decisions_pct', 0.0):.2f}%</strong></td></tr>
    </tbody>
  </table>

  <h2>Directory Breakdown</h2>
  <table>
    <thead><tr><th>Directory</th><th>Covered Lines</th><th>Total Lines</th><th>Line %</th><th>MC/DC %</th></tr></thead>
    <tbody>
{chr(10).join(dir_rows)}
    </tbody>
  </table>

  <h2>Recent Runs</h2>
  <table>
    <thead><tr><th>Date</th><th>Commit</th><th>Line %</th><th>MC/DC %</th></tr></thead>
    <tbody>
{chr(10).join(history_rows)}
    </tbody>
  </table>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Track continuous LLVM-libc code coverage history.")
    parser.add_argument("--export-json", help="Path to llvm-cov export JSON file.")
    parser.add_argument("--history-file", default="data/history.json", help="Path to history.json file.")
    parser.add_argument("--out-dir", default="gh-pages-root", help="Output directory for web dashboard and data.")
    parser.add_argument("--issue-file", help="Path to write pinned tracking issue markdown body.")
    parser.add_argument("--commit-sha", default="main", help="Current commit SHA.")
    parser.add_argument("--query-weekly", action="store_true", help="Print weekly summary and exit.")
    parser.add_argument("--max-days", type=int, default=MAX_HISTORY_DAYS, help="Maximum history retention in days.")

    args = parser.parse_args()

    history = read_history(args.history_file)

    if args.query_weekly:
        print("=== LLVM-libc Weekly Coverage View ===")
        weekly_snapshots = [history[i] for i in range(len(history) - 1, -1, -7)][::-1]
        for s in weekly_snapshots:
            g = s.get("global", {})
            print(f"Date: {s.get('date')} | Commit: {s.get('commit')} | Line: {g.get('line_pct', 0.0):.2f}% | MC/DC: {g.get('mcdc_pct', 0.0):.2f}%")
        return 0

    if args.export_json:
        if not os.path.exists(args.export_json):
            print(f"[coverage_tracker] Error: Export file not found: {args.export_json}", file=sys.stderr)
            return 1

        with open(args.export_json, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        current_metrics = extract_coverage_metrics(raw_data)
        if not current_metrics:
            print("[coverage_tracker] Error: Failed to extract coverage metrics from JSON.", file=sys.stderr)
            return 1

        history = add_daily_run(history, current_metrics, args.commit_sha)

        write_history(args.history_file, history, max_days=args.max_days)

        out_data_dir = os.path.join(args.out_dir, "data")
        os.makedirs(out_data_dir, exist_ok=True)
        write_history(os.path.join(out_data_dir, "history.json"), history, max_days=args.max_days)

        html_content = generate_dashboard_html(history)
        os.makedirs(args.out_dir, exist_ok=True)
        with open(os.path.join(args.out_dir, "index.html"), "w", encoding="utf-8") as f:
            f.write(html_content)

        if args.issue_file:
            md_content = generate_issue_markdown(history, args.commit_sha)
            os.makedirs(os.path.dirname(os.path.abspath(args.issue_file)), exist_ok=True)
            with open(args.issue_file, "w", encoding="utf-8") as f:
                f.write(md_content)

        print(f"[coverage_tracker] Successfully updated history ({len(history)} entries) and generated outputs in {args.out_dir}.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
