from setuptools import find_packages
from setuptools import setup

from pypots import __version__

with open("./README.md", encoding="utf-8") as f:
    README = f.read()

setup(
    name="mypypots",
    version=__version__,
    description="A Python Toolbox for Data Mining on Partially-Observed Time Series. Modified by MB",
    long_description=README,
    long_description_content_type="text/markdown",
    license="BSD-3-Clause",
    author="Wenjie Du, MB",
    author_email="wenjay.du@gmail.com",
    url="https://pypots.com/",
    project_urls={
        "Documentation": "https://docs.pypots.com/",
        "Source": "https://github.com/WenjieDu/PyPOTS/",
        "Tracker": "https://github.com/WenjieDu/PyPOTS/issues/",
        "Download": "https://github.com/WenjieDu/PyPOTS/archive/main.zip",
    },
    keywords=[
        "data mining",
        "neural networks",
        "machine learning",
        "deep learning",
        "artificial intelligence",
        "time-series analysis",
        "time series",
        "imputation",
        "classification",
        "clustering",
        "forecasting",
        "partially observed",
        "irregular sampled",
        "partially-observed time series",
        "incomplete time series",
        "missing data",
        "missing values",
    ],
    packages=find_packages(exclude=["tests"]),
    include_package_data=True,
    install_requires=[
        "numpy",
        "scikit-learn",
        "scipy",
        "torch>=1.10.0",
        "tensorboard",
        "pandas<2.0.0",
        "pygrinder>=0.2",
        "tsdb>=0.2",
        "h5py",
    ],
    python_requires=">=3.7.0",
    setup_requires=["setuptools>=38.6.0"],
    entry_points={"console_scripts": ["pypots-cli=pypots.cli.pypots_cli:main"]},
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "Intended Audience :: Education",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: BSD License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
    ],
)
