"""Small PostgreSQL adapter for StormTrack's parameterized SQL contract.

The default runtime remains SQLite. Importing this module does not connect or
require Psycopg; the optional driver is loaded only for a PostgreSQL target.
"""
import re
import sqlite3
from urllib.parse import urlsplit


class HybridRow(dict):
    """Mapping rows that also support sqlite-style positional reads."""
    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


def translate_sql(sql: str) -> str:
    """Translate qmark parameters, preserving strings/identifiers/comments.

    Percent signs must be doubled for Psycopg's binding protocol. The application
    uses ? exclusively as a parameter marker, not the PostgreSQL JSON operator.
    """
    output = []
    index = 0
    mode = None
    dollar_tag = None
    block_depth = 0
    while index < len(sql):
        char = sql[index]
        pair = sql[index:index + 2]
        if mode == 'dollar':
            if sql.startswith(dollar_tag, index):
                output.append(dollar_tag)
                index += len(dollar_tag)
                mode = None
                continue
        elif mode == 'line':
            if char == '\n':
                mode = None
        elif mode == 'block':
            if pair == '/*':
                block_depth += 1
                output.append(pair)
                index += 2
                continue
            if pair == '*/':
                block_depth -= 1
                if block_depth == 0:
                    mode = None
                output.append(pair)
                index += 2
                continue
        elif mode in ("'", '"'):
            if char == mode:
                if index + 1 < len(sql) and sql[index + 1] == mode:
                    output.append(mode * 2)
                    index += 2
                    continue
                mode = None
        else:
            if pair in ('--', '/*'):
                mode = 'line' if pair == '--' else 'block'
                block_depth = 1
                output.append(pair)
                index += 2
                continue
            if char in ("'", '"'):
                mode = char
            elif char == '$':
                match = re.match(r'\$(?:[A-Za-z_][A-Za-z_0-9]*)?\$', sql[index:])
                if match:
                    dollar_tag = match.group()
                    mode = 'dollar'
                    output.append(dollar_tag)
                    index += len(dollar_tag)
                    continue
            elif char == '?':
                output.append('%s')
                index += 1
                continue
        output.append('%%' if char == '%' else char)
        index += 1
    return ''.join(output)


class PostgresCursor:
    def __init__(self, cursor):
        self.raw = cursor

    @property
    def description(self):
        return self.raw.description

    @property
    def rowcount(self):
        return self.raw.rowcount

    def fetchone(self):
        row = self.raw.fetchone()
        return HybridRow(row) if row is not None else None

    def fetchall(self):
        return [HybridRow(row) for row in self.raw.fetchall()]

    def fetchmany(self, size=1):
        return [HybridRow(row) for row in self.raw.fetchmany(size)]

    def __iter__(self):
        return (HybridRow(row) for row in self.raw)

    def close(self):
        self.raw.close()


class PostgresConnection:
    dialect = 'postgresql'

    def __init__(self, dsn):
        try:
            import psycopg
            from psycopg.rows import dict_row
            from psycopg.conninfo import conninfo_to_dict
        except ImportError:
            raise RuntimeError('Install requirements-postgres.txt to use PostgreSQL.') from None
        self.driver = psycopg
        try:
            options = conninfo_to_dict(dsn)
            self.raw = psycopg.connect(
                dsn, autocommit=True, row_factory=dict_row,
                prepare_threshold=None, connect_timeout=10,
                sslmode=options.get('sslmode', 'require'),
            )
            self.raw.execute('SET search_path TO stormtrack, pg_catalog')
        except psycopg.Error:
            raise sqlite3.OperationalError('PostgreSQL connection failed; check backend configuration and connectivity.') from None

    def _call(self, action):
        try:
            return action()
        except self.driver.IntegrityError as exc:
            message = getattr(getattr(exc, 'diag', None), 'message_primary', None)
            raise sqlite3.IntegrityError(message or 'PostgreSQL integrity constraint failed') from None
        except self.driver.Error:
            raise sqlite3.DatabaseError('PostgreSQL operation failed; see the database configuration.') from None

    def execute(self, sql, parameters=()):
        if sql.strip().rstrip(';').upper() == 'BEGIN IMMEDIATE':
            def begin():
                self.raw.execute('BEGIN')
                # All mutators, seeding, login and transfer share this lock. A
                # waiting READ COMMITTED transaction reads the preceding commit.
                return self.raw.execute("SELECT pg_advisory_xact_lock(5461319)")
            return PostgresCursor(self._call(begin))
        return PostgresCursor(self._call(lambda: self.raw.execute(translate_sql(sql), tuple(parameters))))

    def executemany(self, sql, parameters):
        cursor = self.raw.cursor()
        self._call(lambda: cursor.executemany(translate_sql(sql), parameters))
        return PostgresCursor(cursor)

    def executescript(self, sql):
        # DDL is trusted application SQL, without external parameters. Preserve
        # function bodies and PostgreSQL percentages literally.
        return self._call(lambda: self.raw.execute(sql, prepare=False))

    def commit(self):
        self._call(self.raw.commit)

    def rollback(self):
        self._call(self.raw.rollback)

    def close(self):
        self.raw.close()
