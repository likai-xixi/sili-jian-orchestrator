from __future__ import annotations

import argparse
from pathlib import Path

from common import read_json, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description='Update ai/state/agent-sessions.json for a target project.')
    parser.add_argument('project_root', help='Target project root')
    parser.add_argument('agent_id', help='Peer agent id such as neige or bingbu')
    parser.add_argument('--session-key', help='Session key to store')
    parser.add_argument('--status', default='active', help='idle/active/blocked/etc')
    parser.add_argument('--last-task-id', help='Last dispatched task id')
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    path = project_root / 'ai' / 'state' / 'agent-sessions.json'
    payload = read_json(path)
    record = payload.get(args.agent_id, {'agent_id': args.agent_id})
    if args.session_key is not None:
        record['session_key'] = args.session_key
    record['status'] = args.status
    if args.last_task_id is not None:
        record['last_task_id'] = args.last_task_id
    payload[args.agent_id] = record
    write_json(path, payload)


if __name__ == '__main__':
    main()
