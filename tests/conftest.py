import os

os.environ.setdefault("HF_HOME", os.path.expanduser("~/.cache/huggingface"))


def pytest_configure(config):
    config.addinivalue_line("markers", "example: measures the committed example video with local models (slow)")
