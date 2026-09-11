import os
import sys
import pytest

os.environ.setdefault("MAX_FORK_WORKERS", "1")


@pytest.fixture(autouse=True)
def clean_sys_path():
    orig_path = list(sys.path)
    orig_meta_path = list(sys.meta_path)
    orig_path_importer_cache = dict(sys.path_importer_cache)
    yield
    sys.path[:] = orig_path
    sys.meta_path[:] = orig_meta_path
    sys.path_importer_cache.clear()
    sys.path_importer_cache.update(orig_path_importer_cache)
