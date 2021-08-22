'''
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''

import sqlite3
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from random import getrandbits
from textwrap import dedent
from typing import Optional
import json5
from tempfile import TemporaryDirectory

from semver import VersionInfo


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


@dataclass(frozen=True)
class Repoman:
    repo: Path
    name: str
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
        setattr(self, '__con', sqlite3.connect(self.repo_db))

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

    def add(self, name: str, version: VersionInfo, description: str, url: str):
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

    def import_(self, meta_sdist_tgz: Path):
        # FIXME: use actual exception
        assert meta_sdist_tgz.is_file()

        with tarfile.open(meta_sdist_tgz, mode='r:gz') as tar:
            names = tar.getnames()
            # FIXME: use actual exception
            assert all(self.pkg_dir in self.pkg_dir.joinpath(
                name).parents for name in names)

            try:
                package_json_path = next(f in ('meta_package.json', 'meta_package.jsonc', 'meta_package.json5')
                                         for f in names)

                with TemporaryDirectory(prefix='meta-dds-sdist-') as tmp:
                    tar.extract(package_json_path, path=tmp, set_attrs=False)
                    pkg_json = json5.load(
                        Path(tmp) / package_json_path)

                    pkg_name = pkg_json['name']
                    pkg_namespace = pkg_json['namespace']
                    pkg_version = VersionInfo.parse(pkg_json['version'])
                    pkg_desc = '[no description]'
                    pkg_deps = pkg_json.get('depends', [])
                    pkg_meta_deps = pkg_json.get(
                        'meta_dds', {}).get('depends', [])
            except StopIteration:
                # FIXME: use actual exception
                assert False, "No meta_package.json{,c,5}"

        self.add(pkg_name, pkg_version, pkg_desc,
                 f'dds:{pkg_name}@{pkg_version}')

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
