from setuptools import setup, find_packages

setup(
    name="hl-cli",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "numpy",
        "pandas",
        "scikit-learn",
        "lightgbm",
        "pandas-ta",
        "psycopg2-binary",
        "tqdm",
        "matplotlib",
        "python-dotenv"
    ],
    entry_points={
        "console_scripts": [
            "hl-cli ml-signals=scripts.run_ml_signals:main",
        ],
    }
) 