#!/usr/bin/env python3
#
# ===- Parse llvm-cov output to GitHub Delta Coverage Markdown -*- python -*--==#
#
# Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
# See https://llvm.org/LICENSE.txt for license information.
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#
# ==------------------------------------------------------------------------==#
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

class DiffHunk:
    def __init__(self, header):
        self.header = header
        self.lines = [] # Tuples of (prefix_type, text, absolute_line_number)

class DiffParser:
    @staticmethod
    def parse(diff_path):
        files = {}
        current_file = None
        current_hunk = None
        current_line_num = 0

        with open(diff_path, 'r') as f:
            for line in f:
                line = line.rstrip('\n')
                
                if line.startswith("+++ b/"):
                    current_file = line[6:]
                    files[current_file] = []
                    current_hunk = None
                    continue
                
                if line.startswith("+++ /dev/null"):
                    current_file = None
                    current_hunk = None
                    continue
                
                if current_file is None:
                    continue

                if line.startswith("@@"):
                    match = re.search(r'\+([0-9]+)', line)
                    if match:
                        current_line_num = int(match.group(1))
                        current_hunk = DiffHunk(line)
                        files[current_file].append(current_hunk)
                    continue

                if current_hunk is None:
                    continue

                if line.startswith('-'):
                    # Aggressively drop removed lines to prevent execution confusion
                    continue
                elif line.startswith('+'):
                    current_hunk.lines.append(('+', line[1:], current_line_num))
                    current_line_num += 1
                elif line.startswith(' '):
                    current_hunk.lines.append((' ', line[1:], current_line_num))
                    current_line_num += 1
                else:
                    pass

        return files

class CoverageMapper:
    @staticmethod
    def parse(json_path, diff_files):
        try:
            with open(json_path, 'r') as f:
                cov_data = json.load(f)
        except Exception as e:
            sys.stderr.write(f"::error::Failed to parse coverage JSON: {e}\n")
            sys.exit(1)

        coverage_matrix = {}
        for fpath in diff_files.keys():
            coverage_matrix[fpath] = {'covered': set(), 'missed': set()}

        if 'data' not in cov_data or not cov_data['data']:
            return coverage_matrix

        for item in cov_data['data'][0].get('files', []):
            fpath = item['filename']
            rel_path = next((rp for rp in diff_files.keys() if fpath.endswith(rp)), None)
            if not rel_path:
                continue
                
            segments = item.get('segments', [])
            for i in range(len(segments) - 1):
                current = segments[i]
                nxt = segments[i+1]
                
                line_start = current[0]
                line_end = nxt[0]
                count = current[2]
                has_count = current[3]
                
                if has_count:
                    for line_num in range(line_start, line_end + 1):
                        if count > 0:
                            coverage_matrix[rel_path]['covered'].add(line_num)
                        else:
                            coverage_matrix[rel_path]['missed'].add(line_num)
                            
        return coverage_matrix

import argparse
from typing import Dict, List, Set, Optional, Tuple

