from setuptools import setup, find_packages

setup(
    name='jc-gcal',  # PyPI package name
    version='0.1.0',
    packages=find_packages(),
    install_requires=[
        'jc-handy-helpers',
        'jc-debug',
        'google-api-python-client',
        'google-auth-httplib2',
        'google-auth-oauthlib',
    ],
    entry_points={
        'console_scripts': [
            'gcal=gcal.main:main',  # Command-line name 'gcal', assuming package is also 'gcal'
        ],
    },
    author='Jeff Clough',
    author_email='jeff@cloughcottage.com',
    description='A command line application to interact with Google Calendar',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    url='https://github.com/jeffclough/gcal',
    classifiers=[
        'Development Status :: 3 - Alpha',  # Or your desired status
        'Intended Audience :: End Users/Desktop',
        'License :: OSI Approved :: MIT License', # Or your desired license
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12', # Or your supported Python versions
        'Programming Language :: Python :: 3.13',
    ],
    python_requires='>=3.11', #Or whatever minimum version you require.
)
