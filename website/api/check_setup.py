"""Offline readiness check: python -m website.api.check_setup.

Checks the promoted vector files without loading or downloading model weights.
"""
import argparse
import json
import sys

import torch

from secondthought.lab.catalog import Catalog


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json',action='store_true',help='Print a structured report')
    args=parser.parse_args()
    try:
        catalog=Catalog.load()
        vectors=catalog.public()['vectors']
        available=sum(v['available'] for v in vectors)
        device=('mps' if torch.backends.mps.is_available() else
                'cuda' if torch.cuda.is_available() else 'cpu')
        report=dict(ok=not catalog.issues,python=sys.version.split()[0],pytorch=str(torch.__version__),
            device=device,catalog=catalog.spec.id,catalog_version=catalog.version,
            available_vectors=available,total_vectors=len(vectors),
            artifact_count=len(catalog.spec.artifacts),issues=catalog.issues,
            models=[dict(repository=m.repository,revision=m.revision) for m in catalog.spec.models],
            note='Model weights are not loaded or downloaded by this check. First server launch needs internet unless the pinned model is already cached.')
    except (OSError,ValueError) as exc:
        report=dict(ok=False,error=str(exc),
            next_step='Run from the repository checkout and restore the catalog and its matching artifacts from this branch.')
    if args.json:
        print(json.dumps(report,indent=2))
    elif not report['ok']:
        print(json.dumps(report,indent=2),file=sys.stderr)
    else:
        print(f"Python {report['python']} | PyTorch {report['pytorch']} | device: {report['device']}")
        print(f"Catalog: {report['catalog']}")
        print(f"Verified {report['artifact_count']} artifacts; {report['available_vectors']}/{report['total_vectors']} vectors available.")
        print(report['note'])
        print('Start the website: uv run --locked python -m website.api.server')
    return 0 if report['ok'] else 1


if __name__=='__main__':
    raise SystemExit(main())
