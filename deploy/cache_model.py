"""Download the exact catalog model into the persistent HF cache, before serving."""
from huggingface_hub import snapshot_download
from secondthought.lab.catalog import Catalog


def main():
    catalog = Catalog.load()
    if catalog.issues:
        raise ValueError(catalog.issues)
    for model in catalog.spec.models:
        path = snapshot_download(repo_id=model.repository, revision=model.revision)
        print(f'Cached {model.repository}@{model.revision}: {path}', flush=True)


if __name__ == '__main__':
    main()
