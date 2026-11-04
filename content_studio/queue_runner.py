"""Actions entrypoint: audit first; release only immutable signed packages."""
import argparse
import json
import os
import subprocess
from pathlib import Path
import scheduler
import studio
import re


def select_packages(queue, package_id=None):
    paths = queue.get('packages', [])
    if not package_id:
        return paths
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', package_id):
        raise studio.GateError('Invalid exact package ID')
    selected = [p for p in paths if p == 'packages/' + package_id]
    if len(selected) != 1:
        raise studio.GateError('Exact package must appear once in reviewed queue')
    return selected

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--mode',choices=['audit','dry-run','publish'],default='audit')
    parser.add_argument('--package-id', help='Optional exact reviewed queue package; preserve all other packages')
    parser.add_argument('--batch-id', help='Optional exact reviewed batch under content_studio/batches')
    args=parser.parse_args()
    root=Path(__file__).resolve().parent
    repo=root.parent
    queue=studio.read_json(root/'queue.json')
    key=queue['channel_key']
    channels=studio.read_json(root/'channels.json')
    if key not in channels:
        raise studio.GateError('Unknown queue channel')
    if args.mode=='audit':
        return scheduler.main(['--repo-root',str(repo),'--channel',key,'--channels',str(root/'channels.json'),'--audit'])
    if args.package_id and args.batch_id:
        raise studio.GateError('Choose a package or a batch, not both')
    paths = select_packages(queue, args.package_id)
    if args.batch_id:
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', args.batch_id):
            raise studio.GateError('Invalid exact batch ID')
        batch = studio.read_json(root/'batches'/(args.batch_id+'.json'))
        paths = batch.get('packages', [])
        if not paths or len(paths) != len(set(paths)) or any(x not in queue['packages'] for x in paths):
            raise studio.GateError('Batch must contain unique exact queued packages')
    packages=[]
    for relative in paths:
        package=(root/relative).resolve()
        if not package.is_relative_to((root/'packages').resolve()):
            raise studio.GateError('Queue package outside approved package directory')
        packages.append(str(package))
    if not packages:
        print(json.dumps({'channel':key,'status':'empty_approved_queue','remote_writes':0}))
        return 0
    arguments=['--repo-root',str(repo),'--channel',key,'--channels',str(root/'channels.json'),'--packages',*packages]
    arguments+=['--publish','--git-state'] if args.mode=='publish' else ['--dry-run','--live-preview']
    return scheduler.main(arguments)

if __name__=='__main__':
    try:
        raise SystemExit(main())
    except (scheduler.ScheduleError,studio.GateError) as exc:
        raise SystemExit(f'Content Studio held this release: {exc}') from None
