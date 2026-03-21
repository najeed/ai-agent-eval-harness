import json
import os

def audit_coverage():
    if not os.path.exists('coverage_final.json'):
        print("coverage_final.json not found")
        return

    with open('coverage_final.json', 'r') as f:
        data = json.load(f)

    targets = [
        'explainer.py',
        'plugins.py',
        'triage.py',
        'mutator.py',
        'doctor.py',
        'demo_traces.py',
        'socket.py'
    ]

    report = {}
    for filepath, info in data['files'].items():
        if any(t in filepath for t in targets):
            report[filepath] = {
                'percent': info['summary']['percent_covered'],
                'missing': info['missing_lines']
            }

    with open('tmp_coverage_audit.json', 'w') as f:
        json.dump(report, f, indent=2)

if __name__ == "__main__":
    audit_coverage()