class ReportRenderer:
    @staticmethod
    def _is_executable(text: str) -> bool:
        s = text.strip()
        if not s:
            return False
        if s.startswith('//') or s.startswith('/*') or s.startswith('*') or s.startswith('*/'):
            return False
        if s in ('{', '}', '};'):
            return False
        return True

    @staticmethod
    def render(diff_files: Dict[str, List[DiffHunk]], coverage_matrix: Dict[str, Dict[str, Set[int]]], 
               base_sha: Optional[str], head_sha: Optional[str], 
               base_branch: Optional[str], head_branch: Optional[str]) -> None:
        total_covered = 0
        total_missed = 0
        
        for fpath, data in coverage_matrix.items():
            added_lines = set()
            for hunk in diff_files.get(fpath, []):
                for l_type, text, l_num in hunk.lines:
                    if l_type == '+':
                        if not ReportRenderer._is_executable(text):
                            continue
                        added_lines.add(l_num)
                        
            f_covered = added_lines.intersection(data['covered'])
            f_missed = added_lines.intersection(data['missed'])
            
            total_covered += len(f_covered)
            total_missed += len(f_missed)

        total_lines = total_covered + total_missed

        print("## LLVM-libc Delta Coverage Report")
        
        if total_lines == 0:
            print("\n**Coverage Validated**")
            print("No executable C/C++ lines were added or modified.")
            sys.exit(0)
            
        coverage_percent = (total_covered / total_lines) * 100
        
        print("\n**Patch Coverage Analysis**")
        
        import os
        repo = os.environ.get("GITHUB_REPOSITORY", "llvm/llvm-project")
        
        commit_str = f"[`{head_sha[:7]}`](https://github.com/{repo}/commit/{head_sha}) " if head_sha else ""
        print(f"The code coverage on the recent commit {commit_str}is {coverage_percent:.2f}%. The total number of lines is {total_lines}, with {total_missed} unexecuted lines.")
            
        print("\n<details>")
        print("<summary><b>View Full Diff</b></summary>\n")
        print("<br>\n")
        
        if base_sha and head_sha and base_branch and head_branch:
            print(f"- **Base Branch:** [`{base_branch}` ({base_sha[:7]})](https://github.com/llvm/llvm-project/commit/{base_sha})")
            print(f"- **Head Commit:** [`{head_branch}` ({head_sha[:7]})](https://github.com/{repo}/commit/{head_sha})\n")
            print("---\n<br>\n")
            
        print("### Modified Files Summary")
        print("| File Path | Patch Coverage | Missing Lines |")
        print("| :--- | :---: | :---: |")
        for fpath, hunks in diff_files.items():
            data = coverage_matrix[fpath]
            
            added_lines = set()
            for hunk in hunks:
                for l_type, text, l_num in hunk.lines:
                    if l_type == '+':
                        if not ReportRenderer._is_executable(text):
                            continue
                        added_lines.add(l_num)
            
            f_covered = added_lines.intersection(data['covered'])
            f_missed = added_lines.intersection(data['missed'])
            f_total = len(f_covered) + len(f_missed)
            
            if f_total == 0:
                if len(added_lines) > 0:
                    f_missed = added_lines
                    f_total = len(added_lines)
                else:
                    continue
                
            f_pct = (len(f_covered) / f_total) * 100
            print(f"| `{fpath}` | {f_pct:.2f}% | {len(f_missed)} |")

        print("\n### Delta Coverage (Source Map)")
        
        for fpath, hunks in diff_files.items():
            data = coverage_matrix[fpath]
            
            added_lines = set()
            for hunk in hunks:
                for l_type, text, l_num in hunk.lines:
                    if l_type == '+':
                        if not ReportRenderer._is_executable(text):
                            continue
                        added_lines.add(l_num)
            
            f_missed = added_lines.intersection(data['missed'])
            f_covered = added_lines.intersection(data['covered'])
            
            if len(f_missed) == 0 and len(f_covered) == 0:
                if len(added_lines) > 0:
                    f_missed = added_lines
                else:
                    continue
            
            print(f"\n**`{fpath}`**")
            print("```diff")
            
            for hunk in hunks:
                print(hunk.header)
                for l_type, text, l_num in hunk.lines:
                    if l_type == '+':
                        if l_num in f_missed:
                            print(f"- {text}")
                            sys.stderr.write(f"::warning file={fpath},line={l_num}::Coverage Missed: This delta line was not executed.\n")
                        elif l_num in f_covered:
                            print(f"+ {text}")
                        else:
                            print(f"  {text}")
                    elif l_type == ' ':
                        print(f"  {text}")
            print("```")

@dataclass
class CoverageHistoryEntry:
    """Represents a single historical coverage iteration on a Pull Request."""
    sha: str
    line_pct: str
    mcdc_pct: str
    timestamp: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CoverageHistoryEntry":
        return cls(
            sha=str(data.get("sha", "unknown"))[:7],
            line_pct=str(data.get("line_pct", "N/A")),
            mcdc_pct=str(data.get("mcdc_pct", "N/A")),
            timestamp=str(data.get("timestamp", "")),
        )


class GitHubPRClient:
    """Minimal, dependency-free REST client for GitHub Pull Request comments."""
    def __init__(self, repo_full_name: str, pr_number: int, token: str):
        self.repo_full_name = repo_full_name
        self.pr_number = pr_number
        self.token = token
        self.base_url = f"https://api.github.com/repos/{repo_full_name}/issues/{pr_number}/comments"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "LLVM-libc-Coverage-Bot",
        }

    def _request(
        self,
        url: str,
        method: str = "GET",
        payload: Optional[Dict[str, Any]] = None,
    ) -> Optional[Any]:
        data = json.dumps(payload).encode("utf-8") if payload else None
        req = urllib.request.Request(
            url, data=data, headers=self.headers, method=method
        )
        try:
            with urllib.request.urlopen(req) as resp:
                if resp.status == 204:
                    return None
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            print(
                f"Notice: GitHub REST API {method} {url} failed with HTTP {err.code}. "
                "Step Summary remains untouched.",
                file=sys.stderr,
            )
            return None

    def find_bot_comment(self, header_prefix: str) -> Optional[Dict[str, Any]]:
        comments = self._request(self.base_url, method="GET")
        if not isinstance(comments, list):
            return None
        for comment in comments:
            is_bot = comment.get("user", {}).get("type") == "Bot"
            body = comment.get("body", "")
            if is_bot and header_prefix in body:
                return comment
        return None

    def upsert_comment(
        self, body: str, existing_comment_url: Optional[str] = None
    ) -> bool:
        payload = {"body": body}
        if existing_comment_url:
            return (
                self._request(
                    existing_comment_url, method="PATCH", payload=payload
                )
                is not None
            )
        return self._request(self.base_url, method="POST", payload=payload) is not None


