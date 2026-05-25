# -*- coding: utf-8 -*-
"""
Blakever Trade - 量化投资策略研究与回测系统
安装脚本
"""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="blakever-trade",
    version="2.0.0",
    author="Blakever Team",
    author_email="blakever@example.com",
    description="量化投资策略研究与回测系统",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/blakever/blakever-trade",
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.8',
    install_requires=[
        "numpy>=1.24.0",
        "pandas>=2.0.0",
        "scipy>=1.10.0",
        "akshare>=1.11.0",
        "TA-Lib>=0.4.0",
        "talib>=0.6.8",
        "vectorbt>=0.25.0",
        "backtrader>=1.9.78",
        "scikit-learn>=1.3.0",
        "matplotlib>=3.7.0",
        "seaborn>=0.12.0",
        "plotly>=5.15.0",
        "beautifulsoup4>=4.12.0",
        "lxml>=4.9.0",
        "secure-smtplib>=0.1.1",
        "tqdm>=4.65.0",
        "pyyaml>=6.0.0",
        "python-dotenv>=1.0.0",
        "jupyter>=1.0.0",
        "ipykernel>=6.25.0",
        "pytest>=7.4.0",
        "pytest-cov>=4.1.0",
        "loguru>=0.7.0",
    ],
    entry_points={
        "console_scripts": [
            "blakever-trade=main:main",
        ],
    },
    include_package_data=True,
    package_data={
        "config": ["*.py"],
        "docs": ["*.md", "*.txt"],
    },
)
