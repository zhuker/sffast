#!/usr/bin/env python3
"""Test script for figname.txt parser"""

from sffastus_parser import parse_figname_txt

def main():
    file_path = "SFCDUS2/sffastpg/win/figname.txt"

    print(f"Parsing {file_path}...")
    records = parse_figname_txt(file_path)

    print(f"\nTotal records: {len(records)}")
    print("\n=== First 10 Records ===")
    for i, record in enumerate(records[:10], 1):
        print(f"{i:3d}. Code: {record.figure_code:3s} | Description: {record.description}")

    print("\n=== Sample Records (Engine/Turbo/Brake) ===")
    keywords = ['ENGINE', 'TURBO', 'BRAKE']
    for keyword in keywords:
        matching = [r for r in records if keyword in r.description]
        if matching:
            print(f"\n{keyword}-related figures:")
            for record in matching[:5]:
                print(f"  {record.figure_code}: {record.description}")

    # Show some specific codes mentioned in DATA_FORMAT_SPEC.md
    print("\n=== Validation of Known Codes ===")
    known_codes = {
        '001': 'ENGINE ASSEMBLY',
        '010': 'PISTON & CRANKSHAFT',
        '040': 'TURBO CHARGER',
        '050': 'INTAKE MANIFOLD',
        '262': 'FRONT BRAKE',
        '263': 'REAR BRAKE'
    }

    code_index = {r.figure_code: r.description for r in records}

    for code, expected_desc in known_codes.items():
        actual_desc = code_index.get(code, '<NOT FOUND>')
        status = '✓' if expected_desc in actual_desc else '✗'
        print(f"{status} {code}: Expected '{expected_desc}' | Got '{actual_desc}'")

if __name__ == '__main__':
    main()
