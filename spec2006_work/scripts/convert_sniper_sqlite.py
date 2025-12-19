#!/usr/bin/env python3
"""
Convert Sniper's sim.stats.sqlite3 database to JSON or YAML format.

Usage:
    convert_sniper_sqlite.py <sqlite_file> [--format json|yaml] [--output <output_file>]
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


def get_table_schema(cursor, table_name):
    """Get schema information for a table."""
    # Escape table name with double quotes to handle SQLite reserved words
    cursor.execute(f'PRAGMA table_info("{table_name}")')
    return cursor.fetchall()


def get_all_tables(cursor):
    """Get list of all tables in the database."""
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return [row[0] for row in cursor.fetchall()]


def convert_value(value):
    """Convert SQLite value to Python native type."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        # Try to convert numeric strings
        try:
            if '.' in value:
                return float(value)
            return int(value)
        except ValueError:
            return value
    return str(value)


def export_table_data(cursor, table_name):
    """Export all data from a table as a list of dictionaries."""
    # Escape table name with double quotes to handle SQLite reserved words
    cursor.execute(f'SELECT * FROM "{table_name}"')
    columns = [description[0] for description in cursor.description]
    rows = []
    for row in cursor.fetchall():
        row_dict = {}
        for col, val in zip(columns, row):
            row_dict[col] = convert_value(val)
        rows.append(row_dict)
    return rows


def export_database(sqlite_file, format_type='json'):
    """Export entire SQLite database to dictionary structure."""
    conn = sqlite3.connect(sqlite_file)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    result = {
        'database': str(sqlite_file),
        'tables': {}
    }
    
    tables = get_all_tables(cursor)
    
    for table_name in tables:
        # Get schema
        schema = get_table_schema(cursor, table_name)
        columns = [col[1] for col in schema]
        
        # Get data
        data = export_table_data(cursor, table_name)
        
        result['tables'][table_name] = {
            'columns': columns,
            'schema': [
                {
                    'cid': col[0],
                    'name': col[1],
                    'type': col[2],
                    'notnull': bool(col[3]),
                    'default_value': col[4],
                    'pk': bool(col[5])
                }
                for col in schema
            ],
            'data': data,
            'row_count': len(data)
        }
    
    conn.close()
    return result


def main():
    parser = argparse.ArgumentParser(
        description='Convert Sniper sim.stats.sqlite3 to JSON or YAML format'
    )
    parser.add_argument(
        'sqlite_file',
        type=str,
        help='Path to sim.stats.sqlite3 file'
    )
    parser.add_argument(
        '--format',
        choices=['json', 'yaml'],
        default='json',
        help='Output format (default: json)'
    )
    parser.add_argument(
        '--output',
        type=str,
        help='Output file path (default: <sqlite_file>.<format>)'
    )
    
    args = parser.parse_args()
    
    sqlite_path = Path(args.sqlite_file)
    if not sqlite_path.exists():
        print(f"Error: File not found: {args.sqlite_file}", file=sys.stderr)
        sys.exit(1)
    
    if args.format == 'yaml' and not HAS_YAML:
        print("Error: PyYAML is required for YAML output. Install with: pip install pyyaml", file=sys.stderr)
        sys.exit(1)
    
    # Export database
    try:
        data = export_database(str(sqlite_path), args.format)
    except sqlite3.Error as e:
        print(f"Error reading SQLite database: {e}", file=sys.stderr)
        sys.exit(1)
    
    # Determine output file
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = sqlite_path.with_suffix(f'.{args.format}')
    
    # Write output
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            if args.format == 'json':
                json.dump(data, f, indent=2, ensure_ascii=False)
            else:  # yaml
                yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        
        print(f"Successfully converted {sqlite_path} to {output_path}")
        print(f"  Format: {args.format}")
        print(f"  Tables: {len(data['tables'])}")
        for table_name, table_info in data['tables'].items():
            print(f"    - {table_name}: {table_info['row_count']} rows")
    except Exception as e:
        print(f"Error writing output file: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()

