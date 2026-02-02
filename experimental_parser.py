#!/usr/bin/env python3
"""
Experimental parser for the 288-byte Model Index Records found at offset 0x13000.
These records map Model Codes (B11, etc.) to 2KB VIN Block Indices.
"""

import struct
import os
import sys

SFFASTUS_PATH = "SFCDUS2/sffastus"

def parse_model_index_record(f, offset):
    """
    Parse a single 288-byte record.
    
    Structure hypothesis:
    0x00 - 0x05: Model Code (ASCII, 6 bytes)
    0x06 - 0x11F: Array of pairs (4 bytes each)?
                  Or just list of Block indices?
                  Based on hexdump:
                  42 31 31 20 20 20 (B11   )
                  17 19 0F 00 (Pair 1: 0x1917, 0x000F)
                  17 19 11 00 (Pair 2: 0x1917, 0x0011)
                  
                  It looks like 4-byte entries.
                  Byte 0-1: Unknown (0x1917 = 6423?)
                  Byte 2-3: Block Index (0x000F = 15)
    """
    f.seek(offset)
    data = f.read(288)
    
    if len(data) < 288:
        return None
        
    # Header: Model Code
    model_code = data[0:6].decode('latin-1', errors='replace').strip()
    
    if not model_code or not model_code[0].isalnum():
        return None
        
    entries = []
    
    # Parse payload (282 bytes)
    # 282 bytes / 4 bytes per entry = 70.5 entries? 
    # Let's assume the last 2 bytes are padding or it's not strictly 288 but packed.
    # Actually 288 - 6 = 282. 
    # Let's verify alignment.
    
    payload = data[6:]
    
    for i in range(0, len(payload), 4):
        if i + 4 > len(payload):
            break
            
        entry_data = payload[i:i+4]
        
        # Interpret as two uint16s
        # val1 = Unknown (0x1917 observed)
        # val2 = Block Index
        val1 = struct.unpack('<H', entry_data[0:2])[0]
        val2 = struct.unpack('<H', entry_data[2:4])[0]
        
        # Filter out empty/padding entries
        if val1 == 0 and val2 == 0:
            continue
            
        entries.append({
            'unknown': val1,
            'block_idx': val2,
            'offset_in_rec': 6 + i
        })
        
    return {
        'offset': offset,
        'model': model_code,
        'entries': entries
    }

def main():
    if not os.path.exists(SFFASTUS_PATH):
        print(f"Error: {SFFASTUS_PATH} not found")
        return

    print(f"=== Parsing Model Index Records (2KB Block Aligned) ===")
    
    records = []
    # Start at 0x13000, check blocks until 0x14000 (or further if valid)
    start_block_addr = 0x13000
    
    with open(SFFASTUS_PATH, 'rb') as f:
        current_block_addr = start_block_addr
        
        while True:
            # Check if this block contains valid records
            # We try to parse the first record of the block to decide
            # We are aggressive: if first record fails, we assume end of section
            
            # Theoretical max records per 2KB block: 2048 // 288 = 7
            BLOCK_SIZE = 2048
            REC_SIZE = 288
            RECS_PER_BLOCK = BLOCK_SIZE // REC_SIZE # 7
            
            valid_recs_in_block = 0
            
            for i in range(RECS_PER_BLOCK):
                rec_offset = current_block_addr + (i * REC_SIZE)
                
                rec = parse_model_index_record(f, rec_offset)
                
                if not rec or not rec['model'] or not rec['model'][0].isalnum():
                    # Invalid record found
                    break
                
                records.append(rec)
                valid_recs_in_block += 1
            
            if valid_recs_in_block == 0:
                # No valid records in this block, stop parsing blocks
                break
                
            current_block_addr += BLOCK_SIZE
            
            # Safety break to prevent infinite loops during testing
            if current_block_addr >= 0x14000:
                break
            
    # Print results
    for rec in records:
        print(f"\nModel: {rec['model']} (Offset 0x{rec['offset']:X})")
        print(f"  Entries: {len(rec['entries'])}")
        
        # Print first few entries
        hex_dump = []
        for e in rec['entries']:
            hex_dump.append(f"Blk:{e['block_idx']:04X}({e['block_idx']})")
            
        # Wrap for display
        line_width = 80
        current_line = "  "
        for item in hex_dump:
            if len(current_line) + len(item) + 2 > line_width:
                print(current_line)
                current_line = "  " + item + " "
            else:
                current_line += item + " "
        if current_line.strip():
            print(current_line)
            
    print(f"\nTotal Records Found: {len(records)}")

if __name__ == '__main__':
    main()
