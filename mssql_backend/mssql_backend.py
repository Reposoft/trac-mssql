#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (C) 2013 MATOBA Akihiro <matobaa+trac-hacks@gmail.com>
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.

from trac.core import *
from trac.config import Option
from trac.core import Component, implements
from trac.db.api import ConnectionBase
from trac.db.api import DatabaseManager
from trac.db.api import IDatabaseConnector
from trac.db.api import _parse_db_str, get_column_names
from trac.db.api import ConnectionBase 
from trac.db.util import ConnectionWrapper
from trac.env import IEnvironmentSetupParticipant, ISystemInfoProvider
from trac.env import BackupError
from trac.db import Table, Column
import re


try:
	import pymssql as pymssql
	has_mssql = True
except ImportError:
	has_mssql = False

# force enables this plugin in trac-admin initenv
#enabled = BoolOption("components", "mssql_backend.*", "enabled")

# Mapping from "abstract" SQL types to DB-specific types
_type_map = {
    'int64': 'bigint',
    'text': 'nvarchar(512)',
}

# TODO: You cannot use MS Access because column name 'value' can seems not use via odbc.
_column_map = {
    'key': '"key"',
#    'value': '"value"'
}

re_limit = re.compile(" LIMIT (\d+)( OFFSET (\d+))?", re.IGNORECASE)
re_order_by = re.compile("ORDER BY ", re.IGNORECASE)
re_where = re.compile("WHERE ", re.IGNORECASE)
re_equal = re.compile("(\w+)\s*=\s*(['\w]+|\?)", re.IGNORECASE)
re_isnull = re.compile("(\w+) IS NULL", re.IGNORECASE)
re_select = re.compile('SELECT( DISTINCT)?( TOP)?', re.IGNORECASE)
re_coalesce_equal = re.compile("(COALESCE\([^)]+\))=([^,]+)", re.IGNORECASE)

class MSSQLConnector(Component):
	implements(IDatabaseConnector, IEnvironmentSetupParticipant,
			   ISystemInfoProvider)

	required = False

	def __init__(self):
		self._mssql_version = None

	# ISystemInfoProvider methods

	def get_system_info(self):
		if self.required:
			yield 'pymssql', self._mssql_version

	# IDatabaseConnector methods

	def get_supported_schemes(self):
		yield ('mssql', 1)

	def init_db(self, path, schema=None, log=None, user=None, password=None,\
				host=None, port=None, params={}):
		print "User: %s" % str(user)
		print "Password: %s" % str(password)
		cnx = self.get_connection(path, log, user, password, host, port, params)
		cursor = cnx.cursor()
		if schema is None:
			from trac.db_default import schema
		for table in schema:
			for stmt in _to_sql(table):
				cursor.execute(stmt)
		cnx.commit()

	def get_connection(self, path, log=None, user=None, password=None,
					   host=None, port=None, params={}):
		cnx = MSSQLConnection(path, log, user, password, host, port, params)
		return cnx

	# IEnvironmentSetupParticipant methods

	def environment_created(self):
		pass

	def environment_needs_upgrade(self):
		return False

	def upgrade_environment(self):
		pass


class MSSQLConnection(ConnectionBase, ConnectionWrapper):
	"""Connection wrapper for MSSQL."""

	poolable = True

	def __init__(self, path, log, user=None, password=None, host=None, port=None, params={}):
		if path.startswith('/'):
			path = path[1:]
		if 'host' in params:
			host = params['host']
		cnx = pymssql.connect(database=path, user=user, password=password, host=host, port=port)
		self.schema = path
		conn = ConnectionWrapper.__init__(self, cnx, log)
		self._is_closed = False

	def cursor(self):
		cursor = SQLServerCursor(self.cnx.cursor(), self.log)
		cursor.cnx = self
		return cursor

	def rollback(self):
		try:
			self.cnx.rollback()
		except pymssql.ProgrammingError:
			self._is_closed = True

	def close(self):
		if not self._is_closed:
			try:
				self.cnx.close()
			except pymssql.ProgrammingError:
				pass # this error would mean it's already closed.  So, ignore
			self._is_closed = True


	def cast(self, column, type):
		if type == 'signed':
			type = 'int'
		elif type == 'text':
			type = 'varchar(max)'
		return 'CAST(%s AS %s)' % (column, type)

	def concat(self, *args):
		return 'concat(%s)' % ', '.join(args)

	def drop_table(self, table):
		cursor = pymssql.cursors.Cursor(self.cnx)
		cursor._defer_warnings = True  # ignore "Warning: Unknown table ..."
		cursor.execute("DROP TABLE IF EXISTS " + self.quote(table))

	def get_column_names(self, table):
		rows = self.execute("""
			SELECT column_name FROM information_schema.columns
			WHERE table_schema=%s AND table_name=%s
			""", (self.schema, table))
		return [row[0] for row in rows]

	def get_last_id(self, cursor, table, column='id'):
		return cursor.lastrowid

	def get_table_names(self):
		rows = self.execute("""
			SELECT table_name FROM information_schema.tables
			WHERE table_schema=%s""", (self.schema,))
		return [row[0] for row in rows]

	def like(self):
		return 'LIKE %s'
		# TODO quick hacked. check me.

	def like_escape(self, text):
		return text
		# TODO quick hacked. check me.

	def prefix_match(self):
		return "LIKE %s ESCAPE '/'"

	def prefix_match_value(self, prefix):
		return self.like_escape(prefix) + '%'

	def quote(self, identifier):
		return "`%s`" % identifier.replace('`', '``')

	def update_sequence(self, cursor, table, column='id'):
		# MSSQL handles sequence updates automagically
		pass



