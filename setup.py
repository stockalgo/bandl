from setuptools import setup,find_packages

with open("README.md", 'r') as f:
    README = f.read()

setup(
   name='bandl',
   version='0.0.1',
   description='Utilities for the analysis of financial data',
   license="MIT",
   long_description=README,
   long_description_content_type='text/markdown',
   author='stolgo Developers',
   author_email='stockalgos@gmail.com',
   project_urls={
          "Organization":"http://www.stolgo.com",
          "Source":"https://github.com/chiranjeevg/bandl/",
          "Tracker":"https://github.com/chiranjeevg/bandl/issues"
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
    download_url = "https://github.com/chiranjeevg/bandl/archive/v0.0.1.tar.gz",
    keywords = ['data', 'NSE', 'STOCK','FINANCE',"DERIVATIVE","API"]
)