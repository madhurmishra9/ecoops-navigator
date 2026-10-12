import pytest

from ecoops.generator import generate
from ecoops.pipeline import run
from ecoops.settings import load_settings


@pytest.fixture(scope="session")
def settings():
    return load_settings()


@pytest.fixture(scope="session")
def data():
    return generate(42)


@pytest.fixture(scope="session")
def result(data, settings):
    return run(data, settings)