def _to_sql(table):
    sql = ["CREATE TABLE %s (" % table.name]
    coldefs = []
    for column in table.columns:
        column.name = _column_map.get(column.name, column.name)
        ctype = column.type.lower()
        ctype = _type_map.get(ctype, ctype)
        #  for SQL Server, patch for "enum" table, value is not text, use int instead.
        if table.name == 'enum' and column.name == 'value':
            ctype = 'int'
        if (table.name, column.name) in [
                ('wiki', 'text'),
                ('report', 'query'),
                ('report', 'description'),
                ('milestone', 'description'),
                ('version', 'description'),
            ]:
            ctype = 'nvarchar(MAX)'
        if (table.name, column.name) in [
                ('ticket', 'description'),
                ('ticket_change', 'oldvalue'),
                ('ticket_change', 'newvalue'),
                ('ticket_custom', 'value'),
                ('session_attribute', 'value')
            ]:
            ctype = 'nvarchar(4000)'

# I'm using SQL Userver 2012 Express
        if column.auto_increment:
            ctype = 'INT IDENTITY NOT NULL'  # SQL Server Style
#            ctype = 'INT UNSIGNED NOT NULL AUTO_INCREMENT'  # MySQL Style
#            ctype = 'SERIAL'  # PGSQL Style
#            ctype = "integer constraint P_%s PRIMARY KEY" % table.name  # SQLite Style
        else:
#            if column.name in table.key or any([column.name in index.columns for index in table.indices]):
#                ctype = {'ntext': 'nvarchar(255)'}.get(ctype, ctype)  # SQL Server cannot use text as PK
            if len(table.key) == 1 and column.name in table.key:
                ctype += " constraint P_%s PRIMARY KEY" % table.name
        coldefs.append("    %s %s" % (column.name, ctype))
    if len(table.key) > 1:
        coldefs.append("    UNIQUE (%s)" % ','.join(table.key))
    sql.append(',\n'.join(coldefs) + '\n);')
    yield '\n'.join(sql)
    for index in table.indices:
        type_ = ('INDEX', 'UNIQUE INDEX')[index.unique]
        yield "CREATE %s %s_%s_idx ON %s (%s);" % (type_, table.name,
              '_'.join(index.columns), table.name, ','.join(index.columns))


class SQLServerCursor(object):

    def __init__(self, cursor, log=None):
        self.cursor = cursor
        self.log = log

    def __getattr__(self, name):
        return getattr(self.cursor, name)

    def __iter__(self):
        while True:
            row = self.cursor.fetchone()
            if not row:
                return
            yield row

    def execute(self, sql, args=None):
        if args:
            sql = sql % (('%s',) * len(args))

        # replace __column__ IS NULL -> COALESCE(__column__, '') after ORDER BY
        match = re_order_by.search(sql)
        if match:
            end = match.end()
            for match in reversed([match for match in re_isnull.finditer(sql[end:])]):
                replacement = "COALESCE(%s,'')" % match.group(1)
                sql = sql[:end + match.start()] + replacement + sql[end + match.end():]

        # replace __column__ = %s -> CASE __column__ WHEN %s THEN '0' ELSE '1' END after ORDER BY
        match = re_order_by.search(sql)
        if match:
            end = match.end()
            for match in reversed([match for match in re_equal.finditer(sql[end:])]):
                replacement = "CASE %s WHEN %s THEN '0' ELSE '1' END" % (match.group(1), match.group(2))
                sql = sql[:end + match.start()] + replacement + sql[end + match.end():]
            for match in reversed([match for match in re_coalesce_equal.finditer(sql[end:])]):
                replacement = "CASE %s WHEN %s THEN '0' ELSE '1' END" % (match.group(1), match.group(2))
                sql = sql[:end + match.start()] + replacement + sql[end + match.end():]

        # trim duplicated columns after ORDER BY
        match = re_order_by.search(sql)
        if match:
            end = match.end()
            match = re.search("'([a-z]+)'", sql[end:])
            if match:
                column_name = match.group(1)
                re_columns = re.compile("([a-z]+.)?%s,?" % column_name)
                order_by = ' '.join([column for column in match.string.split(' ') if not re_columns.match(column)])
                self.log.debug(order_by)
                sql = sql[:end] + order_by

        # transform LIMIT clause
        match = re_limit.search(sql)
        if match:
            limit = match.group(1)
            offset = match.group(3)
            if not offset:
                # LIMIT n (without OFFSET) -> SELECT TOP n
                sql = match.string[:match.start()].replace("SELECT", "SELECT TOP %s" % limit)
            else:
                # LIMIT n OFFSET m -> OFFSET m ROWS FETCH NEXT n ROWS ONLY
                sql = match.string[:match.start()] + " OFFSET %s ROWS FETCH NEXT %s ROWS ONLY" % (offset, limit)
#                match = re_where.search(sql)
#                sql = match.string[:match.end()] + 'ROW_NUMBER() > %s, ' % limit + match.string[match.end():]
        # avoid error in "order by" in sub query
        # TODO: decide count of lines
        else:
            for match in reversed([match for match in re_select.finditer(sql) if match.group(2) == None]):
                sql = sql[:match.end()] + ' TOP 1000' + sql[match.end():]
        try:
            if self.log:  # See [trac] debug_sql in trac.ini
                self.log.debug(sql)
                self.log.debug(args)
                if args:
			self.cursor.execute(sql, tuple(args))
		else:
			self.cursor.execute(sql, ())
        except:
            self.cnx.rollback()
            raise

    def executemany(self, sql, args):
        if not args:
            return
        sql = sql % (('%s',) * len(args[0]))
        try:
            if self.log:  # See [trac] debug_sql in trac.ini
                self.log.debug(sql)
                self.log.debug(args)
            self.cursor.executemany(sql, args)
        except:
            self.cnx.rollback()
            raise

