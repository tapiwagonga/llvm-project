#!/usr/bin/env python3
import os
import json
import sys

def main():
    # 1. Check if we are running in a GitHub Actions environment
    event_path = os.environ.get('GITHUB_EVENT_PATH')
    event_name = os.environ.get('GITHUB_EVENT_NAME', 'push')
    
    if not event_path or not os.path.exists(event_path):
        print("Error: GITHUB_EVENT_PATH not set or file does not exist.")
        sys.exit(1)

    print(f"[*] Detected GitHub Event: {event_name}")

    with open(event_path, 'r') as f:
        event_payload = json.load(f)

    # 2. Determine Diff Boundaries and API Endpoints
    base_sha = None
    head_sha = None
    api_endpoint = None

    repo_name = event_payload.get('repository', {}).get('full_name', 'unknown/repo')

    if event_name == 'push':
        base_sha = event_payload.get('before')
        head_sha = event_payload.get('after')
        
        # Handle new branch creation where base_sha is 000000...
        if base_sha == '0000000000000000000000000000000000000000':
            base_sha = f"{head_sha}^1"
            
        api_endpoint = f"/repos/{repo_name}/commits/{head_sha}/comments"
        print(f"[*] Post-Commit Context Detected.")
        print(f"[*] Diff Boundaries: {base_sha} ... {head_sha}")
        print(f"[*] Target API Endpoint: {api_endpoint}")

    elif event_name == 'pull_request':
        pr_number = event_payload.get('number')
        base_sha = event_payload.get('pull_request', {}).get('base', {}).get('sha')
        head_sha = event_payload.get('pull_request', {}).get('head', {}).get('sha')
        api_endpoint = f"/repos/{repo_name}/issues/{pr_number}/comments"
        print(f"[*] Pre-Commit (PR) Context Detected.")
        print(f"[*] Diff Boundaries: {base_sha} ... {head_sha}")
        print(f"[*] Target API Endpoint: {api_endpoint}")

    else:
        print(f"Unsupported event type: {event_name}")
        sys.exit(1)

    if not base_sha or not head_sha:
        print("Error: Could not resolve base and head SHAs from the event payload.")
        sys.exit(1)

    import subprocess
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--coverage-json', required=True)
    args = parser.parse_args()

    # 3. Formulate the Git Command
    import re
    git_diff_cmd = ['git', 'diff', f'{base_sha}...{head_sha}', '--unified=0']
    
    modified_lines = {}
    try:
        diff_output = subprocess.check_output(git_diff_cmd, text=True)
        current_file = None
        for line in diff_output.splitlines():
            if line.startswith('+++ b/'):
                current_file = line[6:]
                modified_lines[current_file] = set()
            elif line.startswith('@@') and current_file:
                m = re.search(r'\+([0-9]+)(?:,([0-9]+))?', line)
                if m:
                    start = int(m.group(1))
                    length = int(m.group(2)) if m.group(2) else 1
                    for i in range(start, start + length):
                        modified_lines[current_file].add(i)
    except subprocess.CalledProcessError as e:
        print(f"Error running git diff: {e}")
        sys.exit(1)

    print(f"[*] Modified files in this commit: {list(modified_lines.keys())}")

    # 4. Parse Coverage JSON
    print(f"[*] Loading coverage data from {args.coverage_json}...")
    try:
        with open(args.coverage_json, 'r') as f:
            cov_data = json.load(f)
    except Exception as e:
        print(f"Error loading coverage JSON: {e}")
        sys.exit(1)

    # 5. Evaluate Functions
    print("\n" + "="*50)
    print("[POST-COMMIT BOT] COVERAGE EVALUATION")
    print("="*50)
    
    issues_dict = {}
    functions = cov_data.get('data', [{}])[0].get('functions', [])

    for func in functions:
        func_filenames = func.get('filenames', [])
        if not func_filenames:
            continue
            
        is_modified = False
        modified_file_match = None
        absolute_file_path = None
        
        for file_path in func_filenames:
            for mf in modified_lines.keys():
                if file_path.endswith(mf):
                    is_modified = True
                    modified_file_match = mf
                    absolute_file_path = file_path
                    break
            if is_modified:
                break
        
        if is_modified:
            regions = func.get('regions', [])
            if not regions:
                continue
                
            func_start = regions[0][0]
            func_end = regions[-1][2]
            
            # Scope Bleed Fix: Bounding box intersection check
            intersect = any(line >= func_start and line <= func_end for line in modified_lines[modified_file_match])
            if not intersect:
                continue

            func_name = func.get('name', 'Unknown')
            branches = func.get('branches', [])
            mcdc_records = func.get('mcdc_records', [])
            
            uncovered_regions = [r for r in regions if r[4] == 0 and r[7] == 0]
            uncovered_branches = [b for b in branches if b[4] == 0 or b[5] == 0]
            
            if uncovered_regions or uncovered_branches or mcdc_records:
                # Template Deduplication Fix
                issue_key = (modified_file_match, func_start, func_end)
                if issue_key not in issues_dict:
                    issues_dict[issue_key] = {
                        'file': absolute_file_path,
                        'func_names': set([func_name]),
                        'uncovered_blocks': len(uncovered_regions),
                        'uncovered_branches': len(uncovered_branches)
                    }
                else:
                    issues_dict[issue_key]['func_names'].add(func_name)

    # API Limit Fix: Output generation and truncation
    output_lines = []
    for (mf, start, end), data in issues_dict.items():
        output_lines.append(f"\n[WARNING] Coverage Issue Detected in Modified File:")
        output_lines.append(f"   File:     {data['file']}")
        output_lines.append(f"   Function(s):")
        for fn in sorted(data['func_names']):
            output_lines.append(f"      - {fn}")
        output_lines.append(f"   Details:  {data['uncovered_blocks']} uncovered blocks, {data['uncovered_branches']} uncovered branches.")

    final_output = "\n".join(output_lines)
    if len(final_output) > 60000:
        final_output = final_output[:60000] + "\n\n[WARNING: Output truncated due to GitHub API limits]"
        
    if not issues_dict:
        print("\n[SUCCESS] All modified functions have 100% coverage. No action needed.")
        sys.exit(0)
    else:
        print(final_output)
        print(f"\n[*] Coverage evaluation complete. Detected {len(issues_dict)} function blocks with regressions.")
        
        # Post the comment directly using GitHub API
        import urllib.request
        github_token = os.environ.get('GITHUB_TOKEN')
        if github_token and api_endpoint:
            print("[*] Posting review comment to GitHub...")
            url = f"https://api.github.com{api_endpoint}"
            headers = {
                "Authorization": f"Bearer {github_token}",
                "Accept": "application/vnd.github.v3+json",
                "Content-Type": "application/json"
            }
            # Wrap final_output in standard markdown formatting
            markdown_body = f"### ⚠️ Code Coverage Regression Detected\n\n```text\n{final_output}\n```"
            data = json.dumps({"body": markdown_body}).encode('utf-8')
            
            try:
                req = urllib.request.Request(url, data=data, headers=headers, method='POST')
                with urllib.request.urlopen(req) as response:
                    print(f"[*] Successfully posted comment. HTTP Status: {response.status}")
            except Exception as e:
                print(f"[ERROR] Failed to post comment to GitHub API: {e}")
        else:
            print("[*] GITHUB_TOKEN not found or api_endpoint missing. Skipping API POST.")

        print(f"\n[FAIL] Failing CI pipeline due to {len(issues_dict)} coverage regressions.")
        sys.exit(1)

if __name__ == '__main__':
    main()
