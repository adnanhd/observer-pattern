#!/usr/bin/env python3
"""Setup script for CallPyBack."""

import os
import re

from setuptools import find_packages, setup


def get_version():
    version_file = os.path.join("callpyback", "__init__.py")
    with open(version_file, "r", encoding="utf-8") as f:
        content = f.read()
        version_match = re.search(r"^__version__ = ['\"]([^'\"]*)['\"]", content, re.M)
        if version_match:
            return version_match.group(1)
        raise RuntimeError("Unable to find version string.")


def get_long_description():
    readme_path = os.path.join(os.path.dirname(__file__), "README.md")
    try:
        with open(readme_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "Message-driven function pipelines with pub-sub, executors, and RPC."


setup(
    name="callpyback",
    version=get_version(),
    author="Adnan Harun Dogan",
    author_email="adnanharundogan@gmail.com",
    description="Message-driven function pipelines with pub-sub, executors, and RPC",
    long_description=get_long_description(),
    long_description_content_type="text/markdown",
    url="https://github.com/adnanharundogan/callpyback",
    project_urls={
        "Issues": "https://github.com/adnanharundogan/callpyback/issues",
        "Source": "https://github.com/adnanharundogan/callpyback",
    },
    packages=find_packages(exclude=["tests*", "examples*", "docs*"]),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Typing :: Typed",
    ],
    keywords="pipeline message-queue pub-sub executor rpc pydantic",
    python_requires=">=3.8",
    install_requires=[
        "pydantic>=2.0.0",
        "typing-extensions>=4.0.0;python_version<'3.10'",
    ],
    extras_require={
        "redis": ["redis>=4.0.0"],
        "zmq": ["pyzmq>=25.0.0"],
        "dev": [
            "pytest>=7.0.0",
            "pytest-cov>=4.0.0",
            "pytest-asyncio>=0.21.0",
            "mypy>=1.0.0",
            "ruff>=0.1.0",
        ],
    },
    include_package_data=True,
    package_data={
        "callpyback": ["py.typed"],
    },
    zip_safe=False,
)
