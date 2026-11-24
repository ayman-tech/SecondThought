import pytest
import torch

from secondthought.steering_rewriter import inference_dtype


@pytest.mark.parametrize('device,precision,expected', [
    ('cpu', 'auto', torch.float32), ('mps', 'auto', torch.float32),
    ('cuda', 'auto', torch.float16), ('cuda', 'float32', torch.float32),
    ('cuda', 'float16', torch.float16), ('cpu', 'float32', torch.float32),
])
def test_deployment_precision_preserves_defaults_and_allows_float32(device, precision, expected):
    assert inference_dtype(torch.device(device), precision) == expected


@pytest.mark.parametrize('device,precision', [('cpu','float16'), ('mps','float16'), ('cuda','typo')])
def test_invalid_deployment_precision_fails_explicitly(device, precision):
    with pytest.raises(ValueError):
        inference_dtype(torch.device(device), precision)


def test_deployment_archive_excludes_credentials_data_and_links(tmp_path):
    import tarfile
    from deploy.package_source import package_source, FILES
    root = tmp_path/'repo'
    root.mkdir()
    for name in FILES:
        (root/name).write_text('fixture')
    for name in ('src/secondthought/app.py', 'artifacts/catalog/test.json',
                 'deploy/.env', 'website/private.pem', 'src/__pycache__/foo.pyc',
                 'data/synthetic/private.jsonl', '.env', 'deploy/README.md'):
        path = root/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('fixture')
    (root/'src/credential-link').symlink_to(root/'.env')
    destination = tmp_path/'source.tgz'
    package_source(root,destination)
    with tarfile.open(destination) as archive:
        names = archive.getnames()
    assert 'SecondThought/src/secondthought/app.py' in names
    assert 'SecondThought/artifacts/catalog/test.json' in names
    assert 'SecondThought/deploy/README.md' in names
    assert not any(name.endswith(('.env','.pem','.pyc')) or 'credential-link' in name or '/data/' in name for name in names)
