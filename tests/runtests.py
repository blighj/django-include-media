#!/usr/bin/env python
"""
Test runner for django-include-media
"""

import argparse
import os
import sys

import django
from django.conf import settings
from django.test.utils import get_runner


def setup_test_environment():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "include_media_tests.settings")
    django.setup()


def run_tests(test_path=None):
    setup_test_environment()
    TestRunner = get_runner(settings)
    test_runner = TestRunner(verbosity=2, interactive=True)

    if test_path:
        test_labels = [test_path]
    else:
        test_labels = ["include_media_tests"]

    failures = test_runner.run_tests(test_labels)
    if failures:
        sys.exit(bool(failures))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Django tests")
    parser.add_argument(
        "test_path",
        nargs="?",
    )
    args = parser.parse_args()

    run_tests(args.test_path)
