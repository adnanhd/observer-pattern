from setuptools import setup, find_packages
from pathlib import Path

CUR_DIR = Path(__file__).parent


if __name__ == "__main__":
    setup(
        name="callback",
        packages=find_packages(),
        version="v1.2.1",
        description="Simple and readable Pure Python callbacks!",
        long_description=(CUR_DIR / "README.md").read_text(),
        long_description_content_type="text/markdown",
        author="samuelgregorovic",
        author_email="samuelgregorovic@gmail.com",
        url="https://github.com/samuelgregorovic/callpyback",
        download_url="https://github.com/samuelgregorovic/callpyback/archive/refs/tags/v.1.2.1.tar.gz",
        keywords=["callpyback", "callback", "python", "pure", "pythonic", "background"],
        classifiers=[],
        install_requires=[],
    )

# $ python setup.py sdist
# $ twine upload dist/callpyback-v1.0.0.tar.gz
