#!/usr/bin/env python3

import logging
import argparse
import psycopg2
import os
import yaml
import time

from . import args
from . import skelet


def count_table(connection, table):
    cursor = connection.cursor()

    logging.debug(f"Counting table {table}")
    try:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
    except psycopg2.ProgrammingError as e:
        logging.error(f"Failed to count(*) in {table}: {e}")
        return None
    else:
        count = cursor.fetchone()[0]
        cursor.close()
        connection.commit()
        return count


def wait_for_count(connection, table, expected):
    while True:
        count = count_table(connection, table)
        if count >= expected:
            break
        time.sleep(3)


def truncate_table(connection, table):
    cursor = connection.cursor()

    logging.debug(f"Truncating table {table}")
    try:
        cursor.execute(f"TRUNCATE TABLE {table}")
    except psycopg2.ProgrammingError as e:
        logging.error(f"Failed to truncate table {table}: {e}")
    else:
        connection.commit()


def recreate_table(connection, table, table_sql):
    """
    Drop and create new table using list of SQL commands (e.g. to create
    table and bunch of indexes)
    """
    cursor = connection.cursor()

    logging.debug(f"Dropping table {table}")
    try:
        cursor.execute(f"DROP TABLE {table}")
    except (psycopg2.InternalError, psycopg2.errors.UndefinedTable) as e:
        logging.error(f"Failed to drop {table}: {e}")
        cursor = connection.cursor()
    connection.commit()

    logging.debug(f"Createing table {table}")
    for sql in table_sql:
        cursor.execute(sql)
    connection.commit()


def null_column(connection, table, column):
    """
    Put NULL into table "table" column "column"
    """
    cursor = connection.cursor()

    logging.debug(f"Setting {table}.{column} to NULL")
    cursor.execute(f"UPDATE {table} SET {column} = NULL")
    connection.commit()


def doit(args, status_data):
    storage_db_conf = {
        'host': args.storage_db_host,
        'port': args.storage_db_port,
        'database': args.storage_db_name,
        'user': args.storage_db_user,
        'password': args.storage_db_pass,
    }
    connection = psycopg2.connect(**storage_db_conf)

    # Load tables definition
    tables_definition = yaml.load(args.tables_definition,
                                  Loader=yaml.SafeLoader)

    # If tables were not specified, that meand we are supposed to work
    # with all of them
    if args.tables == []:
        args.tables = tables_definition['tables'].keys()

    # Process all the tables
    for table in args.tables:
        if args.count:
            count = count_table(connection, table)
            print(f"There is {count} records in the {table} table")
        if args.wait_for_count:
            wait_for_count(connection, table, args.wait_for_count)
            print(f"Table {table} reached {args.wait_for_count} rows")
        if args.truncate:
            truncate_table(connection, table)
            status_data.set_now(f'parameters.storage.{table}.truncated_at')
            print(f"Table {table} truncated")
        if args.recreate:
            table_sql = tables_definition['tables'][table]
            recreate_table(connection, table, table_sql)
            status_data.set_now(f'parameters.storage.{table}.recreated_at')
            print(f"Table {table} dropped and created")
        if args.null_column:
            null_column(connection, table, args.null_column)
            status_data.set_now(f'parameters.storage.{table}.columnt_{args.null_column}_nulled_at')
            print(f"Column {table}.{args.null_column} nulled")


def main():
    parser = argparse.ArgumentParser(
        description='Script to maintain tables in storage DB',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('--tables-definition', type=argparse.FileType('r'),
                        default=open(os.getenv('TABLES_DEFINITION', 'tables.yaml'), 'r'),
                        help='File defining tables and SQL to create them (also use env variable TABLES_DEFINITION)')
    parser.add_argument('--count', action='store_true',
                        help='Count rows in the table(s)')
    parser.add_argument('--wait-for-count', type=int,
                        help='Wait till we have given number of rows'
                             ' in the table(s)')
    parser.add_argument('--truncate', action='store_true',
                        help='Truncate the table(s)')
    parser.add_argument('--recreate', action='store_true',
                        help='Just drop and create the table(s)')
    parser.add_argument('--null-column',
                        help='Put NULL to column in table specified by tables')
    parser.add_argument('tables', nargs='*', default=[],
                        help='Which tables to work with, all by default')
    args.add_storage_db_opts(parser)

    with skelet.test_setup(parser) as (params, status_data):
        doit(params, status_data)
