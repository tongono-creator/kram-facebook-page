"""Actions entrypoint: audit first; release only immutable signed packages."""
import argparse
import json
import os
import subprocess
from pathlib import Path
import scheduler
import studio

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--mode',choices=['audit','dry-run','publish'],default='audit')
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
    packages=[]
    for relative in queue.get('packages',[]):
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
