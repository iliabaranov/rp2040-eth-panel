"""Builds the host shared library once per session, then exposes it to tests."""
import os
import subprocess

import pytest

import coredef

_HOST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "host")


@pytest.fixture(scope="session")
def lib():
    subprocess.run(["make", "-C", _HOST], check=True)
    return coredef.load()
