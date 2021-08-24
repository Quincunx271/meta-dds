'''
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''

import logging
import shutil
import sqlite3
import tarfile
from argparse import ArgumentParser, Namespace
from dataclasses import dataclass, field
from pathlib import Path
from random import getrandbits
from tempfile import TemporaryDirectory
from textwrap import dedent
from typing import Iterable, List, Optional, Tuple

import json5
from semver import VersionInfo

from meta_dds import cli, logutils
from meta_dds.errors import FileNotFound, MetaDDSException
from meta_dds.package import MetaPackage, MetaPackageInfo, PackageID


_logger = logging.getLogger(__name__)


class RepomanError(MetaDDSException):
    def __init__(self, message, repo: Path):
        self.repo = repo
        super().__init__(message)

    @staticmethod
    def format(message: str, repo: Path):
        return RepomanError(f'{message} for repository directory: {repo}', repo)


class BadSDistTGZ(MetaDDSException):
    pass


class TGZHasEscapingFiles(BadSDistTGZ):
    def __init__(self, message: str, escapes: List[str]):
        self.escapes = escapes
        super().__init__(message)

    @staticmethod
    def format(message: str, escapes: List[str]) -> 'TGZHasEscapingFiles':
        escapes_str = ', '.join(escapes)
        return TGZHasEscapingFiles(f'{message}: [{escapes_str}]', escapes)


def _init_db(cur: sqlite3.Cursor, name: str):
    # Table schemas copied from DDS proper
    cur.execute(dedent('''\
    CREATE TABLE IF NOT EXISTS meta_dds_repo_packages (
        package_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        version TEXT NOT NULL,
        description TEXT NOT NULL,
        url TEXT NOT NULL,
        UNIQUE (name, version)
    );
    '''))

    cur.execute(dedent('''\
    CREATE TABLE IF NOT EXISTS meta_dds_repo_package_deps (
        dep_id INTEGER PRIMARY KEY,
        package_id INTEGER NOT NULL
            REFERENCES meta_dds_repo_packages
            ON DELETE CASCADE,
        dep_name TEXT NOT NULL,
        low TEXT NOT NULL,
        high TEXT NOT NULL,
        UNIQUE(package_id, dep_name)
    );
    '''))

    cur.execute(dedent('''\
    CREATE TABLE IF NOT EXISTS meta_dds_repo_package_meta_deps (
        dep_id INTEGER PRIMARY KEY,
        package_id INTEGER NOT NULL
            REFERENCES meta_dds_repo_packages
            ON DELETE CASCADE,
        dep_name TEXT NOT NULL,
        low TEXT NOT NULL,
        high TEXT NOT NULL,
        UNIQUE(package_id, dep_name)
    );
    '''))

    cur.execute(dedent('''\
    CREATE TABLE IF NOT EXISTS meta_dds_repo_meta (
        meta_version INTEGER DEFAULT 1,
        version INTEGER NOT NULL,
        name TEXT NOT NULL
    );
    '''))

    cur.execute(dedent('''\
    INSERT INTO meta_dds_repo_meta (version, name)
        VALUES (0, ?);
    '''), (name,))


@dataclass
class Repoman:
    repo: Path
    name: Optional[str] = None
    __con: sqlite3.Connection = field(init=False)

    @property
    def pkg_dir(self):
        return self.repo / 'meta-pkg'

    @property
    def repo_db(self):
        return self.repo / 'meta-repo.db'

    @property
    def repo_db_gz(self):
        return self.repo_db + '.gz'

    def __post_init__(self):
        if not self.repo.is_dir():
            raise RepomanError.format('Repo is not yet initialized', self.repo)
        self.__con = sqlite3.connect(self.repo_db)

    def commit(self):
        self.__con.commit()

    def close(self):
        self.__con.close()

    def init(self):
        '''
        Initialize the repo database.
        '''
        cur = self.__con.cursor()
        try:
            _init_db(cur, self.name)
        finally:
            cur.close()

    def ls(self):
        '''
        List the repo contents
        '''
        cur = self.__con.cursor()
        try:
            cur.execute('SELECT name, version FROM meta_dds_repo_packages')
            repos = cur.fetchall()
        finally:
            cur.close()

        return [f'{name}@{ver}' for name, ver in repos]

    def add(self, name: str, version: VersionInfo, description: str, url: str, additional_files: Iterable[Tuple[Path, Path]] = []):
        cur = self.__con.cursor()
        try:
            cur.execute(dedent('''\
                INSERT INTO meta_dds_repo_packages (name, version, description, url)
                    VALUES (?, ?, ?, ?);
                '''), (name, str(version), description, url))
        finally:
            cur.close()

        dest_dir = self.pkg_dir / name / str(version)
        stamp_path = dest_dir / 'url.txt'
        dest_dir.mkdir(parents=True)
        stamp_path.write_text(url)

        for dst_file, file in additional_files:
            dst_path = dest_dir / dst_file
            assert dest_dir in dst_path.parents
            shutil.copy(file, dst_path)

    def import_(self, meta_sdist_tgz: Path):
        if not meta_sdist_tgz.is_file():
            if meta_sdist_tgz.exists():
                raise FileNotFound(
                    f'Not a valid sdist file (must be a .tar.gz file): {meta_sdist_tgz}', meta_sdist_tgz)
            raise FileNotFound(
                f'File does not exist: {meta_sdist_tgz}', meta_sdist_tgz)

        with tarfile.open(meta_sdist_tgz, mode='r:gz') as tar:
            names = tar.getnames()
            bad_files = [name for name in names
                         if self.pkg_dir not in self.pkg_dir.joinpath(name).parents and name]
            if bad_files:
                raise TGZHasEscapingFiles.format(
                    f"Files escape from `{meta_sdist_tgz}'", bad_files)

            with TemporaryDirectory(prefix='meta-dds-sdist-') as tmp:
                tmp = Path(tmp)
                tar.extractall(tmp)

                if tmp.joinpath('meta_package.info.json5').is_file():
                    _logger.info(
                        'Found meta_package.info.json5 for %s', meta_sdist_tgz)
                    meta_info = json5.loads(tmp.joinpath(
                        'meta_package.info.json5').read_text())

                    info = MetaPackageInfo(
                        PackageID(
                            namespace=meta_info['namespace'], name=meta_info['name']),
                        version=VersionInfo.parse(meta_info['version']),
                    )
                    _logger.info("Loaded meta-package info: %s/%s @ %s",
                                 info.pkg_id.namespace, info.pkg_id.name, info.version)
                else:
                    info = None

                pkg: MetaPackage = MetaPackage.load(tmp, info)

                self.add(pkg.info.pkg_id.name, pkg.info.version, '[no description]',
                         f'dds:{pkg.info.pkg_id.name}@{pkg.info.version}',
                         additional_files=[
                             ('sdist.tar.gz', meta_sdist_tgz)
                         ])

    def remove(self, name: str, version: VersionInfo):
        cur = self.__con.cursor()
        try:
            cur.execute(dedent('''\
                DELETE FROM meta_dds_repo_packages
                    WHERE name = (?)
                      AND version = (?);
                '''), (name, str(version)))
        finally:
            cur.close()


def repoman_init(dds_exe: Path, repo: Path, name: Optional[str] = None):
    if name is None:
        dds_name = get_dds_repo_name(dds_exe, repo)
        name = dds_name or generate_repo_name()

    repo.mkdir()

    db = repo / 'meta-repo.db'


def get_dds_repo_name(dds_exe: Path, repo: Path) -> Optional[str]:
    return None


def _rand_hex(num) -> str:
    HEX_BITS = 4
    randbits = getrandbits(HEX_BITS * num)
    # Format as hex, with leading 0s and `num` positions
    return f'{randbits:0{num}x}'


def generate_repo_name() -> str:
    NUM_DIGITS = 12
    return f'meta-dds-repo-{_rand_hex(NUM_DIGITS)}'


def init_main(args: Namespace):
    if args.repo_dir.exists():
        if args.if_exists is cli.IfExists.REPLACE:
            _logger.info(
                'Replacing existing repo directory: %s', args.repo_dir)
            shutil.rmtree(args.repo_dir)
        elif args.if_exists is cli.IfExists.SKIP:
            _logger.info('Skipping existing repo directory: %s', args.repo_dir)
            return
        elif args.if_exists is cli.IfExists.FAIL:
            _logger.error('Repo directory already exists: %s', args.repo_dir)
            exit(1)
        else:
            _logger.critical('Unknown --if-exists option: %s', args.if_exists)
            exit(2)

    args.repo_dir.mkdir()
    Repoman(args.repo_dir, args.name).init()


def ls_main(args: Namespace):
    repoman = Repoman(args.repo_dir)
    print('\n'.join(repoman.ls()))


def add_main(args: Namespace):
    logutils.unimplemented(
        _logger, 'Network connectivity currently unsupported')


def import_main(args: Namespace):
    repoman = Repoman(args.repo_dir)
    for meta_sdist_tgz in args.meta_sdist_file_path:
        repoman.import_(meta_sdist_tgz)
        _logger.info('Imported %s', meta_sdist_tgz)


def remove_main(args: Namespace):
    repoman = Repoman(args.repo_dir)
    for pkg_id in args.pkg_id:
        name, version_str = pkg_id.split('@', maxsplit=1)
        repoman.remove(name, VersionInfo.parse(version_str))


def setup_parser(parser: ArgumentParser):
    repoman = parser.add_subparsers()

    def repo_dir(parser: ArgumentParser):
        parser.add_argument(
            'repo_dir', type=Path, help='The directory of the repository to manage')

    init = repoman.add_parser(
        'init', help='Initialize a directory as a new repository')
    cli.if_exists(
        init, help='What to do if the directory exists and is already a repository')
    init.add_argument(
        '-n', '--name', default=generate_repo_name(), help='Specify the name of the new repository (default: generated)')
    repo_dir(init)
    init.set_defaults(func=init_main)

    ls = repoman.add_parser(
        'ls', help='List the contents of a package repository directory')
    repo_dir(ls)
    ls.set_defaults(func=ls_main)

    add = repoman.add_parser(
        'add', help='Add a package listing to the repository by URL')
    repo_dir(add)
    add.add_argument('url', help='URL to add to the repository')
    add.add_argument('-d', '--description', default='[no description]')
    add.set_defaults(func=add_main)

    import_ = repoman.add_parser(
        'import', help='Import a meta- source distribution into the repository')
    repo_dir(import_)
    import_.add_argument('meta_sdist_file_path', type=Path, nargs='+',
                         help='Paths to meta- source distribution archives to import')
    import_.set_defaults(func=import_main)

    remove = repoman.add_parser(
        'remove', help='Remove packages from a Meta-DDS package repository')
    repo_dir(remove)
    remove.add_argument('pkg_id', nargs='+',
                        help='One or more identifiers of packages to remove')
    remove.set_defaults(func=remove_main)
