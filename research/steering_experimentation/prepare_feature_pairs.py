"""Pinned public-source adapters for four experimental mean-difference features.

No test/benchmark corpus is used. Derived span/marker contrasts are explicitly
identified; they are not human-rated parallel rewrites. Raw data stays local.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from difflib import SequenceMatcher
import gzip
import hashlib
import io
import json
from pathlib import Path
import random
import re
import tarfile
from urllib.request import urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[2]
FEATURES = ('simplification', 'conciseness', 'empathy', 'politeness')
SOURCES = {
    'simplification': dict(path='dress-data/data-simplification.tar.bz2',
        url='https://raw.githubusercontent.com/louismartin/dress-data/d99d8846bde641d96eaaa67e6a3a16c15e90cfd1/data-simplification.tar.bz2',
        sha256='42b6b69724d9be6de33e73c4b58bd6a93c46b8b5a26e78d233eb0e463b03718b',
        dataset='WikiLarge (DRESS authors-linked mirror)', revision='d99d8846bde641d96eaaa67e6a3a16c15e90cfd1',
        pair_construction='aligned complex/simple training sentences',
        limitations='Automatically aligned Wikipedia sentences can omit facts or contain alignment errors. Filters do not prove simplification or semantic equivalence.'),
    'conciseness': dict(path='sentence-compression/data/sent-comp.train01.json.gz',
        url='https://raw.githubusercontent.com/google-research-datasets/sentence-compression/f03882c806888835822ed9ac57c117b80d17e932/data/sent-comp.train01.json.gz',
        sha256='248095421694290bb92a2c28e05ffdb7e5e6bd7afcf8838b1167cea6006d5e33',
        dataset='Google sentence-compression, train01 only', revision='f03882c806888835822ed9ac57c117b80d17e932',
        pair_construction='aligned source/compression training sentences',
        limitations='News-domain compression, not general concise writing. Compression can remove important information; no meaning-preservation guarantee.'),
    'empathy': dict(path='Empathy-Mental-Health/dataset/emotional-reactions-reddit.csv',
        url='https://raw.githubusercontent.com/behavioral-data/Empathy-Mental-Health/0e11f98901527550885dbf253bd2af92dbcec43b/dataset/emotional-reactions-reddit.csv',
        sha256='225b28ffdc257f8a997d557eb937e78b68235e6203c87c7e2203d00fef8545cc',
        dataset='EPITOME Reddit emotional reactions', revision='0e11f98901527550885dbf253bd2af92dbcec43b',
        pair_construction='derived: remove exact human-annotated emotional-reaction spans from the same response',
        limitations='Narrow emotional-acknowledgment ablation; removed versions are not human-rated low-empathy responses. Ablation can harm grammar. No inference of general empathy or mental-health capability.'),
    'politeness': dict(path='politeness-dataset/training-data',
        url='https://drive.usercontent.google.com/download?id=1E9GHwmVM9DL9-KiaIaG5lm_oagLWe908&export=download&confirm=t',
        sha256='4d772637dfe8b50e47caae42c34308d1ead3858e346f1b3d7e09c34c4fe1a6a5',
        dataset='Tag-and-Generate politeness training-ready corpus', revision='authors-linked Drive content pinned by SHA256; repository 5cd02314b4e4b802e16688812da446fe03292652',
        pair_construction='derived: delete standalone please from high-scoring P_8/P_9 training requests',
        limitations='Courtesy-marker contrast from automatically labeled email data, not human-rated matched politeness. It can learn please-associated wording rather than broad politeness.'),
}


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def normalized(text):
    return ' '.join(text.split()).casefold()


def records(feature, path):
    if feature == 'simplification':
        with tarfile.open(path) as bundle:
            base='data-simplification/wikilarge/wiki.full.aner.ori.train.'
            sources=bundle.extractfile(base+'src').read().decode().splitlines()
            targets=bundle.extractfile(base+'dst').read().decode().splitlines()
        for i,(source,target) in enumerate(zip(sources,targets,strict=True)):
            # Anonymous aligned data lacks document IDs. Related source/target
            # components are grouped below, rather than claiming document isolation.
            yield source,target,normalized(source),str(i)
    elif feature == 'conciseness':
        with gzip.open(path,'rt') as stream:
            payload=stream.read()
        decoder=json.JSONDecoder();position=0
        while position<len(payload):
            match=re.search(r'\S',payload[position:position+10])
            if match is None:
                if not payload[position:].strip():break
                raise ValueError('Malformed compression record boundary')
            position+=match.start()
            row,position=decoder.raw_decode(payload,position)
            yield row['graph']['sentence'],row['compression']['text'],row['doc_id'],row['graph']['id']
    elif feature == 'empathy':
        with path.open() as stream:
            for row in csv.DictReader(stream):
                if row['level'] not in ('1','2'):continue
                target=row['response_post'].strip();source=target
                spans=[span.strip() for span in row['rationales'].split('|') if span.strip()]
                if not spans or any(span not in target for span in spans):continue
                # Reject uncertain substring matches inside words and retain
                # only exact annotation spans; never synthesize replacements.
                for span in spans:
                    source=re.sub(r'(?<!\w)'+re.escape(span)+r'(?!\w)','',source,count=1)
                source=re.sub(r'\s+',' ',source).strip(' .,!?:;\n\t')
                yield source,target,normalized(row['seeker_post']),row['rp_id']
    else:
        with zipfile.ZipFile(path) as bundle, bundle.open('politeness.tsv') as stream:
            for i,row in enumerate(csv.DictReader(io.TextIOWrapper(stream),delimiter='\t')):
                if row['split']!='train' or row['style'] not in ('P_8','P_9'):continue
                target=row['txt'].strip()
                if not re.search(r'\bplease\b',target,re.I):continue
                source=re.sub(r'\bplease\b\s*','',target,flags=re.I)
                source=re.sub(r'\s+',' ',source).strip(' ,')
                yield source,target,normalized(source),str(i)


def rejection(feature,source,target):
    if not source or not target or normalized(source)==normalized(target):return 'empty_or_copy'
    a,b=source.split(),target.split()
    if min(len(a),len(b))<5 or max(len(a),len(b))>110:return 'length'
    if re.findall(r'\d+(?:[.,]\d+)*',source)!=re.findall(r'\d+(?:[.,]\d+)*',target):return 'numeric_change'
    if feature in ('simplification','conciseness'):
        ratio=len(b)/len(a)
        if not (.5<=ratio<=1.15 if feature=='simplification' else .4<=ratio<=.85):return 'length_ratio'
        if SequenceMatcher(None,normalized(source),normalized(target),autojunk=False).ratio()<.55:return 'large_edit'
        if re.search(r'\b(?:not|never|cannot)\b',source,re.I) and not re.search(r'\b(?:not|never|cannot)\b',target,re.I):return 'negation_removed'
    if feature=='empathy' and len(a)/len(b)<.4:return 'large_ablation'
    return None


def prepare(feature,path,output,seed=42,max_extraction=2000,max_heldout=500):
    settings=SOURCES[feature]
    if digest(path.read_bytes())!=settings['sha256']:raise ValueError('Source checksum mismatch')
    counts=Counter();pairs=[];seen=set()
    # A union-find keeps sentences occurring on either side in one split.
    parents={}
    def root(key):
        parents.setdefault(key,key)
        while parents[key]!=key:
            parents[key]=parents[parents[key]];key=parents[key]
        return key
    for source,target,group,row_id in records(feature,path):
        counts['input_candidates']+=1
        source,target=source.strip(),target.strip()
        reason=rejection(feature,source,target)
        if reason:counts['excluded_'+reason]+=1;continue
        key=(normalized(source),normalized(target))
        if key in seen:counts['excluded_duplicate_pair']+=1;continue
        seen.add(key)
        # All document/context members and connected text variants stay together.
        keys=['group:'+digest(group.encode()),'text:'+digest(key[0].encode()),'text:'+digest(key[1].encode())]
        first=root(keys[0])
        for k in keys[1:]:parents[root(k)]=first
        pairs.append(dict(source=source,target=target,group=keys[0],row_id=row_id))
    groups={}
    for pair in pairs:
        group=root(pair['group']);pair['group']=digest(group.encode())
        groups.setdefault(group,[]).append(pair)
    keys=sorted(groups);random.Random(seed).shuffle(keys)
    if len(keys)<5:raise ValueError('Not enough independent groups')
    heldout_groups=set(keys[:max(1,len(keys)//5)])
    selected=[]
    for split,maximum in (('extraction',max_extraction),('heldout',max_heldout)):
        used=set();retained=[]
        for key in keys:
            if (key in heldout_groups)!=(split=='heldout'):continue
            for pair in groups[key]:
                source=normalized(pair['source'])
                if source in used:continue
                used.add(source);retained.append(pair|dict(split=split))
        random.Random(seed).shuffle(retained)
        selected.extend(retained[:maximum]);counts[split+'_pairs']=min(len(retained),maximum)
    if min(counts['extraction_pairs'],counts['heldout_pairs'])<2:raise ValueError('Insufficient retained pairs')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in selected))
    metadata=dict(feature=feature,dataset=settings['dataset'],dataset_revision=settings['revision'],
        source_url=settings['url'],input_sha256=settings['sha256'],pairs_sha256=digest(output.read_bytes()),
        pair_construction=settings['pair_construction'],limitations=settings['limitations'],
        split_seed=seed,counts=dict(counts),
        split_policy='80/20 shuffled connected groups from training/source corpus only; shared source/target texts and available document/context IDs never cross splits; benchmarks untouched',
        filters=dict(min_words=5,max_words=110,preserve_numeric_sequence=True),
        attribution='Sharma, Miner, Atkins & Althoff (2020), University of Washington' if feature=='empathy' else settings['dataset'])
    output.with_suffix('.metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
    print(feature,json.dumps(dict(counts)),flush=True)
    return selected,metadata


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--features',nargs='+',choices=FEATURES,default=list(FEATURES))
    parser.add_argument('--sources',type=Path,default=ROOT/'data/feature_sources')
    parser.add_argument('--output',type=Path,default=ROOT/'data/lab_features')
    parser.add_argument('--download',action='store_true')
    parser.add_argument('--seed',type=int,default=42)
    parser.add_argument('--max-extraction',type=int,default=2000)
    parser.add_argument('--max-heldout',type=int,default=500)
    args=parser.parse_args()
    if min(args.max_extraction,args.max_heldout)<2:parser.error('Need at least two pairs per split')
    for feature in args.features:
        settings=SOURCES[feature];path=args.sources/settings['path']
        if args.download and not path.exists():
            with urlopen(settings['url'],timeout=180) as response:payload=response.read()
            if digest(payload)!=settings['sha256']:raise ValueError('Download checksum mismatch; obtain the pinned file from its authors')
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(payload)
        prepare(feature,path,args.output/(feature+'_pairs.jsonl'),args.seed,args.max_extraction,args.max_heldout)


if __name__=='__main__':main()
