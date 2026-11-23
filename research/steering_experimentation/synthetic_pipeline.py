"""Synthetic experiment CLI. Planning/import/preparation are offline by default."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from secondthought.lab.synthetic import make_plan,read_jsonl,load_plan,generate,prepare


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    plan=commands.add_parser('plan');plan.add_argument('--definition',type=Path,required=True)
    plan.add_argument('--scenarios',type=Path,required=True);plan.add_argument('--run',type=Path,required=True)
    plan.add_argument('--seed',type=int,default=42);plan.add_argument('--variants',type=int,default=1)
    gen=commands.add_parser('generate');gen.add_argument('--run',type=Path,required=True)
    gen.add_argument('--provider',choices=['responses','chat'],required=True);gen.add_argument('--model',required=True)
    gen.add_argument('--base-url');gen.add_argument('--max-requests',type=int,required=True)
    gen.add_argument('--max-output-tokens',type=int,default=512)
    prep=commands.add_parser('prepare');prep.add_argument('--run',type=Path,required=True)
    prep.add_argument('--responses',type=Path);prep.add_argument('--output',type=Path)
    prep.add_argument('--approvals',type=Path,help='Optional JSON list of human-accepted request IDs')
    extract=commands.add_parser('extract');extract.add_argument('--run',type=Path,required=True)
    extract.add_argument('--dataset',type=Path);extract.add_argument('--device',choices=['cpu','mps','cuda'],default='mps')
    extract.add_argument('--batch-size',type=int,default=8);extract.add_argument('--max-length',type=int,default=256)
    publish=commands.add_parser('publish');publish.add_argument('--run',type=Path,required=True)
    publish.add_argument('--artifact',type=Path);publish.add_argument('--destination',type=Path)
    args=parser.parse_args()
    if args.command=='plan':
        result=make_plan(json.loads(args.definition.read_text()),read_jsonl(args.scenarios),args.run,args.seed,args.variants)
    elif args.command=='generate':
        result=generate(args.run,args.provider,args.model,args.max_requests,args.max_output_tokens,args.base_url)
    elif args.command=='prepare':
        result=prepare(args.run,args.responses,args.output,args.approvals)
        print(json.dumps(result,indent=2));return 0 if result['ready_for_extraction'] else 2
    else:
        manifest,_=load_plan(args.run);feature=manifest['configuration']['feature']
        name=f'qwen2_5_0_5b_{feature["id"]}_all_layers_{feature["version"]}.pt'
        if args.command=='extract':
            dataset=args.dataset or args.run/'dataset/pairs.jsonl'
            subprocess.run([sys.executable,'-m','research.steering_experimentation.extract_lab_vectors',
                '--prepared-pairs',str(dataset),'--feature-id',feature['id'],'--artifact-version',feature['version'],
                '--output',str(args.run/'vectors'),'--device',args.device,'--batch-size',str(args.batch_size),
                '--max-length',str(args.max_length)],check=True)
            return 0
        from secondthought.lab.experiments import publish_experiment
        result=publish_experiment(args.run,args.artifact or args.run/'vectors'/name,args.destination or args.run/'serving')
    print(json.dumps(result,indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
