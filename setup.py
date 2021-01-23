from setuptools import setup,find_packages

with open("README.md", 'r') as f:
    README = f.read()

setup(
   name='bandl',
   version='0.1.0',
   description='Utilities for the analysis of financial data',
   license="MIT",
   long_description=README,
   long_description_content_type='text/markdown',
   author='stolgo Developers',
   author_email='stockalgos@gmail.com',
   project_urls={
          "Organization":"http://www.bandl.io",
          "Source":"https://github.com/stockalgo/bandl",
          "Tracker":"https://github.com/stockalgo/bandl/issues"
          },
   packages=find_packages('lib'),
   package_dir = {'':'lib'},
   include_package_data=True,
   install_requires=[
            'requests',
            'pandas',
            'datetime',
            'openpyxl',
            'futures',
            'beautifulsoup4',
            'lxml'],
    classifiers=[
      'Development Status :: 5 - Production/Stable',
      'Intended Audience :: Developers',
      'Topic :: Software Development :: Build Tools',
      'License :: OSI Approved :: MIT License',
      'Programming Language :: Python :: 3',
      'Programming Language :: Python :: 3.5',
      'Programming Language :: Python :: 3.6',
      'Programming Language :: Python :: 3.7',
      'Programming Language :: Python :: 3.8',
        ],
    download_url = "https://github.com/stockalgo/bandl/archive/v0.1.0.tar.gz",
    keywords = ["python","yahoo-finance-api","coinbase-api","nse","binance-api","coinbase-pro",\
                "5paisa","nasdaq-crawler","yfinance","5paisa-trading-apis","nasdaq-python-api",\
                "yfinance-api","nasqad","samco","nse-python-api","optionchain","angelbroking-apis",\
                  "binance-python-api","coinbase-python-api","samco-python-api"]
)