class CoverageHistoryModel:
    """Manages serialization and idempotent updates of historical coverage state."""
    STATE_REGEX = re.compile(r"<!--\s*cov_history:\s*(\[.*?\])\s*-->", re.DOTALL)

    @classmethod
    def extract(cls, comment_body: str) -> List[CoverageHistoryEntry]:
        match = cls.STATE_REGEX.search(comment_body)
        if not match:
            return []
        try:
            raw_items = json.loads(match.group(1))
            if isinstance(raw_items, list):
                return [CoverageHistoryEntry.from_dict(item) for item in raw_items]
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
        return []

    @classmethod
    def serialize(cls, history: List[CoverageHistoryEntry]) -> str:
        data = [asdict(entry) for entry in history]
        return f"\n<!-- cov_history: {json.dumps(data, separators=(',', ':'))} -->"

    @classmethod
    def upsert_entry(
        cls,
        history: List[CoverageHistoryEntry],
        new_entry: CoverageHistoryEntry,
    ) -> List[CoverageHistoryEntry]:
        updated = [entry for entry in history if entry.sha != new_entry.sha]
        updated.append(new_entry)
        return updated


class CommentRenderer:
    """Formats Markdown tables and sticky comment headers."""
    HEADER = "### LLVM-libc Patch Coverage Report"

    @staticmethod
    def render_history_table(history: List[CoverageHistoryEntry]) -> str:
        if not history:
            return ""
        count = len(history)
        label = "Iteration" if count == 1 else "Iterations"
        lines = [
            "\n<details>",
            f"<summary><b>View Coverage Evolution ({count} {label})</b></summary>",
            "",
            "| Commit | Patch Line Coverage | Patch MC/DC | Timestamp |",
            "| :---: | :---: | :---: | :---: |",
        ]
        for entry in reversed(history):
            lines.append(
                f"| `{entry.sha}` | {entry.line_pct} | {entry.mcdc_pct} | {entry.timestamp} |"
            )
        lines.append("</details>")
        return "\n".join(lines)

    @classmethod
    def assemble_body(
        cls,
        report_markdown: str,
        history: List[CoverageHistoryEntry],
    ) -> str:
        history_table = cls.render_history_table(history)
        state_comment = CoverageHistoryModel.serialize(history)
        return f"{cls.HEADER}\n\n{report_markdown}\n{history_table}{state_comment}"


class CommentManager:
    """Orchestrates sticky PR comment updates with historical coverage logs."""
    @staticmethod
    def post_or_update_comment(report_path: str) -> None:
        token = os.environ.get("GITHUB_TOKEN")
        event_path = os.environ.get("GITHUB_EVENT_PATH")
        if not token or not event_path or not os.path.exists(event_path):
            print("Notice: Missing GITHUB_TOKEN or PR context. Skipping PR comment update.")
            return

        with open(event_path, "r", encoding="utf-8") as f:
            event_data = json.load(f)

        pr_number = event_data.get("pull_request", {}).get("number")
        repo_name = event_data.get("repository", {}).get("full_name")
        head_sha = event_data.get("pull_request", {}).get("head", {}).get("sha", "")[:7]

        if not pr_number or not repo_name:
            print("Notice: Workflow is not executing in a Pull Request context. Skipping comment update.")
            return

        with open(report_path, "r", encoding="utf-8") as f:
            report_text = f.read().strip()
        if not report_text:
            return

        cov_match = re.search(r"is (\d+(?:\.\d+)?)%", report_text)
        cov_pct = f"{cov_match.group(1)}%" if cov_match else "N/A"
        today = datetime.now().strftime("%Y-%m-%d")

        client = GitHubPRClient(repo_name, int(pr_number), token)
        existing_comment = client.find_bot_comment(CommentRenderer.HEADER)

        history = []
        existing_url = None
        if existing_comment:
            existing_url = existing_comment.get("url")
            history = CoverageHistoryModel.extract(existing_comment.get("body", ""))

        new_entry = CoverageHistoryEntry(
            sha=head_sha or "unknown",
            line_pct=cov_pct,
            mcdc_pct="N/A",
            timestamp=today,
        )
        history = CoverageHistoryModel.upsert_entry(history, new_entry)
        final_body = CommentRenderer.assemble_body(report_text, history)

        success = client.upsert_comment(final_body, existing_url)
        if success:
            print(f"Successfully {'updated' if existing_url else 'created'} sticky PR coverage comment.")


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "--update-comment":
        CommentManager.post_or_update_comment(sys.argv[2])
        sys.exit(0)

    parser = argparse.ArgumentParser(description="LLVM-libc Delta Coverage Analyzer")
    parser.add_argument("diff_file")
    parser.add_argument("json_file")
    parser.add_argument("base_sha", nargs='?')
    parser.add_argument("head_sha", nargs='?')
    parser.add_argument("base_branch", nargs='?')
    parser.add_argument("head_branch", nargs='?')
    
    args = parser.parse_args()

    diff_files = DiffParser.parse(args.diff_file)
    coverage_matrix = CoverageMapper.parse(args.json_file, diff_files)
    ReportRenderer.render(diff_files, coverage_matrix, args.base_sha, args.head_sha, args.base_branch, args.head_branch)

if __name__ == '__main__':
    main()
