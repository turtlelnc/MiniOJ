"""Unit CI entry point: private logs, allowlisted counts, no secrets in artifacts."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'tests'))


def counts(result):
    return {'passed':result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
            'failed':len(result.failures)+len(result.errors),'skipped':len(result.skipped),
            'total':result.testsRun,
            'failure_tests':[t.id() for t,_ in result.failures+result.errors]}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--repeat',type=int,default=20);args=parser.parse_args()
    if args.repeat<20:parser.error('at least 20 SIGXCPU repetitions required')
    args.output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='minioj-unit-ci-') as private:
        os.environ['MINIOJ_DATA']=str(Path(private)/'data')
        os.environ['MINIOJ_JUDGE_BACKEND']='local'
        # unittest assertion messages can contain fixture test inputs. Only
        # structured counts and test identifiers leave the private directory.
        with open(Path(private)/'unit.log','w') as log:
            suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'))
            first=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
            repeated=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(
                'test_resource_metrics.ResourceMetricsTests.test_local_self_sent_sigxcpu_is_not_timeout')
                for _ in range(args.repeat))
            second=unittest.TextTestRunner(stream=log,verbosity=2).run(repeated)
        report={'unit':counts(first),'sigxcpu_repetitions':counts(second)}
        ok=first.wasSuccessful() and second.wasSuccessful() and first.testsRun>0 and second.testsRun==args.repeat and len(second.skipped)==0
        report['status']='passed' if ok else 'failed'
        (args.output/'unit-results.json').write_text(json.dumps(report,indent=2))
        text='| Unit Tests | passed | failed | skipped |\n|---|---:|---:|---:|\n'
        for name,row in [('suite',report['unit']),('SIGXCPU repetitions',report['sigxcpu_repetitions'])]:
            text+=f"| {name} | {row['passed']} | {row['failed']} | {row['skipped']} |\n"
        (args.output/'unit-summary.md').write_text(text)
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as summary:summary.write(text)
        print(json.dumps(report,indent=2))
        return 0 if ok else 1


if __name__=='__main__':sys.exit(main())
