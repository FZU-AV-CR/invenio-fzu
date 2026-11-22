# SPDX-FileCopyrightText: 2026 CESNET z.s.p.o.
# SPDX-License-Identifier: MIT

"""Shared pytest fixtures for the repository's test suite."""

import pytest


@pytest.fixture(scope="module")
def create_app():
    """Return the Invenio application factory used by the pytest-invenio fixtures."""
    from invenio_app.factory import create_app as invenio_create_app

    return invenio_create_app
